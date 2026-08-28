from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_usuario, get_db
from backend.app.db.models import Usuario
from backend.app.services import cnpj_receita_service


router = APIRouter(prefix="/cnpj", tags=["cnpj"])


@router.get("/status")
def status_base_cnpj(usuario: Usuario = Depends(get_current_usuario)):
    return cnpj_receita_service.status_base()


@router.get("/{cnpj}")
def consultar_cnpj(
    cnpj: str,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_usuario),
):
    try:
        resultado = cnpj_receita_service.consultar_cnpj_cacheado(db, cnpj)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except cnpj_receita_service.CnpjReceitaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if resultado is None:
        raise HTTPException(status_code=404, detail="CNPJ nao encontrado na base da Receita.")
    return resultado
