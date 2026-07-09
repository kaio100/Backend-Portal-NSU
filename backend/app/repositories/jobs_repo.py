from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from backend.app.db.models import Job


def create_job(db: Session, data: dict) -> Job:
    job = Job(**data)
    db.add(job)
    db.flush()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: int) -> Job | None:
    return db.get(Job, job_id)


def list_jobs(
    db: Session,
    processo_id: int | None = None,
    empresa_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Job]:
    query = db.query(Job).order_by(Job.id.desc())
    if processo_id is not None:
        query = query.filter(Job.processo_id == processo_id)
    if empresa_id is not None:
        query = query.filter(Job.empresa_id == empresa_id)
    if status is not None:
        query = query.filter(Job.status == status)
    return list(query.offset(offset).limit(limit).all())


def update_job(db: Session, job: Job, data: dict) -> Job:
    for key, value in data.items():
        setattr(job, key, value)
    db.add(job)
    db.flush()
    db.refresh(job)
    return job


def get_next_pending_job(db: Session) -> Job | None:
    now = datetime.now(timezone.utc)
    return (
        db.query(Job)
        .filter(Job.status == "pendente")
        .filter(or_(Job.available_at.is_(None), Job.available_at <= now))
        .order_by(Job.available_at.asc().nullsfirst(), Job.id.asc())
        .first()
    )


def claim_next_pending_job(db: Session, locked_by: str) -> Job | None:
    now = datetime.now(timezone.utc)
    candidate_id = (
        db.query(Job.id)
        .filter(Job.status == "pendente")
        .filter(or_(Job.available_at.is_(None), Job.available_at <= now))
        .order_by(Job.available_at.asc().nullsfirst(), Job.id.asc())
        .limit(1)
        .scalar_subquery()
    )
    result = db.execute(
        update(Job)
        .where(Job.id == candidate_id)
        .where(Job.status == "pendente")
        .values(status="rodando", locked_by=locked_by, locked_at=now)
    )
    if result.rowcount != 1:
        db.rollback()
        return None

    db.commit()
    return (
        db.query(Job)
        .filter(Job.status == "rodando")
        .filter(Job.locked_by == locked_by)
        .order_by(Job.locked_at.desc(), Job.id.asc())
        .first()
    )


def mark_job_running(db: Session, job: Job, locked_by: str) -> Job:
    return update_job(
        db,
        job,
        {
            "status": "rodando",
            "locked_by": locked_by,
            "locked_at": datetime.now(timezone.utc),
        },
    )


def mark_job_pending(db: Session, job: Job) -> Job:
    return update_job(
        db,
        job,
        {
            "status": "pendente",
            "locked_by": None,
            "locked_at": None,
        },
    )


def mark_job_finalizado(db: Session, job: Job, mensagem: str | None = None) -> Job:
    data = {
        "status": "finalizado",
        "erro_resumo": mensagem,
    }
    return update_job(db, job, data)


def mark_job_erro(db: Session, job: Job, erro: str) -> Job:
    return update_job(
        db,
        job,
        {
            "status": "erro",
            "erro_resumo": erro,
        },
    )


def mark_job_cancelado(db: Session, job: Job, mensagem: str | None = None) -> Job:
    return update_job(
        db,
        job,
        {
            "status": "cancelado",
            "locked_by": None,
            "locked_at": None,
            "erro_resumo": mensagem,
        },
    )
