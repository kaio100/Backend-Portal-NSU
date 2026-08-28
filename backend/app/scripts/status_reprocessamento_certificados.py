from __future__ import annotations

import argparse
import json
from collections import Counter

from sqlalchemy import func

from backend.app.db.models import Job, Nota, Processo
from backend.app.db.session import SessionLocal


def executar(inicio: int, fim: int) -> dict:
    with SessionLocal() as db:
        processos = (
            db.query(Processo)
            .filter(Processo.id.between(inicio, fim))
            .order_by(Processo.id)
            .all()
        )
        jobs = db.query(Job).filter(Job.processo_id.between(inicio, fim)).all()
        status_processos = Counter(str(item.status) for item in processos)
        status_jobs = Counter(str(item.status) for item in jobs)
        falhas = [
            {
                "processo_id": item.id,
                "certificado_id": item.certificado_id,
                "status": item.status,
                "erro": item.erro_resumo,
            }
            for item in processos
            if item.status in {"erro", "falhou"} or item.erro_resumo
        ]
        rodando = [
            {"processo_id": item.id, "certificado_id": item.certificado_id, "status": item.status}
            for item in processos
            if item.status in {"pendente", "rodando", "running", "queued"}
        ]
        return {
            "faixa": [inicio, fim],
            "processos_total": len(processos),
            "status_processos": dict(sorted(status_processos.items())),
            "status_jobs": dict(sorted(status_jobs.items())),
            "notas_total_banco": int(db.query(func.count(Nota.id)).scalar() or 0),
            "rodando_ou_pendentes": rodando,
            "falhas": falhas,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inicio", type=int)
    parser.add_argument("fim", type=int)
    args = parser.parse_args()
    print(json.dumps(executar(args.inicio, args.fim), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
