from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.services import portal_support_service


router = APIRouter(prefix="/eventos", tags=["eventos"])


@router.get("")
def list_eventos(
    empresa_id: int | None = Query(default=None),
    nota_id: int | None = Query(default=None),
    chave_afetada: str | None = Query(default=None),
    tipo_evento: str | None = Query(default=None),
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return portal_support_service.listar_eventos(
        db,
        empresa_id=empresa_id,
        nota_id=nota_id,
        chave_afetada=chave_afetada,
        tipo_evento=tipo_evento,
        data_inicio=data_inicio,
        data_fim=data_fim,
        limit=limit,
        offset=offset,
    )
