from __future__ import annotations

import time
import traceback

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Job
from backend.app.repositories import jobs_repo, processos_repo
from backend.app.services import legacy_processing_service, locks_service, logs_service
from backend.app.services.storage_service import get_storage_service


def _job_processavel(job: Job, worker_id: str) -> bool:
    return job.status == "pendente" or (job.status == "rodando" and job.locked_by == worker_id)


def _foi_cancelado(db: Session, processo, job: Job) -> bool:
    db.refresh(processo)
    db.refresh(job)
    return processo.status == "cancelado" or job.status == "cancelado"


def _devolver_job_para_fila(db: Session, job: Job) -> None:
    jobs_repo.mark_job_pending(db, job)


def _registrar_job_reservado(db: Session, processo, job: Job, worker_id: str) -> None:
    logs_service.registrar_log(
        db,
        processo.id,
        processo.empresa_id,
        "info",
        "Job reservado pelo worker",
        {
            "job_id": job.id,
            "worker_id": worker_id,
            "empresa_id": job.empresa_id,
            "certificado_id": job.certificado_id,
            "tipo": job.tipo,
        },
    )


def processar_job_simulado(db: Session, job: Job, worker_id: str) -> dict:
    processo = processos_repo.get_processo(db, int(job.processo_id))
    if processo is None:
        jobs_repo.mark_job_erro(db, job, "Processo nao encontrado.")
        db.commit()
        return {"ok": False, "job_id": job.id, "motivo": "processo_nao_encontrado"}

    if not _job_processavel(job, worker_id) or processo.status == "cancelado":
        return {"ok": False, "job_id": job.id, "motivo": "job_nao_processavel"}

    lock_acquired = False
    try:
        _registrar_job_reservado(db, processo, job, worker_id)
        logs_service.registrar_log(
            db,
            processo.id,
            processo.empresa_id,
            "info",
            "Worker iniciou processamento do job",
            {"job_id": job.id, "worker_id": worker_id, "dry_run": settings.worker_dry_run},
        )
        lock_acquired = locks_service.adquirir_lock(
            db,
            empresa_id=int(job.empresa_id),
            certificado_id=int(job.certificado_id),
            locked_by=worker_id,
        )
        if not lock_acquired:
            _devolver_job_para_fila(db, job)
            db.commit()
            return {"ok": False, "job_id": job.id, "motivo": "lock_indisponivel"}

        logs_service.registrar_log(db, processo.id, processo.empresa_id, "info", "Lock adquirido")
        jobs_repo.mark_job_running(db, job, worker_id)
        processos_repo.mark_processo_running(db, processo)
        logs_service.registrar_log(db, processo.id, processo.empresa_id, "info", "Processo marcado como rodando")
        db.commit()

        logs_service.registrar_log(db, processo.id, processo.empresa_id, "info", "Execucao simulada iniciada")
        db.commit()
        time.sleep(max(0, float(settings.worker_dry_run_sleep)))

        if _foi_cancelado(db, processo, job):
            jobs_repo.mark_job_cancelado(db, job, "Processo cancelado durante a execucao.")
            processos_repo.cancelar_processo(db, processo)
            logs_service.registrar_log(db, processo.id, processo.empresa_id, "info", "Processo cancelado durante execucao simulada")
            db.commit()
            return {"ok": False, "job_id": job.id, "motivo": "cancelado"}

        logs_service.registrar_log(db, processo.id, processo.empresa_id, "info", "Execucao simulada finalizada")
        jobs_repo.mark_job_finalizado(db, job)
        processos_repo.mark_processo_finalizado(db, processo)
        logs_service.registrar_log(db, processo.id, processo.empresa_id, "info", "Processo finalizado")
        db.commit()
        return {
            "ok": True,
            "job_id": job.id,
            "processo_id": job.processo_id,
            "dry_run": settings.worker_dry_run,
        }
    except Exception as exc:
        db.rollback()
        if _foi_cancelado(db, processo, job):
            jobs_repo.mark_job_cancelado(db, job, "Processo cancelado durante a execucao.")
            processos_repo.cancelar_processo(db, processo)
            db.commit()
            return {"ok": False, "job_id": job.id, "motivo": "cancelado"}
        erro_detalhado = traceback.format_exc()
        jobs_repo.mark_job_erro(db, job, str(exc))
        processos_repo.mark_processo_erro(db, processo, str(exc))
        logs_service.registrar_log(
            db,
            processo.id,
            processo.empresa_id,
            "error",
            "Erro detalhado no processamento simulado",
            {"job_id": job.id, "erro": str(exc), "traceback": erro_detalhado},
        )
        db.commit()
        return {"ok": False, "job_id": job.id, "motivo": "erro", "erro": str(exc)}
    finally:
        if lock_acquired:
            try:
                locks_service.liberar_lock(
                    db,
                    empresa_id=int(job.empresa_id),
                    certificado_id=int(job.certificado_id),
                    locked_by=worker_id,
                )
                logs_service.registrar_log(db, processo.id, processo.empresa_id, "info", "Lock liberado")
                db.commit()
            except Exception:
                db.rollback()


