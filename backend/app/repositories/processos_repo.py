from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.db.models import Processo


def create_processo(db: Session, data: dict) -> Processo:
    processo = Processo(**data)
    db.add(processo)
    db.flush()
    db.refresh(processo)
    return processo


def get_processo(db: Session, processo_id: int) -> Processo | None:
    return db.get(Processo, processo_id)


def list_processos(
    db: Session,
    empresa_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Processo]:
    query = db.query(Processo).order_by(Processo.id.desc())
    if empresa_id is not None:
        query = query.filter(Processo.empresa_id == empresa_id)
    if status is not None:
        query = query.filter(Processo.status == status)
    return list(query.offset(offset).limit(limit).all())


def update_processo(db: Session, processo: Processo, data: dict) -> Processo:
    for key, value in data.items():
        setattr(processo, key, value)
    db.add(processo)
    db.flush()
    db.refresh(processo)
    return processo


def cancelar_processo(db: Session, processo: Processo) -> Processo:
    return update_processo(db, processo, {"status": "cancelado"})


def mark_processo_running(db: Session, processo: Processo) -> Processo:
    return update_processo(
        db,
        processo,
        {
            "status": "rodando",
            "started_at": datetime.now(timezone.utc),
        },
    )


def mark_processo_finalizado(db: Session, processo: Processo, erro_resumo: str | None = None) -> Processo:
    return update_processo(
        db,
        processo,
        {
            "status": "finalizado",
            "erro_resumo": erro_resumo,
            "finished_at": datetime.now(timezone.utc),
        },
    )


def mark_processo_erro(db: Session, processo: Processo, erro: str) -> Processo:
    return update_processo(
        db,
        processo,
        {
            "status": "erro",
            "erro_resumo": erro,
            "finished_at": datetime.now(timezone.utc),
        },
    )
