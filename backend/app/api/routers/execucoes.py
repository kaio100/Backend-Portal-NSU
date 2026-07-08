from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.db.models import Empresa, Job, Processo


router = APIRouter(prefix="/execucoes", tags=["execucoes"])


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _normalizar_status(status: str | None) -> str:
    value = (status or "").strip().lower()
    if value == "pendente":
        return "queued"
    if value == "rodando":
        return "running"
    if value == "finalizado":
        return "completed"
    if value == "erro":
        return "failed"
    if value == "cancelado":
        return "cancelled"
    return value or "unknown"


def _execucao_item(processo: Processo, job: Job | None = None) -> dict:
    empresa = processo.empresa
    certificado = processo.certificado
    status = job.status if job is not None else processo.status
    return {
        "id": job.id if job is not None else processo.id,
        "execucao_id": job.id if job is not None else processo.id,
        "processo_id": processo.id,
        "empresa_id": processo.empresa_id,
        "empresa_nome": empresa.nome if empresa is not None else None,
        "certificado_id": processo.certificado_id,
        "certificado_nome": certificado.nome if certificado is not None else None,
        "tipo": job.tipo if job is not None else processo.tipo,
        "status": _normalizar_status(status),
        "status_original": status,
        "attempts": job.attempts if job is not None else None,
        "locked_by": job.locked_by if job is not None else None,
        "locked_at": _iso(job.locked_at) if job is not None else None,
        "available_at": _iso(job.available_at) if job is not None else None,
        "nsu_inicio": processo.nsu_inicio,
        "nsu_final": processo.nsu_final,
        "limite": processo.limite,
        "erro_resumo": (job.erro_resumo if job is not None else None) or processo.erro_resumo,
        "started_at": _iso(processo.started_at),
        "finished_at": _iso(processo.finished_at),
        "created_at": _iso(job.created_at if job is not None else processo.created_at),
        "updated_at": _iso(job.updated_at if job is not None else processo.updated_at),
    }


@router.get("")
def list_execucoes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=500),
    empresa_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Processo, Job)
        .outerjoin(Job, Job.processo_id == Processo.id)
        .outerjoin(Empresa, Empresa.id == Processo.empresa_id)
    )
    if empresa_id is not None:
        query = query.filter(Processo.empresa_id == empresa_id)
    if status:
        status_map = {
            "queued": "pendente",
            "running": "rodando",
            "completed": "finalizado",
            "failed": "erro",
            "cancelled": "cancelado",
        }
        mapped = status_map.get(status.strip().lower(), status.strip().lower())
        query = query.filter((Job.status == mapped) | (Processo.status == mapped))

    total = query.count()
    offset = (page - 1) * page_size
    rows = (
        query.order_by(
            Job.updated_at.desc().nullslast(),
            Processo.updated_at.desc().nullslast(),
            Processo.id.desc(),
        )
        .offset(offset)
        .limit(page_size)
        .all()
    )
    items = [_execucao_item(processo, job) for processo, job in rows]
    return {
        "items": items,
        "data": items,
        "results": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if page_size else 0,
    }
