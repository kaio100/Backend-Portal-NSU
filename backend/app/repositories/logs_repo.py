from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.db.models import LogProcesso


def create_log(db: Session, data: dict) -> LogProcesso:
    log = LogProcesso(**data)
    db.add(log)
    db.flush()
    db.refresh(log)
    return log


def list_logs(
    db: Session,
    processo_id: int | None = None,
    empresa_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[LogProcesso]:
    query = db.query(LogProcesso).order_by(LogProcesso.id.desc())
    if processo_id is not None:
        query = query.filter(LogProcesso.processo_id == processo_id)
    if empresa_id is not None:
        query = query.filter(LogProcesso.empresa_id == empresa_id)
    return list(query.offset(offset).limit(limit).all())
