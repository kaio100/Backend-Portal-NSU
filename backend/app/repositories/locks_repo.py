from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.app.db.models import LockProcessamento


def get_lock(db: Session, empresa_id: int, certificado_id: int) -> LockProcessamento | None:
    return (
        db.query(LockProcessamento)
        .filter(LockProcessamento.empresa_id == empresa_id)
        .filter(LockProcessamento.certificado_id == certificado_id)
        .first()
    )


def acquire_lock(
    db: Session,
    empresa_id: int,
    certificado_id: int,
    locked_by: str,
    ttl_seconds: int = 3600,
) -> bool:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    lock = get_lock(db, empresa_id, certificado_id)

    if lock is not None and lock.expires_at > now:
        return False

    if lock is None:
        lock = LockProcessamento(
            empresa_id=empresa_id,
            certificado_id=certificado_id,
            locked_by=locked_by,
            locked_at=now,
            expires_at=expires_at,
        )
        db.add(lock)
    else:
        lock.locked_by = locked_by
        lock.locked_at = now
        lock.expires_at = expires_at
        db.add(lock)

    db.flush()
    return True


def release_lock(db: Session, empresa_id: int, certificado_id: int, locked_by: str) -> bool:
    lock = get_lock(db, empresa_id, certificado_id)
    if lock is None or lock.locked_by != locked_by:
        return False
    db.delete(lock)
    db.flush()
    return True


def renew_lock(
    db: Session,
    empresa_id: int,
    certificado_id: int,
    locked_by: str,
    ttl_seconds: int = 3600,
) -> bool:
    lock = get_lock(db, empresa_id, certificado_id)
    if lock is None or lock.locked_by != locked_by:
        return False
    lock.expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    db.add(lock)
    db.flush()
    return True
