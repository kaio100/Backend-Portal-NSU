from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
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
    """Reserva o certificado de forma atomica.

    Antes lia o lock e depois gravava: dois workers podiam ver o mesmo lock
    vencido e os dois "adquirirem", ou um recebia erro de chave unica e o job
    ia para erro. Agora o lock vencido e tomado com um UPDATE condicional e o
    lock novo e criado dentro de um savepoint.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    tomado = db.execute(
        update(LockProcessamento)
        .where(LockProcessamento.empresa_id == empresa_id)
        .where(LockProcessamento.certificado_id == certificado_id)
        .where(LockProcessamento.expires_at < now)
        .values(locked_by=locked_by, locked_at=now, expires_at=expires_at)
        .execution_options(synchronize_session=False)
    )
    if tomado.rowcount == 1:
        db.expire_all()
        return True
    if get_lock(db, empresa_id, certificado_id) is not None:
        return False
    try:
        with db.begin_nested():
            db.add(
                LockProcessamento(
                    empresa_id=empresa_id,
                    certificado_id=certificado_id,
                    locked_by=locked_by,
                    locked_at=now,
                    expires_at=expires_at,
                )
            )
    except IntegrityError:
        # Outro worker criou o lock entre a leitura e o INSERT.
        return False
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
