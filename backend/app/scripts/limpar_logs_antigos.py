"""Simula a retencao de logs; --aplicar executa em lotes. Preserva processos e notas."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from backend.app.db.models import LogProcesso
from backend.app.db.session import SessionLocal
from backend.app.services.operacao_service import limpar_logs_antigos


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dias", type=int, default=90)
    parser.add_argument("--lote", type=int, default=1000)
    parser.add_argument("--aplicar", action="store_true")
    args = parser.parse_args()
    if args.dias < 1 or args.lote < 1:
        parser.error("--dias e --lote devem ser positivos")
    corte = datetime.now(timezone.utc) - timedelta(days=args.dias)
    with SessionLocal() as db:
        candidatos = db.query(func.count(LogProcesso.id)).filter(LogProcesso.created_at < corte).scalar() or 0
        removidos = limpar_logs_antigos(db, lote=args.lote, dias=args.dias) if args.aplicar else 0
    print(json.dumps({"simulacao": not args.aplicar, "dias": args.dias, "corte": corte.isoformat(),
                      "candidatos": candidatos, "removidos": removidos}, ensure_ascii=False))


if __name__ == "__main__":
    main()
