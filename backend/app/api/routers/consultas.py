from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_usuario, get_db, require_operator
from backend.app.db.models import Usuario
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
    usuario: Usuario = Depends(get_current_usuario),
):
    return consultas_service.montar_status(db, limit=limit, grupo=usuario.grupo)


@router.post("/iniciar", response_model=ConsultaStatusResponse, dependencies=[Depends(require_operator)])
def iniciar_consultas(
    payload: ConsultaIniciarRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_usuario),
):
    consultas_service.iniciar_consultas_automaticas(db, options=payload or ConsultaIniciarRequest(), grupo=usuario.grupo)
    return consultas_service.montar_status(db, grupo=usuario.grupo)


@router.post("/desativar", response_model=ConsultaStatusResponse, dependencies=[Depends(require_operator)])
def desativar_consultas(
    payload: ConsultaDesativarRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_usuario),
):
    options = payload or ConsultaDesativarRequest()
    consultas_service.desativar_consultas_automaticas(
        db,
        cancelar_pendentes=options.cancelar_pendentes,
        cancelar_rodando=options.cancelar_rodando,
        grupo=usuario.grupo,
    )
    return consultas_service.montar_status(db, grupo=usuario.grupo)
