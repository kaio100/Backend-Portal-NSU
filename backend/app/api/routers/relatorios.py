from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from backend.app.api.deps import get_db
from backend.app.schemas.notas import NotasDownloadFiltros
from backend.app.services import portal_support_service


router = APIRouter(prefix="/relatorios", tags=["relatorios"])


class RelatorioConferenciaRequest(BaseModel):
    filtros: NotasDownloadFiltros = Field(default_factory=NotasDownloadFiltros)

    @model_validator(mode="before")
    @classmethod
    def aceitar_filtros_no_corpo_raiz(cls, data):
        if isinstance(data, dict) and "filtros" not in data:
            return {"filtros": data}
        return data


@router.post("/conferencia")
def exportar_conferencia(payload: RelatorioConferenciaRequest, db: Session = Depends(get_db)):
    path, filename = portal_support_service.exportar_conferencia_xlsx(db, payload.filtros)
    return FileResponse(
        path=path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(path.unlink, missing_ok=True),
    )
