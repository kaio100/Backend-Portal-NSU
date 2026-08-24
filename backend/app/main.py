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
    admin,
    auth,
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
from backend.app.db.models import Empresa, Job, LockProcessamento, MonitoramentoConfig, Processo
from backend.app.db.session import SessionLocal, init_db
from backend.app.services import consultas_service
from backend.app.services.notas_download_service import limpar_zips_temporarios
from backend.app.services.valor_liquido_backfill_service import recalcular_notas_salvas
from backend.app.scripts.revalidar_status_pdfs import executar as revalidar_status_pdfs
from backend.app.worker.worker import processar_proximo_job


def _worker_groups() -> list[str]:
    with SessionLocal() as db:
        grupos = {str(grupo) for (grupo,) in db.query(Empresa.grupo).distinct().all() if grupo}
        grupos.update(str(grupo) for (grupo,) in db.query(MonitoramentoConfig.grupo).distinct().all() if grupo)
    return sorted(grupos or {"planning_hub"})


def _build_api_workers(groups: list[str], workers_per_group: int) -> list[tuple[str, str]]:
    hostname = socket.gethostname()
    return [
        (grupo, f"api-{grupo}-{slot}-{hostname}-{uuid.uuid4().hex[:8]}")
        for grupo in groups
        for slot in range(1, workers_per_group + 1)
    ]


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


async def _run_api_worker(slot: int, worker_id: str, grupo: str) -> None:
    print(f"API worker iniciado: {worker_id} | grupo={grupo} | dry_run={settings.worker_dry_run}")
    idle_sleep = max(0.1, float(settings.api_worker_sleep))
    idle_sleep_max = max(idle_sleep, 2.0)

    while True:
        try:
            result = await asyncio.to_thread(processar_proximo_job, worker_id, grupo)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"API worker {slot} ({grupo}) falhou e continuara ativo: {exc}")
            await asyncio.sleep(max(1.0, float(settings.api_worker_sleep)))
            continue
        if result.get("motivo") == "sem_job":
            await asyncio.sleep(idle_sleep)
            idle_sleep = min(idle_sleep * 1.5, idle_sleep_max)
        else:
            idle_sleep = max(0.1, float(settings.api_worker_sleep))
            print(f"API worker {slot} ({grupo}): {result}")


async def _run_consultas_scheduler() -> None:
    print("Agendador de consultas automaticas iniciado")

    while True:
        if consultas_service.is_enabled():
            result = await asyncio.to_thread(_enqueue_consultas_automaticas)
            if result["certificados_enfileirados"]:
                print(f"Agendador de consultas: {result}")
        # O agendador trabalha em minutos; consultar o banco varias vezes por
        # segundo quando o sistema esta ocioso so consome CPU local.
        await asyncio.sleep(max(5.0, float(settings.consultas_scheduler_sleep)))


def _enqueue_consultas_automaticas() -> dict:
    with SessionLocal() as db:
        resultados = [
            consultas_service.enqueue_consultas_pendentes(db, grupo=grupo)
            for grupo in consultas_service.listar_grupos_automaticos_ativos(db)
        ]
        return {
            "certificados_enfileirados": sum(int(item.get("certificados_enfileirados", 0)) for item in resultados),
            "certificados_ignorados": sum(int(item.get("certificados_ignorados", 0)) for item in resultados),
            "grupos_processados": len(resultados),
        }


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


async def _recalcular_valores_liquidos_salvos() -> None:
    try:
        relatorio = await asyncio.to_thread(recalcular_notas_salvas)
        print(f"Recalculo de valores liquidos finalizado: {relatorio}")
    except Exception as exc:
        print(f"Recalculo de valores liquidos falhou: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    zips_removidos = limpar_zips_temporarios()
    if zips_removidos:
        print(f"Limpeza de downloads temporarios: {zips_removidos} ZIP(s) removido(s)")
    worker_tasks: list[asyncio.Task] = []
    scheduler_task: asyncio.Task | None = None
    pdf_revalidation_task: asyncio.Task | None = None
    liquid_recalculation_task = asyncio.create_task(_recalcular_valores_liquidos_salvos())
    if settings.api_worker_enabled and settings.pdf_status_revalidation_enabled:
        pdf_revalidation_task = asyncio.create_task(_revalidar_status_pdfs_salvos())
    if settings.api_worker_enabled:
        workers_per_group = max(1, int(settings.api_worker_concurrency))
        api_workers = _build_api_workers(_worker_groups(), workers_per_group)
        worker_ids = [worker_id for _grupo, worker_id in api_workers]
        recovered = _recover_stale_api_jobs(worker_ids)
        if recovered:
            print(f"API worker recuperou jobs presos de execucoes antigas: {recovered}")
        worker_tasks = [
            asyncio.create_task(_run_api_worker(slot, worker_id, grupo))
            for slot, (grupo, worker_id) in enumerate(api_workers, start=1)
        ]
        scheduler_task = asyncio.create_task(_run_consultas_scheduler())

    try:
        yield
    finally:
        if not liquid_recalculation_task.done():
            liquid_recalculation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await liquid_recalculation_task
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


def _documentation_options(production: bool) -> dict[str, str | None]:
    if production:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}


app = FastAPI(
    title="NFS-e Backend API",
    version="0.1.0",
    lifespan=lifespan,
    **_documentation_options(settings.is_production),
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return response


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

    default_origins = ["https://frontend-portal-nsu.vercel.app"]
    if not settings.is_production:
        default_origins.extend(["http://localhost:5173", "http://127.0.0.1:5173"])

    for origin in default_origins:
        if origin not in origins:
            origins.append(origin)

    return origins


cors_origins = _parse_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

# /health e /db/health ficam sem API key: sao usados por health checks de
# infraestrutura (Docker, load balancer) que nao enviam headers customizados.
app.include_router(health.router)
app.include_router(db_health.router)
# /auth tem sua propria protecao por endpoint: login/criar-conta publicos,
# /me exige JWT e a criacao interna de usuario exige API key.
app.include_router(auth.router)
app.include_router(admin.router)

# Os endpoints do portal fazem a autorizacao por JWT dentro de cada router.
# API_KEY fica reservada a operacoes internas servidor-servidor, nunca ao browser.
app.include_router(storage.router)
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
