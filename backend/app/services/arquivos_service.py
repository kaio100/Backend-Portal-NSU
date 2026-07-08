from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from sqlalchemy.orm import Session

from backend.app.repositories import arquivos_repo
from backend.app.services.storage_service import StorageService


class ArquivoServiceError(RuntimeError):
    pass


CONTENT_TYPES = {
    "xml": "application/xml",
    "pdf_oficial": "application/pdf",
    "pdf_original": "application/pdf",
    "pdf_espelho": "application/pdf",
    "XML": "application/xml",
    "PDF_ORIGINAL": "application/pdf",
    "PDF_ESPELHO": "application/pdf",
    "json": "application/json",
    "raw": "application/octet-stream",
    "log": "text/plain",
    "export": "application/octet-stream",
}


def preparar_download_arquivo(db: Session, storage: StorageService, arquivo_id: int) -> dict[str, Any]:
    arquivo = arquivos_repo.get_arquivo(db, arquivo_id)
    if arquivo is None:
        raise ArquivoServiceError("Arquivo nao encontrado.")
    if arquivo.tipo == "certificado":
        raise ArquivoServiceError("Download de certificado nao permitido por esta rota.")
    if not arquivo.storage_key:
        raise ArquivoServiceError("Arquivo sem chave de storage.")
    if not storage.exists(arquivo.storage_key):
        raise ArquivoServiceError("Arquivo nao encontrado no storage.")

    data = storage.get_bytes(arquivo.storage_key)
    filename = arquivo.filename or PurePosixPath(arquivo.storage_key.replace("\\", "/")).name or f"arquivo-{arquivo.id}"
    filename = filename.replace('"', "")
    content_type = arquivo.content_type or CONTENT_TYPES.get(arquivo.tipo, "application/octet-stream")
    return {
        "filename": filename,
        "content_type": content_type,
        "data": data,
        "size": len(data),
    }
