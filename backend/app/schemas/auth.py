from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginRequest(BaseModel):
    email: str
    senha: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def validar_email(cls, value: str) -> str:
        email = (value or "").strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("Email invalido.")
        return email


class LocalSignupRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=255)
    email: str
    senha: str = Field(min_length=8)
    grupo: str = Field(default="planning_hub", min_length=1, max_length=40)

    @field_validator("email")
    @classmethod
    def validar_email_cadastro(cls, value: str) -> str:
        email = (value or "").strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("Email invalido.")
        return email

    @field_validator("grupo")
    @classmethod
    def validar_grupo(cls, value: str) -> str:
        return (value or "").strip()


class UsuarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    email: str
    nome: str | None = None
    ativo: bool
    grupo: str
    is_admin: bool = False
    papel: str = "operador"


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    usuario: UsuarioRead
