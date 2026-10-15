from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from backend.app.core.config import settings

_PBKDF2_ALGORITHM = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 600_000
_JWT_ALGORITHM = "HS256"


class TokenError(ValueError):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{_PBKDF2_ALGORITHM}${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_hex, digest_hex = (encoded_hash or "").split("$")
        if algorithm != _PBKDF2_ALGORITHM:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        iterations = int(iterations_raw)
    except (ValueError, AttributeError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


# Hash de uma senha qualquer, usado quando o e-mail nao existe: o login leva
# o mesmo tempo nos dois casos e nao revela quais e-mails tem conta.
_HASH_PARA_TEMPO_CONSTANTE = hash_password("senha-inexistente-para-tempo-constante")


def verificar_senha_tempo_constante(password: str, encoded_hash: str | None) -> bool:
    if not encoded_hash:
        verify_password(password, _HASH_PARA_TEMPO_CONSTANTE)
        return False
    return verify_password(password, encoded_hash)


def create_access_token(usuario_id: int, empresa_id: int, versao: int = 0) -> str:
    if not settings.jwt_secret:
        raise TokenError("JWT_SECRET nao configurada. Defina uma chave no .env.")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(usuario_id),
        "empresa_id": empresa_id,
        # Trocar ou redefinir a senha incrementa usuarios.token_version e
        # invalida os tokens emitidos antes.
        "ver": int(versao or 0),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    if not settings.jwt_secret:
        raise TokenError("JWT_SECRET nao configurada. Defina uma chave no .env.")
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError("Token invalido ou expirado.") from exc


ESCOPO_ADMIN = "admin"


def create_admin_token(usuario_id: int, versao: int = 0) -> tuple[str, datetime]:
    """Token curto do painel administrativo, emitido depois de senha + 2FA.

    Vai no cabecalho X-Admin-Token, separado do token do portal, e nao serve
    como token comum (get_current_usuario recusa tokens com escopo).
    """
    if not settings.jwt_secret:
        raise TokenError("JWT_SECRET nao configurada. Defina uma chave no .env.")
    now = datetime.now(timezone.utc)
    expira = now + timedelta(minutes=settings.admin_sessao_minutos)
    payload = {"sub": str(usuario_id), "ver": int(versao or 0), "escopo": ESCOPO_ADMIN, "iat": now, "exp": expira}
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM), expira


def decode_admin_token(token: str) -> dict[str, Any]:
    payload = decode_access_token(token)
    if payload.get("escopo") != ESCOPO_ADMIN:
        raise TokenError("Token sem escopo de administrador.")
    return payload
