from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Certificado, Empresa, MonitoramentoConfig, Processo
from backend.app.db.session import SessionLocal
from backend.app.repositories import jobs_repo, processos_repo
from backend.app.schemas.consultas import ConsultaIniciarRequest
from backend.app.services import secrets_service


PENDENTE_STATUSES = ("pendente", "queued", "queue", "aguardando", "em_fila")
RODANDO_STATUSES = ("rodando", "running", "processando", "em_execucao", "executando")
FINALIZADO_STATUSES = ("finalizado", "finalizada", "concluido", "concluida", "done", "success", "sucesso")
ERRO_STATUSES = ("erro", "falha", "failed", "error")
CANCELADO_STATUSES = ("cancelado", "cancelada", "cancelled", "canceled")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _effective_limite(limite: int) -> int:
    maximo = int(settings.worker_real_max_limite or limite)
    return min(int(limite), maximo)


def _effective_pausa(pausa: float) -> float:
    pausa = max(0.0, float(pausa))
    maximo = float(settings.worker_real_max_pausa)
    if maximo <= 0:
        return pausa
    return min(pausa, maximo)


def _status_filter(query, statuses: tuple[str, ...]):
    return query.filter(func.lower(Processo.status).in_(statuses))


def get_monitoramento_config(db: Session, grupo: str = "planning_hub") -> MonitoramentoConfig:
    config = db.query(MonitoramentoConfig).filter(MonitoramentoConfig.grupo == grupo).first()
    if config is not None:
        return config

    config = MonitoramentoConfig(
        automatico_ativo=False,
        intervalo_minutos=15,
        filtros_json=None,
        grupo=grupo,
    )
    db.add(config)
    db.flush()
    db.refresh(config)
    return config


def is_enabled(db: Session | None = None, grupo: str | None = None) -> bool:
    if db is not None:
        if grupo is None:
            return db.query(MonitoramentoConfig).filter(MonitoramentoConfig.automatico_ativo.is_(True)).first() is not None
        return bool(get_monitoramento_config(db, grupo).automatico_ativo)
    with SessionLocal() as session:
        return is_enabled(session, grupo=grupo)


def listar_grupos_automaticos_ativos(db: Session) -> list[str]:
    rows = db.query(MonitoramentoConfig.grupo).filter(MonitoramentoConfig.automatico_ativo.is_(True)).all()
    return [str(grupo) for (grupo,) in rows if grupo]


def _count_processos(db: Session, statuses: tuple[str, ...], grupo: str) -> int:
    query = db.query(func.count(Processo.id)).join(Empresa, Empresa.id == Processo.empresa_id).filter(Processo.tipo == "consulta_nfse", Empresa.grupo == grupo)
    return int(_status_filter(query, statuses).scalar() or 0)


def _list_processos(db: Session, statuses: tuple[str, ...], limit: int, grupo: str) -> list[Processo]:
    query = db.query(Processo).join(Empresa, Empresa.id == Processo.empresa_id).filter(Processo.tipo == "consulta_nfse", Empresa.grupo == grupo)
    return list(_status_filter(query, statuses).order_by(Processo.id.desc()).limit(limit).all())


def montar_status(db: Session, limit: int = 10, grupo: str = "planning_hub") -> dict[str, Any]:
    config = get_monitoramento_config(db, grupo)
    processos_rodando = _list_processos(db, RODANDO_STATUSES, limit, grupo)
    processos_pendentes = _list_processos(db, PENDENTE_STATUSES, limit, grupo)
    consultando = bool(processos_rodando)
    automatico_ativo = bool(config.automatico_ativo)

    if automatico_ativo:
        mensagem = "Motor ADN ativo"
    elif consultando:
        mensagem = "Consultas em andamento"
    else:
        mensagem = "Motor ADN inativo"

    return {
        "consultando": consultando,
        "automatico_ativo": automatico_ativo,
        "mensagem": mensagem,
        "worker": {
            "enabled": settings.api_worker_enabled,
            "dry_run": settings.worker_dry_run,
            "sleep": settings.api_worker_sleep,
        },
        "totais": {
            "pendentes": _count_processos(db, PENDENTE_STATUSES, grupo),
            "rodando": _count_processos(db, RODANDO_STATUSES, grupo),
            "finalizados": _count_processos(db, FINALIZADO_STATUSES, grupo),
            "erros": _count_processos(db, ERRO_STATUSES, grupo),
            "cancelados": _count_processos(db, CANCELADO_STATUSES, grupo),
        },
        "processos_rodando": processos_rodando,
        "processos_pendentes": processos_pendentes,
    }


def has_active_consulta_for_certificado(db: Session, certificado_id: int) -> bool:
    query = (
        db.query(Processo.id)
        .filter(Processo.tipo == "consulta_nfse")
        .filter(Processo.certificado_id == certificado_id)
    )
    return _status_filter(query, PENDENTE_STATUSES + RODANDO_STATUSES).first() is not None


