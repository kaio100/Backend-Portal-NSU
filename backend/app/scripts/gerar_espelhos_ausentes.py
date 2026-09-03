"""Gera PDFs espelho ausentes a partir dos XMLs ja armazenados."""

from __future__ import annotations

import argparse
import hashlib
import tempfile
from datetime import date
from pathlib import Path

from backend.app.core.config import settings
from backend.app.db.models import Arquivo, Empresa, Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.services.danfse_service import DanfseService, friendly_pdf_filename
from backend.app.services.nfse_xml_parser import extrair_dados_nfse
from backend.app.services.storage_service import build_pdf_espelho_key, get_storage_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera PDFs espelho ausentes para notas com XML armazenado.")
    parser.add_argument("--processo-id", type=int, required=True)
    args = parser.parse_args()

    init_db()
    storage = get_storage_service()
    total = gerados = falhas = 0
    with SessionLocal() as db:
        notas = (
            db.query(Nota)
            .filter(Nota.processo_id == args.processo_id, Nota.xml_storage_key.isnot(None))
            .order_by(Nota.id.asc())
            .all()
        )
        cnpj_por_empresa = {
            empresa.id: empresa.cnpj
            for empresa in db.query(Empresa).filter(Empresa.id.in_({nota.empresa_id for nota in notas})).all()
        }
        for nota in notas:
            total += 1
            if nota.pdf_espelho_storage_key and storage.exists(nota.pdf_espelho_storage_key):
                continue
            try:
                xml_bytes = storage.get_bytes(nota.xml_storage_key)
                with tempfile.TemporaryDirectory(prefix="danfse_backfill_") as temp_dir:
                    xml_path = Path(temp_dir) / "entrada.xml"
                    xml_path.write_bytes(xml_bytes)
                    dados = extrair_dados_nfse(xml_path, prefeitura_info=None)
                    filename = friendly_pdf_filename(dados)
                    competencia = nota.competencia or nota.data_emissao or date.today()
                    key = nota.pdf_espelho_storage_key or build_pdf_espelho_key(
                        cnpj_por_empresa[nota.empresa_id], str(competencia.year), f"{competencia.month:02d}", filename
                    )
                    pdf_bytes, _ = DanfseService().generate(xml_bytes, watermark=nota.status_documento)
                storage.put_bytes(key, pdf_bytes, content_type="application/pdf")
                nota.pdf_espelho_storage_key = key
                arquivo = (
                    db.query(Arquivo)
                    .filter(Arquivo.nota_id == nota.id, Arquivo.tipo == "pdf_espelho")
                    .first()
                )
                if arquivo is None:
                    arquivo = Arquivo(
                        empresa_id=nota.empresa_id,
                        nota_id=nota.id,
                        processo_id=nota.processo_id,
                        tipo="pdf_espelho",
                        storage_backend=settings.storage_backend,
                        storage_bucket=settings.storage_bucket,
                        storage_key=key,
                    )
                    db.add(arquivo)
                arquivo.storage_key = key
                arquivo.filename = filename
                arquivo.content_type = "application/pdf"
                arquivo.tamanho_bytes = len(pdf_bytes)
                arquivo.checksum = hashlib.sha256(pdf_bytes).hexdigest()
                db.commit()
                gerados += 1
                if gerados % 10 == 0:
                    print(f"Progresso: {gerados} PDFs gerados", flush=True)
            except Exception as exc:
                db.rollback()
                falhas += 1
                print(f"Falha nota {nota.id} ({nota.numero_nfse}): {exc}", flush=True)

    print(f"Resultado: notas={total}, gerados={gerados}, falhas={falhas}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
