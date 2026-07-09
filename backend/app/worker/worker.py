from __future__ import annotations

import argparse
import socket
import time
import uuid

from backend.app.core.config import settings
from backend.app.db.session import SessionLocal, init_db
from backend.app.repositories import jobs_repo, processos_repo
from backend.app.services import consultas_service
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
        if job.tipo == "consulta_nfse" and not consultas_service.is_enabled(db):
            jobs_repo.mark_job_cancelado(db, job, "Consultas desativadas.")
            processo = processos_repo.get_processo(db, int(job.processo_id))
            if processo is not None:
                processos_repo.cancelar_processo(db, processo)
            db.commit()
            return {"ok": False, "job_id": job.id, "motivo": "consultas_desativadas"}
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
