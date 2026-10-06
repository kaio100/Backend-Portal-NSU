"""Datas de negocio no fuso do escritorio.

O container roda em UTC: `date.today()` vira o dia seguinte a partir das 21h
de Brasilia e o painel mostrava "acessos de hoje" zerados a noite. O banco
continua gravando em UTC; so a leitura para o usuario usa o fuso local.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from backend.app.core.config import settings


@lru_cache(maxsize=4)
def _zona(nome: str) -> ZoneInfo:
    return ZoneInfo(nome)


def fuso() -> ZoneInfo:
    return _zona(settings.fuso_horario or "America/Sao_Paulo")


def agora_local() -> datetime:
    return datetime.now(fuso())


def hoje_local() -> date:
    return agora_local().date()


def inicio_do_dia_utc(dia: date) -> datetime:
    """Meia-noite local de `dia`, em UTC, para comparar com colunas do banco."""
    return datetime.combine(dia, time.min, tzinfo=fuso()).astimezone(timezone.utc)


def data_local(valor: datetime) -> date:
    """Dia local de um horario gravado no banco (sem fuso = UTC)."""
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(fuso()).date()
