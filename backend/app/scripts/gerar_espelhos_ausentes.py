"""Gera PDFs espelho ausentes a partir dos XMLs ja armazenados."""

from __future__ import annotations

import argparse
import hashlib
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from backend.app.core.config import settings
from backend.app.db.models import Arquivo, Empresa, Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.services.danfse_service import DanfseService, friendly_pdf_filename
from backend.app.services.nfse_xml_parser import extrair_dados_nfse
from backend.app.services.storage_service import build_pdf_espelho_key, get_storage_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera PDFs espelho ausentes para notas com XML armazenado.")
    alvo = parser.add_mutually_exclusive_group(required=True)
    alvo.add_argument("--processo-id", type=int)
    alvo.add_argument("--empresa-id", type=int)
    alvo.add_argument("--all", action="store_true", help="Todas as notas nao arquivadas sem PDF espelho")
    parser.add_argument("--limite", type=int, default=None, help="Maximo de PDFs a gerar nesta execucao")
    args = parser.parse_args()

    init_db()
    from backend.app.core.php_runtime import configurar_php

    configurar_php()  # dompdf precisa do fileinfo/mbstring; no Windows gera o php.ini
    storage = get_storage_service()
    total = gerados = falhas = 0
    with SessionLocal() as db:
        query = db.query(Nota).filter(Nota.xml_storage_key.isnot(None))
        if args.processo_id is not None:
            query = query.filter(Nota.processo_id == args.processo_id)
        else:
            # Varredura ampla: so quem realmente nao tem espelho registrado.
            query = query.filter(Nota.pdf_espelho_storage_key.is_(None), Nota.arquivada.is_(False))
            if args.empresa_id is not None:
                query = query.filter(Nota.empresa_id == args.empresa_id)
        query = query.order_by(Nota.id.asc())
        if args.limite:
            query = query.limit(args.limite)
        notas = query.all()
        print(f"Notas alvo: {len(notas)}", flush=True)
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
                    .filter(Arquivo.nota_id == nota.id, Arquivo.tipo.in_(("PDF_ESPELHO", "pdf_espelho")))
                    .first()
                )
                if arquivo is None:
                    arquivo = Arquivo(
                        empresa_id=nota.empresa_id,
                        nota_id=nota.id,
                        processo_id=nota.processo_id,
                        # Mesmo tipo canonico que a ingestao grava.
                        tipo="PDF_ESPELHO",
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
                arquivo.updated_at = datetime.now(timezone.utc)
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
