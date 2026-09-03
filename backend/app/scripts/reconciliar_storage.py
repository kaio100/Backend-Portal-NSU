"""Compara referencias de XML/PDF no banco com os objetos existentes no storage."""

from __future__ import annotations

import argparse
import json

from backend.app.db.models import Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.services.storage_service import get_storage_service


def executar(processo_id: int | None = None) -> dict[str, object]:
    init_db()
    storage = get_storage_service()
    resultado: dict[str, object] = {"notas": 0, "referencias_verificadas": 0, "ausentes": []}
    with SessionLocal() as db:
        query = db.query(Nota)
        if processo_id is not None:
            query = query.filter(Nota.processo_id == processo_id)
        for nota in query.order_by(Nota.id.asc()):
            resultado["notas"] = int(resultado["notas"]) + 1
            for tipo, key in (("xml", nota.xml_storage_key), ("pdf_espelho", nota.pdf_espelho_storage_key)):
                if not key:
                    continue
                resultado["referencias_verificadas"] = int(resultado["referencias_verificadas"]) + 1
                if not storage.exists(key):
                    ausentes = resultado["ausentes"]
                    assert isinstance(ausentes, list)
                    ausentes.append({"nota_id": nota.id, "tipo": tipo, "storage_key": key})
    resultado["ausentes_count"] = len(resultado["ausentes"])
    return resultado


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcilia banco e storage de XML/PDF")
    parser.add_argument("--processo-id", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    resultado = executar(args.processo_id)
    print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str) if args.json else resultado)
    return 1 if resultado["ausentes_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
