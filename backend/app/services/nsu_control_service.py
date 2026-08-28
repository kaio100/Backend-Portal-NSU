from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.db.models import Empresa, Nota, NsuControle
from backend.app.core.config import settings


def only_digits(value: str | None) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def maior_nsu_importado(db: Session, empresa_id: int) -> int:
    value = (
        db.query(func.max(Nota.ultimo_nsu))
        .filter(Nota.empresa_id == empresa_id)
        .filter(Nota.ultimo_nsu.isnot(None))
        .scalar()
    )
    return int(value or 0)


def nsu_base_mes_anterior(db: Session, empresa_id: int, referencia: date) -> int | None:
    """Localiza um NSU anterior ao mes alvo para atravessa-lo por completo."""
    inicio_mes_atual = referencia.replace(day=1)
    fim_mes_anterior = inicio_mes_atual - timedelta(days=1)
    inicio_mes_anterior = fim_mes_anterior.replace(day=1)
    data_nota = func.coalesce(Nota.data_emissao, Nota.competencia)
    nsu_inicio_nota = func.coalesce(Nota.primeiro_nsu, Nota.ultimo_nsu)
    nsu_fim_nota = func.coalesce(Nota.ultimo_nsu, Nota.primeiro_nsu)
    limite_anterior = (
        db.query(func.max(nsu_fim_nota))
        .filter(Nota.empresa_id == empresa_id)
        .filter(nsu_fim_nota.isnot(None))
        .filter(data_nota < inicio_mes_anterior)
        .scalar()
    )
    if limite_anterior is not None:
        return int(limite_anterior)

    value = (
        db.query(func.min(nsu_inicio_nota))
        .filter(Nota.empresa_id == empresa_id)
        .filter(nsu_inicio_nota.isnot(None))
        .filter(data_nota >= inicio_mes_anterior)
        .filter(data_nota < inicio_mes_atual)
        .scalar()
    )
    return int(value) if value is not None else None


def obter_ultimo_nsu(
    db: Session,
    empresa_id: int,
    certificado_id: int | None = None,
) -> int:
    row = (
        db.query(NsuControle)
        .filter(NsuControle.empresa_id == empresa_id)
        .filter(NsuControle.certificado_id == certificado_id)
        .first()
    )
    central = int(row.ultimo_nsu or 0) if row else 0
    return max(central, maior_nsu_importado(db, empresa_id))


def janela_reconciliacao(now: datetime | None = None) -> date | None:
    """Retorna a data da janela 19h-05h; apos meia-noite pertence ao dia anterior."""
    timezone = ZoneInfo(settings.nsu_reconciliacao_timezone or "America/Sao_Paulo")
    momento = now or datetime.now(timezone)
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone)
    else:
        momento = momento.astimezone(timezone)
    inicio = max(0, min(23, int(settings.nsu_reconciliacao_hora_inicio)))
    fim = max(0, min(23, int(settings.nsu_reconciliacao_hora_fim)))
    if momento.hour >= inicio:
        return momento.date()
    if momento.hour < fim:
        return momento.date() - timedelta(days=1)
    return None


def planejar_inicio_consulta(
    db: Session,
    empresa_id: int,
    certificado_id: int | None,
    now: datetime | None = None,
) -> dict:
    confirmado = obter_ultimo_nsu(db, empresa_id, certificado_id=certificado_id)
    controle = (
        db.query(NsuControle)
        .filter(NsuControle.empresa_id == empresa_id)
        .filter(NsuControle.certificado_id == certificado_id)
        .first()
    )
    janela = janela_reconciliacao(now)
    profunda = bool(janela is not None and (controle is None or controle.ultima_reconciliacao_em != janela))
    recuo = (
        int(settings.nsu_lookback_reconciliacao or 1000)
        if profunda
        else int(settings.nsu_lookback_normal or 50)
    )
    recuo = max(0, recuo)
    nsu_mes_anterior = nsu_base_mes_anterior(db, empresa_id, janela) if profunda and janela else None
    if nsu_mes_anterior is not None:
        nsu_inicio = max(0, nsu_mes_anterior - recuo)
    else:
        nsu_inicio = max(0, confirmado - recuo)
    return {
        "nsu_confirmado": confirmado,
        "nsu_inicio": nsu_inicio,
        "recuo": max(0, confirmado - nsu_inicio),
        "margem_seguranca": recuo,
        "nsu_mes_anterior": nsu_mes_anterior,
        "reconciliacao_profunda": profunda,
        "janela_reconciliacao": janela,
    }


def marcar_reconciliacao_concluida(
    db: Session,
    empresa_id: int,
    certificado_id: int | None,
    janela: date,
) -> None:
    controle = (
        db.query(NsuControle)
        .filter(NsuControle.empresa_id == empresa_id)
        .filter(NsuControle.certificado_id == certificado_id)
        .first()
    )
    if controle is not None:
        controle.ultima_reconciliacao_em = janela
        db.add(controle)


def atualizar_ultimo_nsu(
    db: Session,
    empresa_id: int,
    certificado_id: int | None,
    cnpj: str,
    ultimo_nsu: int | None,
    origem: str,
) -> NsuControle | None:
    if ultimo_nsu is None:
        return None
    nsu = int(ultimo_nsu or 0)
    if nsu < 0:
        nsu = 0
    cnpj_digits = only_digits(cnpj)
    if not cnpj_digits:
        empresa = db.get(Empresa, empresa_id)
        cnpj_digits = only_digits(empresa.cnpj if empresa else "")
    if not cnpj_digits:
        return None

    row = (
        db.query(NsuControle)
        .filter(NsuControle.empresa_id == empresa_id)
        .filter(NsuControle.certificado_id == certificado_id)
        .first()
    )
    if row is None:
        row = NsuControle(
            empresa_id=empresa_id,
            certificado_id=certificado_id,
            cnpj=cnpj_digits,
            ultimo_nsu=nsu,
            origem=origem,
        )
        db.add(row)
        db.flush()
        db.refresh(row)
        return row

    if nsu >= int(row.ultimo_nsu or 0):
        row.ultimo_nsu = nsu
        row.origem = origem
        row.cnpj = cnpj_digits
        db.add(row)
        db.flush()
        db.refresh(row)
    return row


def sincronizar_com_notas(
    db: Session,
    empresa_id: int,
    certificado_id: int | None,
    cnpj: str,
    origem: str = "notas",
) -> int:
    nsu = maior_nsu_importado(db, empresa_id)
    atualizar_ultimo_nsu(db, empresa_id, certificado_id, cnpj, nsu, origem=origem)
    return nsu
