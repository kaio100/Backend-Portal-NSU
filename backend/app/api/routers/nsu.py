from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.db.models import Certificado, Empresa, NsuControle, Processo
from backend.app.services import nsu_control_service


router = APIRouter(tags=["nsu"])


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _nsu_payload(
    db: Session,
    empresa_id: int,
    certificado_id: int | None = None,
) -> dict:
    empresa = db.get(Empresa, empresa_id)
    certificado = db.get(Certificado, certificado_id) if certificado_id is not None else None
    query = db.query(NsuControle).filter(NsuControle.empresa_id == empresa_id)
    if certificado_id is None:
        query = query.filter(NsuControle.certificado_id.is_(None))
    else:
        query = query.filter(NsuControle.certificado_id == certificado_id)
    controle = query.order_by(NsuControle.id.desc()).first()

    maior_nsu_importado = nsu_control_service.maior_nsu_importado(db, empresa_id)
    ultimo_nsu = max(int(controle.ultimo_nsu or 0) if controle else 0, maior_nsu_importado)
    processo_query = db.query(Processo).filter(Processo.empresa_id == empresa_id)
    if certificado_id is not None:
        processo_query = processo_query.filter(Processo.certificado_id == certificado_id)
    ultimo_processo = processo_query.order_by(Processo.updated_at.desc().nullslast(), Processo.id.desc()).first()

    return {
        "status": "ok",
        "empresa_id": empresa_id,
        "empresa_nome": empresa.nome if empresa is not None else None,
        "certificado_id": certificado_id,
        "certificado_nome": certificado.nome if certificado is not None else None,
        "cnpj": (controle.cnpj if controle is not None else None) or (empresa.cnpj if empresa is not None else None),
        "ultimo_nsu": ultimo_nsu,
        "ultimo_nsu_banco": int(controle.ultimo_nsu or 0) if controle is not None else 0,
        "maior_nsu_importado": maior_nsu_importado,
        "origem": controle.origem if controle is not None else "notas",
        "ultimo_processo_id": ultimo_processo.id if ultimo_processo is not None else None,
        "status_processo": ultimo_processo.status if ultimo_processo is not None else None,
        "nsu_inicio": ultimo_processo.nsu_inicio if ultimo_processo is not None else None,
        "nsu_final": ultimo_processo.nsu_final if ultimo_processo is not None else None,
        "created_at": _iso(controle.created_at) if controle is not None else None,
        "updated_at": _iso(controle.updated_at) if controle is not None else None,
    }


@router.get("/empresas/{empresa_id}/nsu")
def get_empresa_nsu(
    empresa_id: int,
    certificado_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return _nsu_payload(db, empresa_id=empresa_id, certificado_id=certificado_id)


@router.get("/nsu/status")
def get_nsu_status(
    empresa_id: int | None = Query(default=None),
    certificado_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if empresa_id is not None:
        payload = _nsu_payload(db, empresa_id=empresa_id, certificado_id=certificado_id)
        return {**payload, "items": [payload], "total": 1}

    empresas = db.query(Empresa).order_by(Empresa.id.asc()).all()
    items = [_nsu_payload(db, empresa_id=int(empresa.id), certificado_id=None) for empresa in empresas]
    ultimo_nsu = max((int(item.get("ultimo_nsu") or 0) for item in items), default=0)
    return {
        "status": "ok",
        "items": items,
        "total": len(items),
        "ultimo_nsu": ultimo_nsu,
    }
