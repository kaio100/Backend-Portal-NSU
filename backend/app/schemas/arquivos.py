from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, model_validator


def _canonical_tipo(value: str | None) -> str:
    normalized = (value or "").lower()
    if normalized == "xml":
        return "XML"
    if normalized in {"pdf_oficial", "pdf_original", "oficial"}:
        return "PDF_ORIGINAL"
    if normalized in {"pdf_espelho", "espelho"}:
        return "PDF_ESPELHO"
    return value or ""


class ArquivoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    nota_id: int | None = None
    processo_id: int | None = None
    tipo: str
    storage_backend: str
    storage_bucket: str | None = None
    storage_key: str
    filename: str | None = None
    content_type: str | None = None
    tamanho_bytes: int | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def preencher_aliases(self):
        self.tipo = _canonical_tipo(self.tipo)
        self.filename = self.filename or PurePosixPath((self.storage_key or "").replace("\\", "/")).name
        self.size_bytes = self.size_bytes if self.size_bytes is not None else self.tamanho_bytes
        return self


class ArquivoDownloadInfo(BaseModel):
    filename: str
    content_type: str
    size: int
