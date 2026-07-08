from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.db.models import Arquivo


def get_arquivo(db: Session, arquivo_id: int) -> Arquivo | None:
    return db.get(Arquivo, arquivo_id)


def get_arquivo_by_storage_key(db: Session, storage_key: str) -> Arquivo | None:
    return db.query(Arquivo).filter(Arquivo.storage_key == storage_key).first()


def list_arquivos_by_nota(db: Session, nota_id: int) -> list[Arquivo]:
    return list(
        db.query(Arquivo)
        .filter(Arquivo.nota_id == nota_id)
        .filter(Arquivo.tipo != "certificado")
        .order_by(Arquivo.id.asc())
        .all()
    )


def list_arquivos_by_notas(db: Session, nota_ids: list[int]) -> list[Arquivo]:
    if not nota_ids:
        return []
    return list(
        db.query(Arquivo)
        .filter(Arquivo.nota_id.in_(nota_ids))
        .filter(Arquivo.tipo != "certificado")
        .order_by(Arquivo.nota_id.asc(), Arquivo.id.asc())
        .all()
    )


def list_arquivos(
    db: Session,
    empresa_id: int | None = None,
    nota_id: int | None = None,
    processo_id: int | None = None,
    tipo: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Arquivo]:
    query = db.query(Arquivo).filter(Arquivo.tipo != "certificado")
    if empresa_id is not None:
        query = query.filter(Arquivo.empresa_id == empresa_id)
    if nota_id is not None:
        query = query.filter(Arquivo.nota_id == nota_id)
    if processo_id is not None:
        query = query.filter(Arquivo.processo_id == processo_id)
    if tipo:
        query = query.filter(Arquivo.tipo == tipo)

    safe_limit = min(max(limit, 1), 500)
    safe_offset = max(offset, 0)
    return list(query.order_by(Arquivo.id.desc()).offset(safe_offset).limit(safe_limit).all())


def create_arquivo(db: Session, data: dict) -> Arquivo:
    now = datetime.now(timezone.utc)
    data.setdefault("created_at", now)
    data.setdefault("updated_at", now)
    arquivo = Arquivo(**data)
    db.add(arquivo)
    db.flush()
    db.refresh(arquivo)
    return arquivo


def create_arquivo_if_missing(db: Session, data: dict) -> tuple[Arquivo, bool]:
    existente = get_arquivo_by_storage_key(db, data["storage_key"])
    if existente is not None:
        existente.updated_at = datetime.now(timezone.utc)
        if data.get("nota_id") and existente.nota_id is None:
            existente.nota_id = data["nota_id"]
        if data.get("processo_id") and existente.processo_id is None:
            existente.processo_id = data["processo_id"]
        if data.get("filename") and not existente.filename:
            existente.filename = data["filename"]
        if data.get("tipo"):
            existente.tipo = data["tipo"]
        db.add(existente)
        db.flush()
        db.refresh(existente)
        return existente, False
    return create_arquivo(db, data), True
