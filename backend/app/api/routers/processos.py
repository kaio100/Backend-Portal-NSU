from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.api.deps import get_storage
from backend.app.schemas.jobs import JobRead
from backend.app.schemas.processos import ProcessoCancelResponse, ProcessoCreate, ProcessoRead
from backend.app.services import processos_service
from backend.app.services import portal_support_service
from backend.app.services.portal_support_service import PortalSupportError
from backend.app.services.processos_service import ProcessoServiceError
from backend.app.services.storage_service import StorageService


router = APIRouter(prefix="/processos", tags=["processos"])


def _handle_error(exc: ProcessoServiceError) -> None:
    message = str(exc)
    status_code = 404 if "nao encontrad" in message else 400
    raise HTTPException(status_code=status_code, detail=message)


def _handle_portal_error(exc: PortalSupportError) -> None:
    message = str(exc)
    status_code = 404 if "nao encontrad" in message else 400
    raise HTTPException(status_code=status_code, detail=message)


@router.post("", response_model=ProcessoRead)
def create_processo(payload: ProcessoCreate, db: Session = Depends(get_db)):
    try:
        return processos_service.criar_processo_com_job(db, payload)
    except ProcessoServiceError as exc:
        _handle_error(exc)


@router.get("", response_model=list[ProcessoRead])
def list_processos(
    empresa_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=500),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        effective_limit = page_size or limit
        effective_offset = ((page - 1) * effective_limit) if page is not None else offset
        return processos_service.listar_processos(
            db,
            empresa_id=empresa_id,
            status=status,
            limit=effective_limit,
            offset=effective_offset,
        )
    except ProcessoServiceError as exc:
        _handle_error(exc)


@router.get("/{processo_id}", response_model=ProcessoRead)
def get_processo(processo_id: int, db: Session = Depends(get_db)):
    try:
        return processos_service.obter_processo(db, processo_id)
    except ProcessoServiceError as exc:
        _handle_error(exc)


@router.get("/{processo_id}/arquivos")
def list_arquivos_processo(
    processo_id: int,
    tipo: str | None = Query(default=None),
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    try:
        return portal_support_service.listar_arquivos_processo(db, processo_id, tipo=tipo, storage=storage)
    except PortalSupportError as exc:
        _handle_portal_error(exc)


@router.get("/{processo_id}/notas")
def list_notas_processo(
    processo_id: int,
    status: str | None = Query(default=None),
    conferencia_status: str | None = Query(default=None),
    tipo_nota: str | None = Query(default=None),
    direcao_nota: str | None = Query(default=None),
    busca: str | None = Query(default=None),
    somente_divergentes: bool = Query(default=False),
    valor_min: Decimal | None = Query(default=None),
    valor_max: Decimal | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return portal_support_service.listar_notas_processo(
            db,
            processo_id,
            status=status,
            conferencia_status=conferencia_status,
            tipo_nota=tipo_nota,
            direcao_nota=direcao_nota,
            busca=busca,
            somente_divergentes=somente_divergentes,
            valor_min=valor_min,
            valor_max=valor_max,
            limit=limit,
            offset=offset,
        )
    except PortalSupportError as exc:
        _handle_portal_error(exc)


@router.get("/{processo_id}/summary")
def get_summary_processo(processo_id: int, db: Session = Depends(get_db)):
    try:
        return portal_support_service.resumo_processo(db, processo_id)
    except PortalSupportError as exc:
        _handle_portal_error(exc)


@router.post("/{processo_id}/cancelar", response_model=ProcessoCancelResponse)
def cancelar_processo(processo_id: int, db: Session = Depends(get_db)):
    try:
        processo, message = processos_service.cancelar_processo(db, processo_id)
        return {
            "status": processo.status,
            "message": message,
            "processo": processo,
        }
    except ProcessoServiceError as exc:
        _handle_error(exc)


@router.get("/{processo_id}/jobs", response_model=list[JobRead])
def list_jobs_processo(processo_id: int, db: Session = Depends(get_db)):
    try:
        return processos_service.listar_jobs_processo(db, processo_id)
    except ProcessoServiceError as exc:
        _handle_error(exc)
