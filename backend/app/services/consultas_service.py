from __future__ import annotations

import logging
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


logger = logging.getLogger(__name__)

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


def descrever_monitor(db: Session, config: MonitoramentoConfig, grupo: str) -> dict[str, Any]:
    """Diz se o monitor consulta todas as empresas do grupo ou so algumas.

    So SQL: roda a cada atualizacao da tela e nao pode abrir senhas.
    """
    filtros = ConsultaIniciarRequest(**(config.filtros_json or {}))
    restrito = filtros.empresa_ids is not None or filtros.certificado_ids is not None

    base = (
        db.query(Empresa.id, Empresa.nome)
        .join(Certificado, Certificado.empresa_id == Empresa.id)
        .filter(Empresa.grupo == grupo, Empresa.ativo.is_(True), Certificado.ativo.is_(True))
        .distinct()
    )
    total = base.count()
    monitoradas = base
    if filtros.empresa_ids is not None:
        monitoradas = monitoradas.filter(Empresa.id.in_(filtros.empresa_ids))
    if filtros.certificado_ids is not None:
        monitoradas = monitoradas.filter(Certificado.id.in_(filtros.certificado_ids))
    empresas = monitoradas.order_by(Empresa.nome.asc()).all() if restrito else []
    quantidade = len(empresas) if restrito else total

    return {
        "escopo": "restrito" if restrito else "global",
        "empresa_ids": filtros.empresa_ids,
        "certificado_ids": filtros.certificado_ids,
        "empresas": [{"id": int(empresa_id), "nome": nome} for empresa_id, nome in empresas],
        "empresas_monitoradas": quantidade,
        "empresas_fora_do_monitor": max(0, total - quantidade),
    }


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
        "monitor": descrever_monitor(db, config, grupo),
    }


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
    agora = _now()
    for certificado in certificados:
        validade = _as_aware(certificado.valido_ate)
        if validade is not None and validade <= agora:
            # O ADN recusa certificado vencido. Antes ele entrava na fila a cada
            # ciclo e gastava ~3,5 min em 5 tentativas antes de falhar,
            # atrasando todas as outras empresas (477 erros em 7 dias).
            logger.warning(
                "Certificado %s ignorado na consulta: vencido em %s. Renove ou desative o certificado.",
                certificado.id,
                validade.date().isoformat(),
            )
            continue
        try:
            secrets_service.get_secret_value(db, str(certificado.senha_secret_ref))
        except secrets_service.SecretsServiceError as exc:
            # Sem este log o certificado simplesmente some da fila: nenhuma
            # consulta e enfileirada e o portal fica parado sem explicacao.
            # A causa tipica e SECRETS_KEY trocada sem recadastrar as senhas.
            logger.error(
                "Certificado %s ignorado na consulta: senha nao pode ser lida (%s). "
                "Verifique a SECRETS_KEY ou recadastre a senha do certificado.",
                certificado.id,
                exc,
            )
            continue
        elegiveis.append(certificado)
    return elegiveis


def _create_consulta_job(
    db: Session, certificado: Certificado, options: ConsultaIniciarRequest,
    available_at: datetime | None = None,
) -> Processo:
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
            "available_at": available_at if available_at is not None else _now(),
            "payload_json": {
                "empresa_id": certificado.empresa_id,
                "certificado_id": certificado.id,
                "tipo": "consulta_nfse",
                "nsu_inicio": options.nsu_inicio,
                "limite": limite,
                "pausa": pausa,
                "gerar_pdf_espelho": options.gerar_pdf_espelho,
                "releitura_mes_anterior": bool(options.releitura_mes_anterior),
            },
        },
    )
    return processo


