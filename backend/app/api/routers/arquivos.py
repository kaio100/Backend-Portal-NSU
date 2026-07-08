from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_storage
from backend.app.services import arquivos_service
from backend.app.services.arquivos_service import ArquivoServiceError
from backend.app.services.storage_service import StorageService


router = APIRouter(prefix="/arquivos", tags=["arquivos"])


def _download_status(message: str) -> int:
    if "nao encontrado" in message:
        return 404
    if "nao permitido" in message:
        return 403
    return 400


@router.get("/{arquivo_id}/download")
def download_arquivo(
    arquivo_id: int,
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    try:
        prepared = arquivos_service.preparar_download_arquivo(db, storage, arquivo_id)
    except ArquivoServiceError as exc:
        message = str(exc)
        raise HTTPException(status_code=_download_status(message), detail=message)

    filename = prepared["filename"]
    return Response(
        content=prepared["data"],
        media_type=prepared["content_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(prepared["size"]),
        },
    )

