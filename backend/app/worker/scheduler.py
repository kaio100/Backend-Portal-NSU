from __future__ import annotations

import argparse
import time

from backend.app.core.config import settings
from backend.app.db.session import SessionLocal, init_db
from backend.app.services import consultas_service
from backend.app.core.observability import alert_failure


def enqueue_consultas() -> dict[str, int]:
    with SessionLocal() as db:
        resultados = [
            consultas_service.enqueue_consultas_pendentes(db, grupo=grupo)
            for grupo in consultas_service.listar_grupos_automaticos_ativos(db)
        ]
    return {
        "certificados_enfileirados": sum(int(item.get("certificados_enfileirados", 0)) for item in resultados),
        "certificados_ignorados": sum(int(item.get("certificados_ignorados", 0)) for item in resultados),
        "grupos_processados": len(resultados),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NFS-e consultas scheduler")
    parser.add_argument("--once", action="store_true", help="Executa um ciclo e encerra")
    parser.add_argument("--sleep", type=float, default=None, help="Pausa entre ciclos em segundos")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    init_db()
    pause = max(5.0, float(args.sleep if args.sleep is not None else settings.consultas_scheduler_sleep))
    while True:
        try:
            if consultas_service.is_enabled():
                result = enqueue_consultas()
                print(result, flush=True)
        except Exception as exc:
            alert_failure("consultas_scheduler", exc)
        if args.once:
            return
        time.sleep(pause)


if __name__ == "__main__":
    main()
