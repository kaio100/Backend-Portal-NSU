"""Revalida status de notas ja salvas usando o carimbo do PDF oficial.

Uso:
    python -m backend.app.scripts.revalidar_status_pdfs --dry-run
    python -m backend.app.scripts.revalidar_status_pdfs --all
    python -m backend.app.scripts.revalidar_status_pdfs --empresa-id 1
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from backend.app.db.models import Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.services.pdf_status_service import aplicar_status_pdf_oficial
from backend.app.services.storage_service import get_storage_service


@dataclass
class Relatorio:
    analisadas: int = 0
    sem_pdf_oficial: int = 0
    pdf_indisponivel: int = 0
    sem_carimbo: int = 0
    canceladas: int = 0
    substituidas: int = 0
    alteradas: int = 0
    erros: int = 0


def executar(empresa_id: int | None, dry_run: bool, batch_size: int = 200) -> Relatorio:
    init_db()
    storage = get_storage_service()
    relatorio = Relatorio()

    with SessionLocal() as db:
        query = db.query(Nota.id).order_by(Nota.id.asc())
        if empresa_id is not None:
            query = query.filter(Nota.empresa_id == empresa_id)
        ids = [row[0] for row in query.all()]

        for inicio in range(0, len(ids), max(1, batch_size)):
            notas = db.query(Nota).filter(Nota.id.in_(ids[inicio : inicio + batch_size])).all()
            for nota in notas:
                relatorio.analisadas += 1
                key = nota.pdf_oficial_storage_key
                if not key:
                    relatorio.sem_pdf_oficial += 1
                    continue
                try:
                    if not storage.exists(key):
                        relatorio.pdf_indisponivel += 1
                        continue
                    status_anterior = nota.status_documento
                    status = aplicar_status_pdf_oficial(nota, storage.get_bytes(key))
                except Exception:
                    relatorio.erros += 1
                    continue
                if status is None:
                    relatorio.sem_carimbo += 1
                    continue
                if status == "cancelada":
                    relatorio.canceladas += 1
                else:
                    relatorio.substituidas += 1
                if status_anterior != status:
                    relatorio.alteradas += 1
            if dry_run:
                db.rollback()
            else:
                db.commit()
    return relatorio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Revalida status pelo carimbo do PDF oficial.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--empresa-id", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args(argv)
    if not args.all and args.empresa_id is None and not args.dry_run:
        parser.error("Informe --all, --empresa-id ou use --dry-run.")
    relatorio = executar(args.empresa_id, args.dry_run, args.batch_size)
    print(relatorio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
