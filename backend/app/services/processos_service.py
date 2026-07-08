from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.db.models import Job, Processo
from backend.app.repositories import certificados_repo, empresas_repo, jobs_repo, processos_repo
from backend.app.schemas.processos import ProcessoCreate


STATUS_PERMITIDOS = {"pendente", "rodando", "finalizado", "erro", "cancelado"}


class ProcessoServiceError(ValueError):
    pass


def criar_processo_com_job(db: Session, payload: ProcessoCreate) -> Processo:
    empresa = empresas_repo.get_empresa(db, payload.empresa_id)
    if empresa is None:
        raise ProcessoServiceError("Empresa nao encontrada.")
    if not empresa.ativo:
        raise ProcessoServiceError("Empresa inativa.")

    certificado = certificados_repo.get_certificado(db, payload.certificado_id)
    if certificado is None:
        raise ProcessoServiceError("Certificado nao encontrado.")
    if certificado.empresa_id != empresa.id:
        raise ProcessoServiceError("Certificado nao pertence a empresa informada.")
    if not certificado.ativo:
        raise ProcessoServiceError("Certificado inativo.")

    data = payload.model_dump()
    try:
        processo = processos_repo.create_processo(
            db,
            {
                "empresa_id": payload.empresa_id,
                "certificado_id": payload.certificado_id,
                "tipo": payload.tipo,
                "status": "pendente",
                "nsu_inicio": payload.nsu_inicio,
                "limite": payload.limite,
                "pausa": payload.pausa,
                "gerar_pdf_espelho": payload.gerar_pdf_espelho,
                "baixar_pdf_oficial": payload.baixar_pdf_oficial,
            },
        )
        jobs_repo.create_job(
            db,
            {
                "processo_id": processo.id,
                "empresa_id": payload.empresa_id,
                "certificado_id": payload.certificado_id,
                "tipo": payload.tipo,
                "status": "pendente",
                "attempts": 0,
                "available_at": datetime.now(timezone.utc),
                "payload_json": data,
            },
        )
        db.commit()
        db.refresh(processo)
        return processo
    except Exception:
        db.rollback()
        raise


def listar_processos(
    db: Session,
    empresa_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Processo]:
    if status is not None and status not in STATUS_PERMITIDOS:
        raise ProcessoServiceError("Status invalido.")
    return processos_repo.list_processos(
        db,
        empresa_id=empresa_id,
        status=status,
        limit=limit,
        offset=offset,
    )


def obter_processo(db: Session, processo_id: int) -> Processo:
    processo = processos_repo.get_processo(db, processo_id)
    if processo is None:
        raise ProcessoServiceError("Processo nao encontrado.")
    return processo


def listar_jobs_processo(db: Session, processo_id: int) -> list[Job]:
    obter_processo(db, processo_id)
    return jobs_repo.list_jobs(db, processo_id=processo_id)


def cancelar_processo(db: Session, processo_id: int) -> tuple[Processo, str]:
    processo = obter_processo(db, processo_id)

    if processo.status == "rodando":
        return processo, "Cancelamento solicitado, mas worker ainda nao implementado."
    if processo.status == "cancelado":
        return processo, "Processo ja estava cancelado."
    if processo.status in {"finalizado", "erro"}:
        return processo, "Processo nao pode ser cancelado neste status."

    try:
        processos_repo.cancelar_processo(db, processo)
        jobs = jobs_repo.list_jobs(db, processo_id=processo.id, status="pendente")
        for job in jobs:
            jobs_repo.update_job(db, job, {"status": "cancelado"})
        db.commit()
        db.refresh(processo)
        return processo, "Processo cancelado."
    except Exception:
        db.rollback()
        raise
