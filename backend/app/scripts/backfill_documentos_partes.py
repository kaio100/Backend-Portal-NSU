"""Preenche CNPJ/CPF de prestador e tomador ausentes a partir do XML salvo.

O motor legado so lia <CNPJ>; notas com pessoa fisica (<CPF>) entravam com
nome e sem documento. O parser do backend ja le os dois; este script aplica
nas notas existentes. Sem --executar apenas conta.

    python -m backend.app.scripts.backfill_documentos_partes
    python -m backend.app.scripts.backfill_documentos_partes --executar
"""

from __future__ import annotations

import argparse
import json
import re

from sqlalchemy import or_

from backend.app.db.models import Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.services.legacy_ingestion_service import parse_xml_resumo_bytes
from backend.app.services.storage_service import get_storage_service


def _vazio(valor) -> bool:
    return not str(valor or "").strip()


def executar(executar: bool, limite: int | None = None) -> dict:
    init_db()
    storage = get_storage_service()
    contadores = {"alvo": 0, "tomador_preenchido": 0, "prestador_preenchido": 0, "sem_documento_no_xml": 0, "erros": 0}
    with SessionLocal() as db:
        query = (
            db.query(Nota)
            .filter(Nota.xml_storage_key.isnot(None))
            .filter(or_(Nota.tomador_cnpj.is_(None), Nota.tomador_cnpj == "", Nota.prestador_cnpj.is_(None), Nota.prestador_cnpj == ""))
            .order_by(Nota.id.asc())
        )
        if limite:
            query = query.limit(limite)
        notas = query.all()
        contadores["alvo"] = len(notas)
        if not executar:
            return {"dry_run": True, **contadores}
        for indice, nota in enumerate(notas, start=1):
            try:
                resumo = parse_xml_resumo_bytes(storage.get_bytes(nota.xml_storage_key), "nota.xml")
                mudou = False
                for campo in ("tomador_cnpj", "prestador_cnpj"):
                    if _vazio(getattr(nota, campo)):
                        documento = re.sub(r"\D", "", str(resumo.get(campo) or ""))
                        if documento:
                            setattr(nota, campo, documento)
                            contadores[f"{campo.split('_')[0]}_preenchido"] += 1
                            mudou = True
                if not mudou:
                    contadores["sem_documento_no_xml"] += 1
                if indice % 100 == 0:
                    db.commit()
                    print(f"Progresso: {indice}/{len(notas)}", flush=True)
            except Exception as exc:
                db.rollback()
                contadores["erros"] += 1
                print(f"Erro na nota {nota.id}: {str(exc)[:160]}", flush=True)
        db.commit()
    return {"dry_run": False, **contadores}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--executar", action="store_true")
    parser.add_argument("--limite", type=int, default=None)
    args = parser.parse_args()
    print(json.dumps(executar(args.executar, args.limite), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
