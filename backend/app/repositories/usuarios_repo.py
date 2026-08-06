from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.db.models import Usuario


def create_usuario(db: Session, data: dict) -> Usuario:
    usuario = Usuario(**data)
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def get_usuario(db: Session, usuario_id: int) -> Usuario | None:
    return db.get(Usuario, usuario_id)


def get_usuario_by_email(db: Session, email: str) -> Usuario | None:
    return db.query(Usuario).filter(func.lower(Usuario.email) == (email or "").strip().lower()).first()


def list_usuarios(db: Session, empresa_id: int | None = None) -> list[Usuario]:
    query = db.query(Usuario).order_by(Usuario.email.asc())
    if empresa_id is not None:
        query = query.filter(Usuario.empresa_id == empresa_id)
    return list(query.all())
