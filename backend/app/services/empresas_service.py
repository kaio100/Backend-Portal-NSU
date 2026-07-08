from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.db.models import Empresa
from backend.app.repositories import empresas_repo
from backend.app.schemas.empresas import EmpresaCreate, EmpresaUpdate


class EmpresaServiceError(ValueError):
    pass


def criar_empresa(db: Session, data: EmpresaCreate) -> Empresa:
    payload = data.model_dump()
    existente = empresas_repo.get_empresa_by_cnpj(db, payload["cnpj"])
    if existente:
        raise EmpresaServiceError("Empresa com este CNPJ ja existe.")
    return empresas_repo.create_empresa(db, payload)


def listar_empresas(db: Session, ativo: bool | None = None) -> list[Empresa]:
    return empresas_repo.list_empresas(db, ativo=ativo)


def obter_empresa(db: Session, empresa_id: int) -> Empresa:
    empresa = empresas_repo.get_empresa(db, empresa_id)
    if empresa is None:
        raise EmpresaServiceError("Empresa nao encontrada.")
    return empresa


def atualizar_empresa(db: Session, empresa_id: int, data: EmpresaUpdate) -> Empresa:
    empresa = obter_empresa(db, empresa_id)
    payload = data.model_dump(exclude_unset=True)
    novo_cnpj = payload.get("cnpj")
    if novo_cnpj and novo_cnpj != empresa.cnpj:
        existente = empresas_repo.get_empresa_by_cnpj(db, novo_cnpj)
        if existente:
            raise EmpresaServiceError("Empresa com este CNPJ ja existe.")
    return empresas_repo.update_empresa(db, empresa, payload)


def desativar_empresa(db: Session, empresa_id: int) -> Empresa:
    empresa = obter_empresa(db, empresa_id)
    return empresas_repo.delete_empresa(db, empresa)
