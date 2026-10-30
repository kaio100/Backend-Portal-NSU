from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from backend.app.api.deps import get_current_usuario, get_db
from backend.app.db.models import Usuario
from backend.app.schemas.notas import NotasDownloadFiltros
from backend.app.services import portal_support_service, relatorio_layouts_service


router = APIRouter(prefix="/relatorios", tags=["relatorios"])


class RelatorioConferenciaRequest(BaseModel):
    filtros: NotasDownloadFiltros = Field(default_factory=NotasDownloadFiltros)
    # planning_ma (conferencia, padrao) | planning_hub (relacao de NFS-e e retencoes)
    layout: str | None = None

    @model_validator(mode="before")
    @classmethod
    def aceitar_filtros_no_corpo_raiz(cls, data):
        if isinstance(data, dict) and "filtros" not in data:
            corpo = dict(data)
            layout = corpo.pop("layout", None)
            return {"filtros": corpo, "layout": layout}
        return data


@router.post("/conferencia")
def exportar_conferencia(payload: RelatorioConferenciaRequest, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
    try:
        path, filename = relatorio_layouts_service.exportar_relatorio_xlsx(
            db, payload.filtros, grupo=usuario.grupo, layout=payload.layout
        )
    except portal_support_service.PortalSupportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(
        path=path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(path.unlink, missing_ok=True),
    )