def processar_job_consulta_nfse_real(db: Session, job: Job, worker_id: str) -> dict:
    processo = processos_repo.get_processo(db, int(job.processo_id))
    if processo is None:
        jobs_repo.mark_job_erro(db, job, "Processo nao encontrado.")
        db.commit()
        return {"ok": False, "job_id": job.id, "motivo": "processo_nao_encontrado"}

    if not _job_processavel(job, worker_id) or processo.status == "cancelado":
        return {"ok": False, "job_id": job.id, "motivo": "job_nao_processavel"}

    lock_acquired = False
    try:
        _registrar_job_reservado(db, processo, job, worker_id)
        logs_service.registrar_log(
            db,
            processo.id,
            processo.empresa_id,
            "info",
            "Worker iniciou processamento do job",
            {"job_id": job.id, "worker_id": worker_id, "dry_run": settings.worker_dry_run},
        )
        lock_acquired = locks_service.adquirir_lock(
            db,
            empresa_id=int(job.empresa_id),
            certificado_id=int(job.certificado_id),
            locked_by=worker_id,
        )
        if not lock_acquired:
            _devolver_job_para_fila(db, job)
            db.commit()
            return {"ok": False, "job_id": job.id, "motivo": "lock_indisponivel"}

        logs_service.registrar_log(db, processo.id, processo.empresa_id, "info", "Lock adquirido")
        jobs_repo.mark_job_running(db, job, worker_id)
        processos_repo.mark_processo_running(db, processo)
        logs_service.registrar_log(db, processo.id, processo.empresa_id, "info", "Processo marcado como rodando")
        db.commit()

        result = legacy_processing_service.executar_consulta_nfse_legado(
            db=db,
            storage=get_storage_service(),
            processo=processo,
            job=job,
            worker_id=worker_id,
        )
        if _foi_cancelado(db, processo, job):
            jobs_repo.mark_job_cancelado(db, job, "Processo cancelado durante a execucao.")
            processos_repo.cancelar_processo(db, processo)
            logs_service.registrar_log(db, processo.id, processo.empresa_id, "info", "Processo cancelado durante execucao real")
            db.commit()
            return {"ok": False, "job_id": job.id, "processo_id": processo.id, "motivo": "cancelado"}
        jobs_repo.mark_job_finalizado(db, job)
        processos_repo.mark_processo_finalizado(db, processo)
        logs_service.registrar_log(db, processo.id, processo.empresa_id, "info", "Processo finalizado")
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        if _foi_cancelado(db, processo, job):
            jobs_repo.mark_job_cancelado(db, job, "Processo cancelado durante a execucao.")
            processos_repo.cancelar_processo(db, processo)
            db.commit()
            return {"ok": False, "job_id": job.id, "processo_id": processo.id, "motivo": "cancelado"}
        erro = str(exc)
        erro_detalhado = traceback.format_exc()
        jobs_repo.mark_job_erro(db, job, erro)
        processos_repo.mark_processo_erro(db, processo, erro)
        logs_service.registrar_log(
            db,
            processo.id,
            processo.empresa_id,
            "error",
            "Erro no processamento real via motor legado",
            {"job_id": job.id, "erro": erro, "traceback": erro_detalhado},
        )
        db.commit()
        return {"ok": False, "job_id": job.id, "motivo": "erro", "erro": erro}
    finally:
        if lock_acquired:
            try:
                locks_service.liberar_lock(
                    db,
                    empresa_id=int(job.empresa_id),
                    certificado_id=int(job.certificado_id),
                    locked_by=worker_id,
                )
                logs_service.registrar_log(db, processo.id, processo.empresa_id, "info", "Lock liberado")
                db.commit()
            except Exception:
                db.rollback()


def processar_job(db: Session, job: Job, worker_id: str) -> dict:
    if settings.worker_dry_run:
        return processar_job_simulado(db, job, worker_id)

    if job.tipo == "consulta_nfse":
        return processar_job_consulta_nfse_real(db, job, worker_id)

    processo = processos_repo.get_processo(db, int(job.processo_id))
    erro = f"Tipo de job nao suportado: {job.tipo}"
    jobs_repo.mark_job_erro(db, job, erro)
    if processo is not None:
        processos_repo.mark_processo_erro(db, processo, erro)
        logs_service.registrar_log(db, processo.id, processo.empresa_id, "error", erro)
    db.commit()
    return {"ok": False, "job_id": job.id, "motivo": "tipo_nao_suportado"}
