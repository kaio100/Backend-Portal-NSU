from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.db.models import Secret


def create_or_update_secret(db: Session, ref: str, tipo: str, encrypted_value: str) -> Secret:
    secret = get_secret_by_ref(db, ref)
    if secret is None:
        secret = Secret(ref=ref, tipo=tipo, encrypted_value=encrypted_value)
        db.add(secret)
    else:
        secret.tipo = tipo
        secret.encrypted_value = encrypted_value
        db.add(secret)
    db.flush()
    db.refresh(secret)
    return secret


def get_secret_by_ref(db: Session, ref: str) -> Secret | None:
    return db.query(Secret).filter(Secret.ref == ref).first()


def delete_secret_by_ref(db: Session, ref: str) -> bool:
    secret = get_secret_by_ref(db, ref)
    if secret is None:
        return False
    db.delete(secret)
    db.flush()
    return True
