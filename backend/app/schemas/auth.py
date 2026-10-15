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


def _email_valido(value: str) -> str:
    email = (value or "").strip().lower()
    if not _EMAIL_RE.match(email) or len(email) > 255:
        raise ValueError("Email invalido.")
    return email


class EmailRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validar_email(cls, value: str) -> str:
        return _email_valido(value)


class CriarContaRequest(EmailRequest):
    convite: str = Field(min_length=10, max_length=200)
    nome: str = Field(min_length=1, max_length=255)
    senha: str = Field(min_length=8, max_length=128)


class VerificarEmailRequest(EmailRequest):
    codigo: str = Field(min_length=4, max_length=12)


class RedefinirSenhaRequest(EmailRequest):
    codigo: str = Field(min_length=4, max_length=12)
    nova_senha: str = Field(min_length=8, max_length=128)


class TrocarSenhaRequest(BaseModel):
    senha_atual: str = Field(min_length=1, max_length=128)
    nova_senha: str = Field(min_length=8, max_length=128)


class ConviteCreate(BaseModel):
    nome: str | None = Field(default=None, max_length=120)
    validade_dias: int = Field(default=7, ge=1, le=30)
    max_usos: int = Field(default=1, ge=1, le=50)


class MensagemResponse(BaseModel):
    ok: bool = True
    mensagem: str


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


class SenhaRequest(BaseModel):
    senha: str = Field(min_length=1, max_length=128)


class CodigoRequest(BaseModel):
    codigo: str = Field(min_length=6, max_length=12)


class AdminSessaoRequest(SenhaRequest):
    codigo: str = Field(min_length=6, max_length=12)