def enqueue_consultas_pendentes(
    db: Session,
    options: ConsultaIniciarRequest | None = None,
    respeitar_ciclo: bool = True,
    grupo: str = "planning_hub",
    atualizar_ciclo: bool = True,
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

    # `options.limite` e o teto de consultas NSU de cada job, nao a quantidade
    # de certificados do ciclo. Usa-lo aqui fazia um limite pequeno (ex.: 1)
    # enfileirar um unico certificado e deixar os demais sem consulta.
    pendentes = []
    for certificado in certificados:
        if not options.forcar and int(certificado.id) in certificados_ativos:
            certificados_ignorados += 1
            continue
        pendentes.append(certificado)
    # So ciclos automaticos sao distribuidos. Pedidos manuais/forcados e
    # releituras avulsas continuam disponiveis imediatamente.
    distribuir = respeitar_ciclo and atualizar_ciclo and config.automatico_ativo and not options.forcar
    espacamento = (int(config.intervalo_minutos) * 60 / len(pendentes)) if distribuir and pendentes else 0
    for indice, certificado in enumerate(pendentes):
        disponibilidade = agora + timedelta(seconds=indice * espacamento)
        processos_criados.append(_create_consulta_job(db, certificado, options, available_at=disponibilidade))

    if atualizar_ciclo:
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


def _consulta_avulsa(db: Session, options: ConsultaIniciarRequest, grupo: str) -> dict[str, Any]:
    """Consulta pontual: enfileira so o pedido e nao toca no monitor do grupo.

    Antes, uma consulta avulsa gravava automatico_ativo e os filtros
    (empresa_ids) no monitor: o automatico passava a consultar so aquela
    empresa, ou era desligado. Em 17/09/2026 o monitor global de producao
    teve de ser restaurado a mao por isso.
    """
    if options.nsu_inicio is not None:
        # Novo ponto de partida so para os certificados pedidos.
        alvos = [int(c.id) for c in list_certificados_elegiveis(db, options=options, grupo=grupo)]
        _cancelar_consultas_dos_certificados(db, alvos, "Nova consulta com NSU inicial informado.")
    return enqueue_consultas_pendentes(
        db, options=options, respeitar_ciclo=False, grupo=grupo, atualizar_ciclo=False
    )


def solicitar_releitura_mes_anterior(db: Session, empresa_ids: list[int], grupo: str = "planning_hub") -> dict[str, Any]:
    """Enfileira, para cada certificado elegivel das empresas, uma consulta que
    rele desde antes do 1o dia do mes anterior. Nao mexe no monitor; empresas
    de outro grupo sao ignoradas pelo filtro de grupo; certificado com consulta
    ja na fila ou rodando e pulado (a releitura nao concorre com ela)."""
    if not empresa_ids:
        raise ValueError("Informe ao menos uma empresa.")
    options = ConsultaIniciarRequest(automatico=False, empresa_ids=empresa_ids, releitura_mes_anterior=True)
    resultado = _consulta_avulsa(db, options, grupo)
    return {
        "processos_criados": len(resultado["processos_criados"]),
        "certificados_ignorados": int(resultado["certificados_ignorados"]),
    }


def _cancelar_consultas_dos_certificados(db: Session, certificado_ids: list[int], motivo: str) -> int:
    if not certificado_ids:
        return 0
    processos = (
        db.query(Processo)
        .filter(Processo.tipo == "consulta_nfse", Processo.certificado_id.in_(certificado_ids))
        .filter(Processo.status.in_(PENDENTE_STATUSES + RODANDO_STATUSES))
        .all()
    )
    for processo in processos:
        processos_repo.cancelar_processo(db, processo)
        for job in jobs_repo.list_jobs(db, processo_id=processo.id, limit=100000):
            if job.status in {"pendente", "rodando"}:
                jobs_repo.mark_job_cancelado(db, job, motivo)
    db.commit()
    return len(processos)


def iniciar_consultas_automaticas(
    db: Session,
    options: ConsultaIniciarRequest | None = None,
    grupo: str = "planning_hub",
) -> dict[str, Any]:
    options = options or ConsultaIniciarRequest()
    if not options.automatico:
        return _consulta_avulsa(db, options, grupo)
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
    filtros_ciclos = options.model_copy(update={"nsu_inicio": None, "forcar": False, "releitura_mes_anterior": False})
    config.filtros_json = filtros_ciclos.model_dump()
    db.add(config)
    db.commit()
    return resultado


def iniciar_certificado_sem_substituir_monitor(
    db: Session,
    options: ConsultaIniciarRequest,
    grupo: str = "planning_hub",
) -> dict[str, Any]:
    """Enfileira um certificado novo sem retirar os anteriores do monitor.

    O autocadastro nunca restringe o monitor. Com o monitor parado, so a
    consulta do certificado novo e enfileirada (antes o monitor era ligado
    consultando apenas essa empresa). Com o monitor ligado, o certificado e
    somado apenas as dimensoes ja restritas: um filtro ausente significa
    "todas" e continua ausente.
    """
    config = get_monitoramento_config(db, grupo)
    if not config.automatico_ativo:
        return _consulta_avulsa(db, options.model_copy(update={"automatico": False}), grupo)

    filtros_atuais = ConsultaIniciarRequest(**(config.filtros_json or {}))

    # O NSU e o modo forcar do autocadastro valem somente para o job imediato.
    resultado = enqueue_consultas_pendentes(
        db,
        options=options,
        respeitar_ciclo=False,
        grupo=grupo,
    )

    # Os filtros se combinam (empresa E certificado). Em 01/10/2026 o monitor
    # tinha so certificado_ids; somar a empresa nova a um empresa_ids vazio
    # criou a lista [empresa nova] e o monitor passou a consultar so ela,
    # deixando 78 de 84 empresas sem consulta por 5 dias.
    def _somar(atuais: list[int] | None, novos: list[int] | None) -> list[int] | None:
        if atuais is None:
            return None
        return sorted(set(atuais) | set(novos or []))

    filtros_ciclos = filtros_atuais.model_copy(
        update={
            "empresa_ids": _somar(filtros_atuais.empresa_ids, options.empresa_ids),
            "certificado_ids": _somar(filtros_atuais.certificado_ids, options.certificado_ids),
            "nsu_inicio": None,
            "forcar": False,
            "releitura_mes_anterior": False,
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
