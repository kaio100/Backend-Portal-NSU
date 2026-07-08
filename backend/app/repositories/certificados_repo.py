from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.db.models import Certificado


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
) -> list[Certificado]:
    query = db.query(Certificado).order_by(Certificado.id.desc())
    if empresa_id is not None:
        query = query.filter(Certificado.empresa_id == empresa_id)
    if ativo is not None:
        query = query.filter(Certificado.ativo == ativo)
    return list(query.all())


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
