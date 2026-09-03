from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.orm import Session

from backend.app.repositories import arquivos_repo
from backend.app.services.storage_service import StorageService
from backend.app.services.storage_naming_service import build_nota_base_filename


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
    nota = getattr(arquivo, "nota", None)
    if nota is not None and arquivo.tipo.lower() in {"xml", "pdf_espelho", "pdf_original", "pdf_oficial"}:
        suffix = Path(filename).suffix or (".xml" if arquivo.tipo.lower() == "xml" else ".pdf")
        filename = f"{build_nota_base_filename(nota)}{suffix}"
    filename = filename.replace('"', "")
    content_type = arquivo.content_type or CONTENT_TYPES.get(arquivo.tipo, "application/octet-stream")
    return {
        "filename": filename,
        "content_type": content_type,
        "data": data,
        "size": len(data),
    }
