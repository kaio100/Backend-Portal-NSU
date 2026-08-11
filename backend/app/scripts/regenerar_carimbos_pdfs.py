"""Regenera PDFs espelho de notas canceladas ou substituidas.

Por seguranca, o comando apenas simula por padrao:

    python -m backend.app.scripts.regenerar_carimbos_pdfs
    python -m backend.app.scripts.regenerar_carimbos_pdfs --empresa-id 1

Para sobrescrever os espelhos no storage configurado:

    python -m backend.app.scripts.regenerar_carimbos_pdfs --apply --all
    python -m backend.app.scripts.regenerar_carimbos_pdfs --apply --empresa-id 1
"""

from __future__ import annotations

import argparse
import hashlib
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import func

from backend.app.db.models import Arquivo, Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.services.nfse_pdf_service import NfsePdfService
from backend.app.services.nfse_xml_parser import extrair_dados_nfse
from backend.app.services.storage_service import get_storage_service


STATUS_CARIMBO = {
    "cancelada": "cancelada",
    "cancelado": "cancelada",
    "substituida": "substituida",
    "substituido": "substituida",
}


@dataclass
class Relatorio:
    candidatas: int = 0
    simuladas: int = 0
    atualizadas: int = 0
    sem_xml: int = 0
    sem_pdf_espelho: int = 0
    arquivo_indisponivel: int = 0
    erros: int = 0


def _gerar_pdf(xml_bytes: bytes, status: str, nota_id: int) -> bytes:
    with tempfile.TemporaryDirectory(prefix=f"nfse_carimbo_{nota_id}_") as temp_dir:
        temp_path = Path(temp_dir)
        xml_path = temp_path / "nota.xml"
        pdf_path = temp_path / "nota.pdf"
        xml_path.write_bytes(xml_bytes)
        dados = extrair_dados_nfse(xml_path)
        dados["status_documento"] = status
        NfsePdfService().gerar_danfse_espelho(dados, pdf_path)
        return pdf_path.read_bytes()


def executar(empresa_id: int | None = None, dry_run: bool = True, batch_size: int = 100) -> Relatorio:
    init_db()
    storage = get_storage_service()
    relatorio = Relatorio()

    with SessionLocal() as db:
        query = db.query(Nota.id).filter(func.lower(Nota.status_documento).in_(tuple(STATUS_CARIMBO)))
        if empresa_id is not None:
            query = query.filter(Nota.empresa_id == empresa_id)
        ids = [int(row[0]) for row in query.order_by(Nota.id.asc()).all()]
        relatorio.candidatas = len(ids)

        for inicio in range(0, len(ids), max(1, batch_size)):
            notas = db.query(Nota).filter(Nota.id.in_(ids[inicio : inicio + batch_size])).all()
            for nota in notas:
                if not nota.xml_storage_key:
                    relatorio.sem_xml += 1
                    continue
                if not nota.pdf_espelho_storage_key:
                    relatorio.sem_pdf_espelho += 1
                    continue
                try:
                    if not storage.exists(nota.xml_storage_key):
                        relatorio.arquivo_indisponivel += 1
                        continue
                    status = STATUS_CARIMBO[str(nota.status_documento).strip().lower()]
                    pdf_bytes = _gerar_pdf(storage.get_bytes(nota.xml_storage_key), status, int(nota.id))
                    if dry_run:
                        relatorio.simuladas += 1
                        continue

                    meta = storage.put_bytes(
                        nota.pdf_espelho_storage_key,
                        pdf_bytes,
                        content_type="application/pdf",
                    )
                    checksum = hashlib.sha256(pdf_bytes).hexdigest()
                    arquivos = db.query(Arquivo).filter(Arquivo.storage_key == nota.pdf_espelho_storage_key).all()
                    for arquivo in arquivos:
                        arquivo.tamanho_bytes = int(meta.get("size") or len(pdf_bytes))
                        arquivo.checksum = checksum
                        arquivo.content_type = "application/pdf"
                    relatorio.atualizadas += 1
                except Exception:
                    relatorio.erros += 1
            if not dry_run:
                db.commit()

    return relatorio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenera carimbos nos PDFs espelho cancelados/substituidos.")
    parser.add_argument("--apply", action="store_true", help="Sobrescreve os PDFs no storage; sem esta opcao apenas simula.")
    parser.add_argument("--all", action="store_true", help="Processa todas as empresas.")
    parser.add_argument("--empresa-id", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args(argv)
    if args.apply and not args.all and args.empresa_id is None:
        parser.error("Para aplicar, informe --all ou --empresa-id.")
    relatorio = executar(empresa_id=args.empresa_id, dry_run=not args.apply, batch_size=args.batch_size)
    print(asdict(relatorio))
    return 1 if relatorio.erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
