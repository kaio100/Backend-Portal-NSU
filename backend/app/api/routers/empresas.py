from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.schemas.empresas import EmpresaCreate, EmpresaRead, EmpresaUpdate
from backend.app.services import empresas_service
from backend.app.services import portal_support_service
from backend.app.services.empresas_service import EmpresaServiceError


router = APIRouter(prefix="/empresas", tags=["empresas"])


def _handle_error(exc: EmpresaServiceError) -> None:
    message = str(exc)
    status_code = 409 if "ja existe" in message else 404
    raise HTTPException(status_code=status_code, detail=message)


@router.post("", response_model=EmpresaRead)
def create_empresa(payload: EmpresaCreate, db: Session = Depends(get_db)):
    try:
        return empresas_service.criar_empresa(db, payload)
    except EmpresaServiceError as exc:
        _handle_error(exc)


@router.get("", response_model=list[EmpresaRead])
def list_empresas(
    ativo: bool | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return empresas_service.listar_empresas(db, ativo=ativo)


@router.get("/resumo-operacional")
def resumo_operacional_empresas(
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    competencia_inicio: date | None = Query(default=None),
    competencia_fim: date | None = Query(default=None),
    status: str | None = Query(default=None),
    conferencia_status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return portal_support_service.resumo_operacional_empresas(
        db,
        data_inicio=data_inicio,
        data_fim=data_fim,
        competencia_inicio=competencia_inicio,
        competencia_fim=competencia_fim,
        status=status,
        conferencia_status=conferencia_status,
    )


@router.get("/{empresa_id}", response_model=EmpresaRead)
def get_empresa(empresa_id: int, db: Session = Depends(get_db)):
    try:
        return empresas_service.obter_empresa(db, empresa_id)
    except EmpresaServiceError as exc:
        _handle_error(exc)


@router.patch("/{empresa_id}", response_model=EmpresaRead)
def update_empresa(empresa_id: int, payload: EmpresaUpdate, db: Session = Depends(get_db)):
    try:
        return empresas_service.atualizar_empresa(db, empresa_id, payload)
    except EmpresaServiceError as exc:
        _handle_error(exc)


@router.delete("/{empresa_id}", response_model=EmpresaRead)
def delete_empresa(empresa_id: int, db: Session = Depends(get_db)):
    try:
        return empresas_service.desativar_empresa(db, empresa_id)
    except EmpresaServiceError as exc:
        _handle_error(exc)
