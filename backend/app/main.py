from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routers import (
    arquivos,
    admin,
    auth,
    certificados,
    cnpj,
    consultas,
    danfse,
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
from backend.app.core.observability import configure_logging
from backend.app.db.models import Empresa, MonitoramentoConfig
from backend.app.db.session import SessionLocal, init_db
from backend.app.repositories import jobs_repo
from backend.app.services import consultas_service, operacao_service
from backend.app.services.legacy_processing_service import limpar_pfx_temporarios
from backend.app.services.notas_download_service import limpar_zips_temporarios
from backend.app.services.valor_liquido_backfill_service import recalcular_notas_salvas
from backend.app.worker.worker import processar_proximo_job


configure_logging()

# Intervalo da varredura por grupos novos sem worker dedicado.
SUPERVISOR_GRUPOS_INTERVALO = 60
# Limpeza de logs antigos: uma vez por dia (o primeiro ciclo ja limpa).
LIMPEZA_LOGS_INTERVALO = 24 * 3600
_rotina_estado: dict[str, float] = {"ultima_limpeza_logs": float("-inf")}


def _rotina_operacao() -> dict:
    """Vigia da fila (aviso por e-mail/webhook) e retencao de logs."""
    resultado: dict = {}
    with SessionLocal() as db:
        resultado["avisos"] = operacao_service.verificar_e_avisar(db)
        if time.monotonic() - _rotina_estado["ultima_limpeza_logs"] >= LIMPEZA_LOGS_INTERVALO:
            _rotina_estado["ultima_limpeza_logs"] = time.monotonic()
            resultado["logs_removidos"] = operacao_service.limpar_logs_antigos(db)
    return resultado


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


def _recuperar_jobs_travados() -> int:
    with SessionLocal() as db:
        return jobs_repo.recuperar_jobs_travados(db, settings.jobs_travados_minutos)


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


async def _supervisionar_grupos(
    worker_tasks: list[asyncio.Task],
    grupos_cobertos: set[str],
    workers_per_group: int,
) -> None:
    """Sobe workers para grupos criados depois da inicializacao da API.

    Os grupos sao lidos uma unica vez no startup. Sem esta supervisao, uma
    empresa cadastrada em um grupo novo nunca tem quem consuma sua fila: os
    jobs ficam pendentes ate alguem reiniciar a API.
    """
    while True:
        await asyncio.sleep(SUPERVISOR_GRUPOS_INTERVALO)
        try:
            recuperados = await asyncio.to_thread(_recuperar_jobs_travados)
            if recuperados:
                print(f"Supervisor: {recuperados} job(s) sem heartbeat voltaram para a fila")
            rotina = await asyncio.to_thread(_rotina_operacao)
            if rotina.get("avisos") or rotina.get("logs_removidos"):
                print(f"Supervisor: rotina de operacao {rotina}")
            novos = [g for g in await asyncio.to_thread(_worker_groups) if g not in grupos_cobertos]
        except Exception as exc:
            print(f"Supervisor de grupos falhou e continuara ativo: {exc}")
            continue
        for grupo in novos:
            grupos_cobertos.add(grupo)
            for slot, (_g, worker_id) in enumerate(
                _build_api_workers([grupo], workers_per_group), start=1
            ):
                print(f"Supervisor de grupos: iniciando worker para o grupo novo {grupo}")
                worker_tasks.append(asyncio.create_task(_run_api_worker(slot, worker_id, grupo)))


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
    pfx_removidos = limpar_pfx_temporarios()
    if pfx_removidos:
        print(f"Limpeza de certificados temporarios: {pfx_removidos} PFX removido(s)")
    if zips_removidos:
        print(f"Limpeza de downloads temporarios: {zips_removidos} ZIP(s) removido(s)")
    worker_tasks: list[asyncio.Task] = []
    scheduler_task: asyncio.Task | None = None
    liquid_recalculation_task = asyncio.create_task(_recalcular_valores_liquidos_salvos())
    if settings.api_worker_enabled:
        workers_per_group = max(1, int(settings.api_worker_concurrency))
        api_workers = _build_api_workers(_worker_groups(), workers_per_group)
        recovered = _recuperar_jobs_travados()
        if recovered:
            print(f"API worker recuperou jobs presos de execucoes antigas: {recovered}")
        worker_tasks = [
            asyncio.create_task(_run_api_worker(slot, worker_id, grupo))
            for slot, (grupo, worker_id) in enumerate(api_workers, start=1)
        ]
        supervisor_task = asyncio.create_task(
            _supervisionar_grupos(worker_tasks, {grupo for grupo, _id in api_workers}, workers_per_group)
        )
        worker_tasks.append(supervisor_task)
        if settings.embedded_scheduler_enabled:
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
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Admin-Token"],
    # Sem isso o navegador (frontend em outro dominio) nao le o nome do arquivo
    # nos downloads de XML/PDF/ZIP/XLSX e salva com um nome padrao. X-Next-Cursor
    # e o ponteiro da proxima pagina de /notas.
    expose_headers=["Content-Disposition", "X-Next-Cursor"],
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
app.include_router(cnpj.router)
app.include_router(consultas.router)
app.include_router(execucoes.router)
app.include_router(processos.router)
app.include_router(logs.router)
app.include_router(nfse_compat.router)
app.include_router(notas.router)
app.include_router(eventos.router)
app.include_router(relatorios.router)
app.include_router(arquivos.router)
app.include_router(danfse.router)
