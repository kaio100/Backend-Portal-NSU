from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from backend.app.api.deps import get_current_usuario, require_operator
from backend.app.core.config import settings
from backend.app.db.models import Usuario
from backend.app.services.danfse_service import DanfseError, DanfseService


router = APIRouter(prefix="/api/danfse", tags=["danfse"])


@router.post("/gerar")
async def gerar_danfse(
    arquivo_xml: UploadFile = File(...),
    usuario: Usuario = Depends(get_current_usuario),
):
    require_operator(usuario)
    filename = (arquivo_xml.filename or "").lower()
    if not filename.endswith(".xml"):
        raise HTTPException(status_code=400, detail="Envie um arquivo XML da NFS-e.")
    try:
        content = await arquivo_xml.read(int(settings.danfse_xml_max_bytes) + 1)
        pdf, output_name = DanfseService().generate(content)
    except DanfseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{output_name}"',
            "Content-Length": str(len(pdf)),
        },
    )
