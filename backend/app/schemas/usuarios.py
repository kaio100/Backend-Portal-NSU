from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from backend.app.schemas.auth import _EMAIL_RE


class UsuarioCreate(BaseModel):
    empresa_id: int
    email: str
    senha: str = Field(min_length=8)
    nome: str | None = None

    @field_validator("email")
    @classmethod
    def validar_email(cls, value: str) -> str:
        email = (value or "").strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("Email invalido.")
        return email
