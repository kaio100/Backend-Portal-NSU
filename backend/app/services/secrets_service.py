from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.repositories import secrets_repo


class SecretsServiceError(ValueError):
    pass


SECRETS_KEY_ERROR = "SECRETS_KEY nao configurada. Gere uma chave Fernet e defina no .env."


def build_certificado_senha_ref(certificado_id: int) -> str:
    return f"certificado:{certificado_id}:senha"


def _get_fernet() -> Fernet:
    if not settings.secrets_key:
        raise SecretsServiceError(SECRETS_KEY_ERROR)
    try:
        return Fernet(settings.secrets_key.encode("utf-8"))
    except Exception as exc:
        raise SecretsServiceError("SECRETS_KEY invalida. Gere uma chave Fernet valida.") from exc


def encrypt_secret(value: str) -> str:
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(encrypted_value: str) -> str:
    try:
        return _get_fernet().decrypt(encrypted_value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretsServiceError("Nao foi possivel descriptografar o segredo.") from exc


def save_secret(db: Session, ref: str, tipo: str, value: str):
    encrypted_value = encrypt_secret(value)
    return secrets_repo.create_or_update_secret(db, ref, tipo, encrypted_value)


def get_secret_value(db: Session, ref: str) -> str:
    secret = secrets_repo.get_secret_by_ref(db, ref)
    if secret is None:
        raise SecretsServiceError("Segredo nao configurado.")
    return decrypt_secret(secret.encrypted_value)


def delete_secret(db: Session, ref: str) -> bool:
    return secrets_repo.delete_secret_by_ref(db, ref)
