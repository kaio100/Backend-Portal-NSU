from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models import LogProcesso
from backend.app.repositories import logs_repo


_SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "credential",
    "credentials",
    "database_url",
    "jwt_secret",
    "password",
    "pfx_password",
    "secret",
    "secrets_key",
    "senha",
    "token",
}
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_DATABASE_URL_RE = re.compile(r"(?i)\b(postgres(?:ql)?(?:\+[a-z0-9_]+)?://)[^\s/@]+@")
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|password|senha|secret|token)=)[^&\s]+"
)


def sanitizar_texto(value: Any, max_length: int = 4000) -> str:
    texto = str(value or "")
    texto = _BEARER_RE.sub("Bearer [REDACTED]", texto)
    texto = _DATABASE_URL_RE.sub(r"\1[REDACTED]@", texto)
    texto = _QUERY_SECRET_RE.sub(r"\1[REDACTED]", texto)
    if len(texto) > max_length:
        texto = texto[:max_length] + "...[TRUNCADO]"
    return texto


def sanitizar_contexto(value: Any, depth: int = 0) -> Any:
    if depth >= 8:
        return "[TRUNCADO]"
    if isinstance(value, dict):
        resultado: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            key_normalized = key_text.strip().lower().replace("-", "_")
            if key_normalized == "traceback":
                resultado[key_text] = "[REMOVIDO]"
            elif key_normalized in _SENSITIVE_KEYS or any(
                token in key_normalized for token in ("password", "senha", "secret", "token")
            ):
                resultado[key_text] = "[REDACTED]"
            else:
                resultado[key_text] = sanitizar_contexto(item, depth + 1)
        return resultado
    if isinstance(value, (list, tuple, set)):
        return [sanitizar_contexto(item, depth + 1) for item in value]
    if isinstance(value, str):
        return sanitizar_texto(value)
    return value


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
            "mensagem": sanitizar_texto(mensagem, max_length=8000),
            "contexto_json": sanitizar_contexto(contexto),
        },
    )


def listar_logs(
    db: Session,
    processo_id: int | None = None,
    empresa_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    grupo: str | None = None,
) -> list[LogProcesso]:
    return logs_repo.list_logs(
        db,
        processo_id=processo_id,
        empresa_id=empresa_id,
        limit=limit,
        offset=offset,
        grupo=grupo,
    )
