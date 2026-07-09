from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.consultas import (
    ConsultaDesativarRequest,
    ConsultaIniciarRequest,
    ConsultaStatusResponse,
)
from backend.app.services import consultas_service


router = APIRouter(prefix="/consultas", tags=["consultas"])


@router.get("/status", response_model=ConsultaStatusResponse)
def get_consultas_status(
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return consultas_service.montar_status(db, limit=limit)


@router.post("/iniciar", response_model=ConsultaStatusResponse)
def iniciar_consultas(
    payload: ConsultaIniciarRequest | None = Body(default=None),
    db: Session = Depends(get_db),
):
    consultas_service.iniciar_consultas_automaticas(db, options=payload or ConsultaIniciarRequest())
    return consultas_service.montar_status(db)


@router.post("/desativar", response_model=ConsultaStatusResponse)
def desativar_consultas(
    payload: ConsultaDesativarRequest | None = Body(default=None),
    db: Session = Depends(get_db),
):
    consultas_service.desativar_consultas_automaticas(
        db,
        cancelar_pendentes=True,
        cancelar_rodando=True,
    )
    return consultas_service.montar_status(db)
