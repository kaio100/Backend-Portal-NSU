from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

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


class ContaCreate(BaseModel):
    nome: str | None = Field(default=None, max_length=255)
    email: str
    senha: str = Field(min_length=8)
    empresa_nome: str | None = Field(default=None, min_length=1, max_length=255)
    empresa_cnpj: str | None = None
    ambiente: str = "producao"
    grupo: str = "planning_hub"

    @model_validator(mode="before")
    @classmethod
    def aceitar_aliases_frontend(cls, data):
        if isinstance(data, dict):
            empresa_nome = data.get("empresa_nome") or data.get("razao_social") or data.get("nome_empresa")
            empresa_cnpj = data.get("empresa_cnpj") or data.get("cnpj")
            data = {**data}
            if empresa_nome:
                data["empresa_nome"] = empresa_nome
            if empresa_cnpj:
                data["empresa_cnpj"] = empresa_cnpj
        return data

    @field_validator("email")
    @classmethod
    def validar_email(cls, value: str) -> str:
        email = (value or "").strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("Email invalido.")
        return email

    @field_validator("empresa_cnpj")
    @classmethod
    def validar_cnpj(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        cnpj = re.sub(r"\D", "", value or "")
        if len(cnpj) != 14:
            raise ValueError("CNPJ deve conter 14 digitos.")
        return cnpj

    @field_validator("ambiente")
    @classmethod
    def validar_ambiente(cls, value: str) -> str:
        ambiente = (value or "producao").strip().lower()
        if ambiente in {"homologacao", "homologaÃ§Ã£o"}:
            return "homologacao"
        if ambiente not in {"producao", "restrita", "homologacao"}:
            raise ValueError("Ambiente deve ser 'producao' ou 'homologacao'.")
        return ambiente

    @field_validator("grupo")
    @classmethod
    def validar_grupo(cls, value: str) -> str:
        grupo = (value or "").strip().lower().replace("/", "_")
        if not re.fullmatch(r"[a-z0-9_]{2,40}", grupo):
            raise ValueError("Grupo invalido.")
        return grupo
