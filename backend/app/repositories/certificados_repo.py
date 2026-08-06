from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.db.models import Certificado, Empresa


def create_certificado(db: Session, data: dict) -> Certificado:
    certificado = Certificado(**data)
    db.add(certificado)
    db.commit()
    db.refresh(certificado)
    return certificado


def get_certificado(db: Session, certificado_id: int) -> Certificado | None:
    return db.get(Certificado, certificado_id)


def list_certificados(
    db: Session,
    empresa_id: int | None = None,
    ativo: bool | None = None,
    grupo: str | None = None,
) -> list[Certificado]:
    query = db.query(Certificado).order_by(Certificado.id.desc())
    if grupo is not None:
        query = query.join(Empresa, Empresa.id == Certificado.empresa_id).filter(Empresa.grupo == grupo)
    if empresa_id is not None:
        query = query.filter(Certificado.empresa_id == empresa_id)
    if ativo is not None:
        query = query.filter(Certificado.ativo == ativo)
    return list(query.all())


def get_certificado_no_grupo(db: Session, certificado_id: int, grupo: str) -> Certificado | None:
    return (
        db.query(Certificado)
        .join(Empresa, Empresa.id == Certificado.empresa_id)
        .filter(Certificado.id == certificado_id, Empresa.grupo == grupo)
        .first()
    )


def update_certificado(db: Session, certificado: Certificado, data: dict) -> Certificado:
    for key, value in data.items():
        setattr(certificado, key, value)
    db.add(certificado)
    db.commit()
    db.refresh(certificado)
    return certificado


def deactivate_certificado(db: Session, certificado: Certificado) -> Certificado:
    certificado.ativo = False
    db.add(certificado)
    db.commit()
    db.refresh(certificado)
    return certificado
