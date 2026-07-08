from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.services import logs_service


class LogProcessoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    processo_id: int
    empresa_id: int
    level: str
    mensagem: str
    contexto_json: dict | None = None
    created_at: datetime | None = None


router = APIRouter(tags=["logs"])


@router.get("/logs", response_model=list[LogProcessoRead])
def list_logs(
    processo_id: int | None = Query(default=None),
    empresa_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return logs_service.listar_logs(
        db,
        processo_id=processo_id,
        empresa_id=empresa_id,
        limit=limit,
        offset=offset,
    )


@router.get("/processos/{processo_id}/logs", response_model=list[LogProcessoRead])
def list_logs_processo(
    processo_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return logs_service.listar_logs(
        db,
        processo_id=processo_id,
        limit=limit,
        offset=offset,
    )
