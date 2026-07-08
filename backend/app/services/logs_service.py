from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.db.models import LogProcesso
from backend.app.repositories import logs_repo


def registrar_log(
    db: Session,
    processo_id: int,
    empresa_id: int,
    level: str,
    mensagem: str,
    contexto: dict | None = None,
) -> LogProcesso:
    return logs_repo.create_log(
        db,
        {
            "processo_id": processo_id,
            "empresa_id": empresa_id,
            "level": level,
            "mensagem": mensagem,
            "contexto_json": contexto,
        },
    )


def listar_logs(
    db: Session,
    processo_id: int | None = None,
    empresa_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[LogProcesso]:
    return logs_repo.list_logs(
        db,
        processo_id=processo_id,
        empresa_id=empresa_id,
        limit=limit,
        offset=offset,
    )
