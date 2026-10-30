"""Saude da operacao: estado da fila, vigia com aviso e retencao de logs.

O /health so diz que o processo responde. Aqui se olha o que importa para o
escritorio: a fila de consultas anda? os jobs estao falhando em serie? toda
empresa com certificado valido esta sendo consultada?
Quando algo para, o vigia avisa por e-mail (Resend) e pelo webhook de alerta,
no maximo uma vez a cada ALERTA_INTERVALO_HORAS por motivo.

Um servico fora do ar (ex.: Railway parado) nao consegue avisar sobre si
mesmo: para isso, um monitor externo deve consultar /health.
"""

from __future__ import annotations

import html
import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.observability import alert_failure
from backend.app.db.models import Certificado, Empresa, Job, LogProcesso, MonitoramentoConfig, Processo
from backend.app.services import email_service

logger = logging.getLogger(__name__)

_ultimo_aviso: dict[str, datetime] = {}
_trava_aviso = threading.Lock()

# Batimento do agendador embutido (main._run_consultas_scheduler), so deste
# processo. Em 08/10/2026 o agendador morreu numa excecao e ninguem percebeu
# por horas: o vigia compara este horario com o relogio.
_agendador: dict[str, object] = {"ultimo_tick": None, "ultimo_erro": None, "ultimo_erro_em": None}


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def registrar_tick_agendador(agora: datetime | None = None) -> None:
    _agendador["ultimo_tick"] = agora or _agora()


def registrar_erro_agendador(erro: str, agora: datetime | None = None) -> None:
    _agendador["ultimo_erro"] = erro[:500]
    _agendador["ultimo_erro_em"] = agora or _agora()


