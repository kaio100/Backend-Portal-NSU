"""Heartbeat independente da ingestao, durante toda a execucao real do job."""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from backend.app.db.models import Job, LockProcessamento, Processo
from backend.app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def renovar_lease(job_id: int, processo_id: int, worker_id: str) -> bool:
    # Atualizacao condicional: nunca ressuscita job cancelado ou de outro worker.
    with SessionLocal() as db:
        agora = datetime.now(timezone.utc)
        resultado = db.execute(
            update(Job).where(Job.id == job_id, Job.status == "rodando", Job.locked_by == worker_id)
            .values(updated_at=agora)
        )
        if resultado.rowcount != 1:
            db.rollback()
            return False
        db.execute(update(Processo).where(Processo.id == processo_id, Processo.status == "rodando")
                   .values(updated_at=agora))
        job = db.get(Job, job_id)
        db.execute(
            update(LockProcessamento).where(
                LockProcessamento.empresa_id == job.empresa_id,
                LockProcessamento.certificado_id == job.certificado_id,
                LockProcessamento.locked_by == worker_id,
            ).values(expires_at=agora + timedelta(hours=1))
        )
        db.commit()
        return True


@contextmanager
def manter_lease(job_id: int, processo_id: int, worker_id: str, intervalo: float = 30):
    stop = threading.Event()

    def loop():
        while not stop.wait(intervalo):
            try:
                if not renovar_lease(job_id, processo_id, worker_id):
                    return
            except Exception:
                logger.exception("Falha ao renovar heartbeat do job %s", job_id)

    thread = threading.Thread(target=loop, name=f"heartbeat-job-{job_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