def _active_consulta_certificado_ids(db: Session, certificado_ids: list[int]) -> set[int]:
    if not certificado_ids:
        return set()
    query = (
        db.query(Processo.certificado_id)
        .filter(Processo.tipo == "consulta_nfse")
        .filter(Processo.certificado_id.in_(certificado_ids))
        .filter(Processo.certificado_id.isnot(None))
    )
    rows = _status_filter(query, PENDENTE_STATUSES + RODANDO_STATUSES).distinct().all()
    return {int(certificado_id) for (certificado_id,) in rows if certificado_id is not None}


def list_certificados_elegiveis(
    db: Session,
    options: ConsultaIniciarRequest | None = None,
    grupo: str = "planning_hub",
) -> list[Certificado]:
    options = options or ConsultaIniciarRequest()
    query = (
        db.query(Certificado)
        .join(Empresa, Empresa.id == Certificado.empresa_id)
        .filter(Empresa.ativo.is_(True))
        .filter(Certificado.ativo.is_(True))
        .filter(Certificado.storage_key.isnot(None))
        .filter(Certificado.storage_key != "")
        .filter(Certificado.storage_key != "pending")
        .filter(Certificado.senha_secret_ref.isnot(None))
        .filter(Empresa.grupo == grupo)
    )
    if options.empresa_ids:
        query = query.filter(Certificado.empresa_id.in_(options.empresa_ids))
    if options.certificado_ids:
        query = query.filter(Certificado.id.in_(options.certificado_ids))

    certificados = list(query.order_by(Certificado.id.asc()).all())
    elegiveis = []
    for certificado in certificados:
        try:
            secrets_service.get_secret_value(db, str(certificado.senha_secret_ref))
        except secrets_service.SecretsServiceError:
            continue
        elegiveis.append(certificado)
    return elegiveis


def _create_consulta_job(db: Session, certificado: Certificado, options: ConsultaIniciarRequest) -> Processo:
    limite = _effective_limite(options.limite)
    pausa = _effective_pausa(options.pausa)
    processo = processos_repo.create_processo(
        db,
        {
            "empresa_id": certificado.empresa_id,
            "certificado_id": certificado.id,
            "tipo": "consulta_nfse",
            "status": "pendente",
            "nsu_inicio": options.nsu_inicio,
            "limite": limite,
            "pausa": pausa,
            "gerar_pdf_espelho": options.gerar_pdf_espelho,
            "baixar_pdf_oficial": options.baixar_pdf_oficial,
        },
    )
    jobs_repo.create_job(
        db,
        {
            "processo_id": processo.id,
            "empresa_id": certificado.empresa_id,
            "certificado_id": certificado.id,
            "tipo": "consulta_nfse",
            "status": "pendente",
            "attempts": 0,
            "available_at": _now(),
            "payload_json": {
                "empresa_id": certificado.empresa_id,
                "certificado_id": certificado.id,
                "tipo": "consulta_nfse",
                "nsu_inicio": options.nsu_inicio,
                "limite": limite,
                "pausa": pausa,
                "gerar_pdf_espelho": options.gerar_pdf_espelho,
                "baixar_pdf_oficial": options.baixar_pdf_oficial,
            },
        },
    )
    return processo


def enqueue_consultas_pendentes(
    db: Session,
    options: ConsultaIniciarRequest | None = None,
    respeitar_ciclo: bool = True,
    grupo: str = "planning_hub",
) -> dict[str, Any]:
    config = get_monitoramento_config(db, grupo)
    options = options or ConsultaIniciarRequest(**(config.filtros_json or {}))
    agora = _now()

    proximo_ciclo_em = _as_aware(config.proximo_ciclo_em)
    if respeitar_ciclo and proximo_ciclo_em and proximo_ciclo_em > agora:
        return {"processos_criados": [], "certificados_enfileirados": 0, "certificados_ignorados": 0}

    processos_criados = []
    certificados_ignorados = 0
    certificados = list_certificados_elegiveis(db, options=options, grupo=grupo)
    certificados_ativos = (
        set()
        if options.forcar
        else _active_consulta_certificado_ids(db, [int(certificado.id) for certificado in certificados])
    )

    for certificado in certificados:
        if len(processos_criados) >= _effective_limite(options.limite):
            break
        if not options.forcar and int(certificado.id) in certificados_ativos:
            certificados_ignorados += 1
            continue
        processos_criados.append(_create_consulta_job(db, certificado, options))

    config.ultimo_ciclo_em = agora
    config.proximo_ciclo_em = agora + timedelta(minutes=int(config.intervalo_minutos))
    db.add(config)
    db.commit()
    for processo in processos_criados:
        db.refresh(processo)

    return {
        "processos_criados": processos_criados,
        "certificados_enfileirados": len(processos_criados),
        "certificados_ignorados": certificados_ignorados,
    }