def _estado_agendador(agora: datetime) -> dict:
    tick = _agendador["ultimo_tick"]
    erro_em = _agendador["ultimo_erro_em"]
    return {
        "agendador_embutido": bool(settings.api_worker_enabled and settings.embedded_scheduler_enabled),
        "agendador_ultimo_tick_em": tick.isoformat() if isinstance(tick, datetime) else None,
        "agendador_minutos_sem_tick": (
            int((agora - tick).total_seconds() // 60) if isinstance(tick, datetime) else None
        ),
        "agendador_ultimo_erro": _agendador["ultimo_erro"],
        "agendador_ultimo_erro_em": erro_em.isoformat() if isinstance(erro_em, datetime) else None,
    }


def _aware(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def empresas_sem_consulta(db: Session, horas: int, agora: datetime | None = None) -> list[dict]:
    """Empresas que deveriam estar sendo consultadas e nao foram nas ultimas `horas`.

    Conta so empresa ativa, de grupo com monitor ligado, com certificado que o
    worker aceitaria (ativo, arquivo e senha salvos, dentro da validade) e
    cadastrado ha mais de `horas`. A fila andando nao garante que todas as
    empresas passam por ela: de 01/10 a 06/10/2026 o monitor ficou restrito a
    7 empresas e as outras 78 ficaram sem consulta sem nenhum aviso.
    """
    if horas <= 0:
        return []
    agora = agora or _agora()
    corte = agora - timedelta(hours=horas)
    grupos = [
        grupo
        for (grupo,) in db.query(MonitoramentoConfig.grupo).filter(MonitoramentoConfig.automatico_ativo.is_(True)).all()
        if grupo
    ]
    if not grupos:
        return []
    consultada = (
        db.query(Processo.id)
        .filter(
            Processo.empresa_id == Empresa.id,
            Processo.tipo == "consulta_nfse",
            Processo.status == "finalizado",
            Processo.finished_at >= corte,
        )
        .exists()
    )
    linhas = (
        db.query(Empresa.id, Empresa.nome)
        .join(Certificado, Certificado.empresa_id == Empresa.id)
        .filter(
            Empresa.ativo.is_(True),
            Empresa.grupo.in_(grupos),
            Certificado.ativo.is_(True),
            Certificado.storage_key.isnot(None),
            Certificado.storage_key.notin_(("", "pending")),
            Certificado.senha_secret_ref.isnot(None),
            or_(Certificado.valido_ate.is_(None), Certificado.valido_ate > agora),
            Certificado.created_at <= corte,
            ~consultada,
        )
        .distinct()
        .order_by(Empresa.nome.asc())
        .all()
    )
    return [{"id": int(empresa_id), "nome": nome} for empresa_id, nome in linhas]


def estado_operacao(db: Session) -> dict:
    agora = _agora()
    uma_hora = agora - timedelta(hours=1)
    pendentes = db.query(func.count(Job.id)).filter(Job.status == "pendente").scalar() or 0
    rodando = db.query(func.count(Job.id)).filter(Job.status == "rodando").scalar() or 0
    mais_antigo = (
        db.query(func.min(func.coalesce(Job.available_at, Job.created_at))).filter(Job.status == "pendente").scalar()
    )
    ultimo_finalizado = db.query(func.max(Job.updated_at)).filter(Job.status == "finalizado").scalar()
    falhas_ultima_hora = (
        db.query(func.count(Job.id)).filter(Job.status == "erro", Job.updated_at >= uma_hora).scalar() or 0
    )
    mais_antigo = _aware(mais_antigo)
    ultimo_finalizado = _aware(ultimo_finalizado)
    sem_consulta = empresas_sem_consulta(db, int(settings.alerta_empresa_sem_consulta_horas or 0), agora)
    return {
        "jobs_pendentes": int(pendentes),
        "jobs_rodando": int(rodando),
        "pendente_mais_antigo_minutos": int((agora - mais_antigo).total_seconds() // 60) if mais_antigo else None,
        "ultimo_job_finalizado_em": ultimo_finalizado.isoformat() if ultimo_finalizado else None,
        "falhas_ultima_hora": int(falhas_ultima_hora),
        "empresas_sem_consulta": len(sem_consulta),
        "empresas_sem_consulta_exemplos": [empresa["nome"] for empresa in sem_consulta[:10]],
        **_estado_agendador(agora),
    }


def problemas(estado: dict) -> dict[str, str]:
    """Motivos de alerta presentes no estado (motivo -> descricao)."""
    encontrados: dict[str, str] = {}
    limite_fila = max(1, int(settings.alerta_fila_parada_minutos))
    espera = estado.get("pendente_mais_antigo_minutos")
    if espera is not None and espera >= limite_fila and not estado.get("jobs_rodando"):
        encontrados["fila_parada"] = (
            f"Ha {estado['jobs_pendentes']} consulta(s) na fila e a mais antiga espera ha {espera} minutos "
            "sem nenhuma em execucao. O worker pode ter parado."
        )
    limite_falhas = max(1, int(settings.alerta_falhas_por_hora))
    if estado.get("falhas_ultima_hora", 0) >= limite_falhas:
        encontrados["falhas_em_serie"] = (
            f"{estado['falhas_ultima_hora']} consulta(s) terminaram em erro na ultima hora "
            f"(limite de aviso: {limite_falhas})."
        )
    sem_consulta = int(estado.get("empresas_sem_consulta") or 0)
    if sem_consulta:
        horas = int(settings.alerta_empresa_sem_consulta_horas)
        exemplos = ", ".join(estado.get("empresas_sem_consulta_exemplos") or [])
        resto = sem_consulta - len(estado.get("empresas_sem_consulta_exemplos") or [])
        encontrados["empresas_sem_consulta"] = (
            f"{sem_consulta} empresa(s) com certificado valido sem nenhuma consulta ao ADN nas ultimas {horas} horas: "
            f"{exemplos}{f' e mais {resto}' if resto > 0 else ''}. "
            "Confira no Motor ADN se o monitor automatico esta consultando todas as empresas."
        )
    limite_agendador = int(settings.alerta_agendador_parado_minutos or 0)
    sem_tick = estado.get("agendador_minutos_sem_tick")
    if estado.get("agendador_embutido") and limite_agendador > 0 and sem_tick is not None and sem_tick >= limite_agendador:
        erro = estado.get("agendador_ultimo_erro")
        encontrados["agendador_parado"] = (
            f"O agendador de consultas automaticas esta ha {sem_tick} minutos sem rodar "
            f"(limite de aviso: {limite_agendador}). Nenhuma consulta nova entra na fila. "
            f"{f'Ultimo erro: {erro}. ' if erro else ''}Reinicie o servico se o aviso continuar."
        )
    return encontrados


def _pode_avisar(motivo: str, agora: datetime) -> bool:
    intervalo = timedelta(hours=max(1, int(settings.alerta_intervalo_horas)))
    with _trava_aviso:
        anterior = _ultimo_aviso.get(motivo)
        if anterior is not None and agora - anterior < intervalo:
            return False
        _ultimo_aviso[motivo] = agora
        return True


def _enviar_aviso(motivo: str, descricao: str) -> None:
    alert_failure(f"operacao_{motivo}", descricao)
    for destino in settings.alerta_email_list:
        try:
            email_service.enviar_email(
                para=destino,
                assunto=f"[Portal NFS-e] Alerta: {motivo.replace('_', ' ')}",
                html_corpo=(
                    "<div style=\"font-family:Arial,sans-serif;font-size:14px;color:#1f2937\">"
                    f"<p><strong>Alerta da operacao do Portal NFS-e</strong></p><p>{html.escape(descricao)}</p>"
                    "<p>Verifique os logs do servico e a fila em /health/operacao.</p></div>"
                ),
                texto_log_local=descricao,
            )
        except email_service.EmailServiceError as exc:
            logger.error("Aviso de operacao nao enviado para %s: %s", destino, exc)


def verificar_e_avisar(db: Session) -> list[str]:
    """Roda no supervisor: avisa cada problema no maximo 1x por intervalo."""
    agora = _agora()
    avisados = []
    for motivo, descricao in problemas(estado_operacao(db)).items():
        if _pode_avisar(motivo, agora):
            _enviar_aviso(motivo, descricao)
            avisados.append(motivo)
    return avisados


def limpar_logs_antigos(db: Session, lote: int = 5000, *, dias: int | None = None) -> int:
    """Apaga logs_processos mais antigos que LOGS_RETENCAO_DIAS (0 = nunca)."""
    dias = int(settings.logs_retencao_dias or 0) if dias is None else int(dias)
    if dias <= 0:
        return 0
    corte = _agora() - timedelta(days=dias)
    removidos = 0
    while True:
        ids = [
            linha[0]
            for linha in db.query(LogProcesso.id).filter(LogProcesso.created_at < corte).limit(max(1, lote)).all()
        ]
        if not ids:
            return removidos
        db.query(LogProcesso).filter(LogProcesso.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
        removidos += len(ids)
