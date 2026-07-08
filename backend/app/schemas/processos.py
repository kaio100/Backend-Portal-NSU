from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ProcessoStatus = Literal["pendente", "rodando", "finalizado", "erro", "cancelado"]
ProcessoTipo = Literal["consulta_nfse", "gerar_planilha"]


class ProcessoCreate(BaseModel):
    empresa_id: int
    certificado_id: int
    tipo: ProcessoTipo = "consulta_nfse"
    nsu_inicio: int | None = None
    limite: int = Field(default=100, ge=1)
    pausa: float = Field(default=8, ge=0)
    gerar_pdf_espelho: bool = True
    baixar_pdf_oficial: bool = False

    @field_validator("nsu_inicio")
    @classmethod
    def validar_nsu_inicio(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("nsu_inicio nao pode ser negativo.")
        return value


class ProcessoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    certificado_id: int | None
    tipo: str
    status: str
    nsu_inicio: int | None = None
    nsu_final: int | None = None
    limite: int | None = None
    pausa: float | None = None
    gerar_pdf_espelho: bool
    baixar_pdf_oficial: bool
    erro_resumo: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProcessoCancelResponse(BaseModel):
    status: str
    message: str
    processo: ProcessoRead