def iniciar_consultas_automaticas(
    db: Session,
    options: ConsultaIniciarRequest | None = None,
    grupo: str = "planning_hub",
) -> dict[str, Any]:
    options = options or ConsultaIniciarRequest()
    # Um NSU informado manualmente representa um novo ponto de partida. Nao
    # pode concorrer com jobs antigos, pois o worker poderia reservar primeiro
    # uma consulta criada com o estado anterior.
    if options.nsu_inicio is not None:
        desativar_consultas_automaticas(db, grupo=grupo)

    config = get_monitoramento_config(db, grupo)
    config.automatico_ativo = bool(options.automatico)
    config.intervalo_minutos = int(options.intervalo_minutos)
    config.filtros_json = options.model_dump()
    config.proximo_ciclo_em = None
    db.add(config)
    db.flush()

    resultado = enqueue_consultas_pendentes(db, options=options, respeitar_ciclo=False, grupo=grupo)

    # O NSU inicial e o modo forcar valem apenas para esta partida. Ciclos
    # automaticos posteriores devem continuar do NSU central ja alcancado e
    # nao recriar a mesma faixa indefinidamente.
    filtros_ciclos = options.model_copy(update={"nsu_inicio": None, "forcar": False})
    config.filtros_json = filtros_ciclos.model_dump()
    db.add(config)
    db.commit()
    return resultado


def iniciar_certificado_sem_substituir_monitor(
    db: Session,
    options: ConsultaIniciarRequest,
    grupo: str = "planning_hub",
) -> dict[str, Any]:
    """Enfileira um certificado novo sem retirar os anteriores do monitor."""
    config = get_monitoramento_config(db, grupo)
    if not config.automatico_ativo:
        return iniciar_consultas_automaticas(db, options=options, grupo=grupo)

    filtros_atuais_raw = config.filtros_json
    filtros_atuais = ConsultaIniciarRequest(**(filtros_atuais_raw or {}))

    # O NSU e o modo forcar do autocadastro valem somente para o job imediato.
    resultado = enqueue_consultas_pendentes(
        db,
        options=options,
        respeitar_ciclo=False,
        grupo=grupo,
    )

    # Ausencia de filtros representa monitoramento global e deve continuar
    # global. Em um monitor restrito, o novo certificado e sua empresa sao
    # acrescentados ao conjunto existente em vez de substitui-lo.
    if filtros_atuais_raw is None or (
        filtros_atuais.empresa_ids is None and filtros_atuais.certificado_ids is None
    ):
        filtros_ciclos = filtros_atuais.model_copy(update={"nsu_inicio": None, "forcar": False})
    else:
        empresa_ids = sorted(set(filtros_atuais.empresa_ids or []) | set(options.empresa_ids or [])) or None
        certificado_ids = sorted(
            set(filtros_atuais.certificado_ids or []) | set(options.certificado_ids or [])
        ) or None
        filtros_ciclos = filtros_atuais.model_copy(
            update={
                "empresa_ids": empresa_ids,
                "certificado_ids": certificado_ids,
                "nsu_inicio": None,
                "forcar": False,
            }
        )

    config.filtros_json = filtros_ciclos.model_dump()
    db.add(config)
    db.commit()
    return resultado


def desativar_consultas_automaticas(
    db: Session,
    cancelar_pendentes: bool = True,
    cancelar_rodando: bool = True,
    grupo: str = "planning_hub",
) -> dict[str, Any]:
    config = get_monitoramento_config(db, grupo)
    config.automatico_ativo = False
    config.proximo_ciclo_em = None
    db.add(config)

    cancelados = 0
    if cancelar_pendentes:
        processos = _status_filter(
            db.query(Processo).join(Empresa, Empresa.id == Processo.empresa_id).filter(Processo.tipo == "consulta_nfse", Empresa.grupo == grupo),
            PENDENTE_STATUSES,
        ).all()
        for processo in processos:
            processos_repo.cancelar_processo(db, processo)
            for job in jobs_repo.list_jobs(db, processo_id=processo.id, status="pendente", limit=100000):
                jobs_repo.mark_job_cancelado(db, job, "Consultas desativadas pelo usuario.")
            cancelados += 1

    if cancelar_rodando:
        processos = _status_filter(
            db.query(Processo).join(Empresa, Empresa.id == Processo.empresa_id).filter(Processo.tipo == "consulta_nfse", Empresa.grupo == grupo),
            RODANDO_STATUSES,
        ).all()
        for processo in processos:
            processos_repo.cancelar_processo(db, processo)
            for job in jobs_repo.list_jobs(db, processo_id=processo.id, status="rodando", limit=100000):
                jobs_repo.mark_job_cancelado(db, job, "Consultas desativadas pelo usuario.")
            cancelados += 1

    db.commit()
    return {"automatico_ativo": False, "processos_cancelados": cancelados}
