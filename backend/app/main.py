from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routers import (
    arquivos,
    certificados,
    consultas,
    db_health,
    empresas,
    eventos,
    execucoes,
    health,
    logs,
    nfse_compat,
    notas,
    nsu,
    processos,
    relatorios,
    storage,
)
from backend.app.core.config import settings
from backend.app.db.models import Job, LockProcessamento, Processo
from backend.app.db.session import SessionLocal, init_db
from backend.app.services import consultas_service
from backend.app.services.notas_download_service import limpar_zips_temporarios
from backend.app.scripts.revalidar_status_pdfs import executar as revalidar_status_pdfs
from backend.app.worker.worker import processar_proximo_job


def _build_api_worker_ids(worker_count: int) -> list[str]:
    hostname = socket.gethostname()
    return [f"api-{slot}-{hostname}-{uuid.uuid4().hex[:8]}" for slot in range(1, worker_count + 1)]


def _recover_stale_api_jobs(active_worker_ids: list[str]) -> int:
    with SessionLocal() as db:
        stale_jobs = (
            db.query(Job)
            .filter(Job.status == "rodando")
            .filter(Job.locked_by.like("api-%"))
            .filter(Job.locked_by.notin_(active_worker_ids))
            .all()
        )
        if not stale_jobs:
            return 0

        stale_worker_ids = {str(job.locked_by) for job in stale_jobs if job.locked_by}
        for job in stale_jobs:
            job.status = "pendente"
            job.locked_by = None
            job.locked_at = None
            db.add(job)
            processo = db.get(Processo, int(job.processo_id))
            if processo is not None and processo.status == "rodando":
                processo.status = "pendente"
                processo.started_at = None
                db.add(processo)

        if stale_worker_ids:
            (
                db.query(LockProcessamento)
                .filter(LockProcessamento.locked_by.in_(stale_worker_ids))
                .delete(synchronize_session=False)
            )
        db.commit()
        return len(stale_jobs)


async def _run_api_worker(slot: int, worker_id: str) -> None:
    print(f"API worker iniciado: {worker_id} | dry_run={settings.worker_dry_run}")

    while True:
        result = await asyncio.to_thread(processar_proximo_job, worker_id)
        if result.get("motivo") == "sem_job":
            await asyncio.sleep(settings.api_worker_sleep)
        else:
            print(f"API worker {slot}: {result}")


async def _run_consultas_scheduler() -> None:
    print("Agendador de consultas automaticas iniciado")

    while True:
        if consultas_service.is_enabled():
            result = await asyncio.to_thread(_enqueue_consultas_automaticas)
            if result["certificados_enfileirados"]:
                print(f"Agendador de consultas: {result}")
        await asyncio.sleep(settings.consultas_scheduler_sleep)


def _enqueue_consultas_automaticas() -> dict:
    with SessionLocal() as db:
        return consultas_service.enqueue_consultas_pendentes(db)


async def _revalidar_status_pdfs_salvos() -> None:
    try:
        relatorio = await asyncio.to_thread(
            revalidar_status_pdfs,
            None,
            False,
            max(1, int(settings.pdf_status_revalidation_batch_size)),
        )
        print(f"Revalidacao de status por PDF oficial finalizada: {relatorio}")
    except Exception as exc:
        # A API continua disponivel mesmo se um storage externo estiver
        # temporariamente indisponivel; a proxima inicializacao tenta de novo.
        print(f"Revalidacao de status por PDF oficial falhou: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    zips_removidos = limpar_zips_temporarios()
    if zips_removidos:
        print(f"Limpeza de downloads temporarios: {zips_removidos} ZIP(s) removido(s)")
    worker_tasks: list[asyncio.Task] = []
    scheduler_task: asyncio.Task | None = None
    pdf_revalidation_task: asyncio.Task | None = None
    if settings.api_worker_enabled and settings.pdf_status_revalidation_enabled:
        pdf_revalidation_task = asyncio.create_task(_revalidar_status_pdfs_salvos())
    if settings.api_worker_enabled:
        worker_count = max(1, int(settings.api_worker_concurrency))
        worker_ids = _build_api_worker_ids(worker_count)
        recovered = _recover_stale_api_jobs(worker_ids)
        if recovered:
            print(f"API worker recuperou jobs presos de execucoes antigas: {recovered}")
        worker_tasks = [
            asyncio.create_task(_run_api_worker(slot, worker_id))
            for slot, worker_id in enumerate(worker_ids, start=1)
        ]
        scheduler_task = asyncio.create_task(_run_consultas_scheduler())

    try:
        yield
    finally:
        if scheduler_task is not None:
            scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await scheduler_task
        for worker_task in worker_tasks:
            worker_task.cancel()
        for worker_task in worker_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
        if pdf_revalidation_task is not None and not pdf_revalidation_task.done():
            pdf_revalidation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pdf_revalidation_task


app = FastAPI(
    title="NFS-e Backend API",
    version="0.1.0",
    lifespan=lifespan,
)


def _parse_cors_origins() -> list[str]:
    raw = (
        os.getenv("CORS_ORIGINS")
        or os.getenv("BACKEND_CORS_ORIGINS")
        or os.getenv("FRONTEND_URL")
        or settings.cors_origins
        or ""
    )

    origins = []
    for item in raw.split(","):
        origin = item.strip().rstrip("/")
        if origin and origin not in origins:
            origins.append(origin)

    default_origins = [
        "https://frontend-portal-nsu.vercel.app",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    for origin in default_origins:
        if origin not in origins:
            origins.append(origin)

    return origins


cors_origins = _parse_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(storage.router)
app.include_router(db_health.router)
app.include_router(empresas.router)
app.include_router(nsu.router)
app.include_router(certificados.router)
app.include_router(certificados.empresa_router)
app.include_router(consultas.router)
app.include_router(execucoes.router)
app.include_router(processos.router)
app.include_router(logs.router)
app.include_router(nfse_compat.router)
app.include_router(notas.router)
app.include_router(eventos.router)
app.include_router(relatorios.router)
app.include_router(arquivos.router)
