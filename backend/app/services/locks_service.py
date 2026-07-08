from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.repositories import locks_repo


def adquirir_lock(
    db: Session,
    empresa_id: int,
    certificado_id: int,
    locked_by: str,
    ttl_seconds: int = 3600,
) -> bool:
    return locks_repo.acquire_lock(
        db,
        empresa_id=empresa_id,
        certificado_id=certificado_id,
        locked_by=locked_by,
        ttl_seconds=ttl_seconds,
    )


def liberar_lock(db: Session, empresa_id: int, certificado_id: int, locked_by: str) -> bool:
    return locks_repo.release_lock(
        db,
        empresa_id=empresa_id,
        certificado_id=certificado_id,
        locked_by=locked_by,
    )


def renovar_lock(
    db: Session,
    empresa_id: int,
    certificado_id: int,
    locked_by: str,
    ttl_seconds: int = 3600,
) -> bool:
    return locks_repo.renew_lock(
        db,
        empresa_id=empresa_id,
        certificado_id=certificado_id,
        locked_by=locked_by,
        ttl_seconds=ttl_seconds,
    )
