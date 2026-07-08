from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    processo_id: int | None = None
    empresa_id: int | None = None
    certificado_id: int | None = None
    tipo: str | None = None
    status: str
    attempts: int | None = None
    locked_by: str | None = None
    locked_at: datetime | None = None
    available_at: datetime | None = None
    payload_json: dict | None = None
    erro_resumo: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
