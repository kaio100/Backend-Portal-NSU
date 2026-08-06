from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_usuario, get_db, require_empresa_grupo, require_nota_grupo
from backend.app.db.models import Usuario
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
    usuario: Usuario = Depends(get_current_usuario),
):
    if empresa_id is not None:
        require_empresa_grupo(db, empresa_id, usuario)
    if nota_id is not None:
        require_nota_grupo(db, nota_id, usuario)
    if empresa_id is None and nota_id is None:
        raise HTTPException(status_code=400, detail="Informe uma empresa ou nota do seu grupo.")
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
