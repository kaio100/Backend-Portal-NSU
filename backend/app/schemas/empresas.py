from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic import model_validator


def limpar_cnpj(value: str) -> str:
    return re.sub(r"\D", "", value or "")


class EmpresaBase(BaseModel):
    nome: str = Field(min_length=1, max_length=255)
    cnpj: str
    ambiente: str = "producao"
    ativo: bool = True

    @model_validator(mode="before")
    @classmethod
    def aceitar_payload_frontend(cls, data):
        if isinstance(data, dict) and not data.get("nome"):
            nome = data.get("razao_social") or data.get("nome_fantasia")
            if nome:
                data = {**data, "nome": nome}
        return data

    @field_validator("cnpj")
    @classmethod
    def validar_cnpj(cls, value: str) -> str:
        cnpj = limpar_cnpj(value)
        if len(cnpj) != 14:
            raise ValueError("CNPJ deve conter 14 digitos.")
        return cnpj

    @field_validator("ambiente")
    @classmethod
    def validar_ambiente(cls, value: str) -> str:
        ambiente = (value or "").lower().strip()
        if ambiente in {"homologacao", "homologação"}:
            return "homologacao"
        if ambiente not in {"producao", "restrita", "homologacao"}:
            raise ValueError("Ambiente deve ser 'producao' ou 'homologacao'.")
        return ambiente


class EmpresaCreate(EmpresaBase):
    pass


class EmpresaUpdate(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=255)
    cnpj: str | None = None
    ambiente: str | None = None
    ativo: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def aceitar_payload_frontend(cls, data):
        if isinstance(data, dict) and not data.get("nome"):
            nome = data.get("razao_social") or data.get("nome_fantasia")
            if nome:
                data = {**data, "nome": nome}
        return data

    @field_validator("cnpj")
    @classmethod
    def validar_cnpj(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cnpj = limpar_cnpj(value)
        if len(cnpj) != 14:
            raise ValueError("CNPJ deve conter 14 digitos.")
        return cnpj

    @field_validator("ambiente")
    @classmethod
    def validar_ambiente(cls, value: str | None) -> str | None:
        if value is None:
            return None
        ambiente = value.lower().strip()
        if ambiente in {"homologacao", "homologação"}:
            return "homologacao"
        if ambiente not in {"producao", "restrita", "homologacao"}:
            raise ValueError("Ambiente deve ser 'producao' ou 'homologacao'.")
        return ambiente


class EmpresaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    cnpj: str
    razao_social: str | None = None
    nome_fantasia: str | None = None
    ambiente: str
    ativo: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def preencher_aliases_frontend(self):
        self.razao_social = self.razao_social or self.nome
        return self
