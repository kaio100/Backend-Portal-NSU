from __future__ import annotations

import argparse
import socket
import time
import uuid

from backend.app.core.config import settings
from backend.app.db.session import SessionLocal, init_db
from backend.app.repositories import jobs_repo
from backend.app.worker.jobs import processar_job


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NFS-e backend worker")
    parser.add_argument("--once", action="store_true", help="Processa no maximo um job e encerra")
    parser.add_argument("--sleep", type=float, default=5, help="Pausa entre buscas por jobs")
    parser.add_argument("--worker-id", default="", help="Identificador do worker")
    return parser


def processar_proximo_job(worker_id: str) -> dict:
    with SessionLocal() as db:
        job = jobs_repo.claim_next_pending_job(db, worker_id)
        if job is None:
            return {"ok": False, "motivo": "sem_job"}
        print(
            "Job reservado",
            {
                "job_id": job.id,
                "processo_id": job.processo_id,
                "empresa_id": job.empresa_id,
                "certificado_id": job.certificado_id,
                "tipo": job.tipo,
                "worker_id": worker_id,
            },
        )
        return processar_job(db, job, worker_id)


def main() -> None:
    args = build_parser().parse_args()
    worker_id = args.worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    init_db()
    print(f"Worker iniciado: {worker_id} | dry_run={settings.worker_dry_run}")

    try:
        while True:
            result = processar_proximo_job(worker_id)
            print(result)
            if args.once:
                return
            if result.get("motivo") == "sem_job":
                time.sleep(args.sleep)
    except KeyboardInterrupt:
        print("Worker interrompido.")


if __name__ == "__main__":
    main()
