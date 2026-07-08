from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.db.models import Empresa


def create_empresa(db: Session, data: dict) -> Empresa:
    empresa = Empresa(**data)
    db.add(empresa)
    db.commit()
    db.refresh(empresa)
    return empresa


def get_empresa(db: Session, empresa_id: int) -> Empresa | None:
    return db.get(Empresa, empresa_id)


def get_empresa_by_cnpj(db: Session, cnpj: str) -> Empresa | None:
    return db.query(Empresa).filter(Empresa.cnpj == cnpj).first()


def list_empresas(db: Session, ativo: bool | None = None) -> list[Empresa]:
    query = db.query(Empresa).order_by(Empresa.nome.asc())
    if ativo is not None:
        query = query.filter(Empresa.ativo == ativo)
    return list(query.all())


def update_empresa(db: Session, empresa: Empresa, data: dict) -> Empresa:
    for key, value in data.items():
        setattr(empresa, key, value)
    db.add(empresa)
    db.commit()
    db.refresh(empresa)
    return empresa


def delete_empresa(db: Session, empresa: Empresa) -> Empresa:
    empresa.ativo = False
    db.add(empresa)
    db.commit()
    db.refresh(empresa)
    return empresa
