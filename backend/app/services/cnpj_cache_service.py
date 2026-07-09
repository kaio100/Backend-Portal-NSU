from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import CnpjCache


DEFAULT_FONTE = "Invertexto"


def only_digits(value: str | None) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _cache_to_dict(cache: CnpjCache) -> dict[str, Any]:
    return {
        "cnpj": cache.cnpj,
        "fonte": cache.fonte,
        "consulta": cache.consulta_simples_api or cache.simples_status or "Não disponível",
        "consulta_simples_api": cache.consulta_simples_api or cache.simples_status or "Não disponível",
        "cnae": cache.codigo_cnae or "",
        "codigo_cnae": cache.codigo_cnae or "",
        "descricao_cnae": cache.descricao_cnae or "",
        "status_consulta": cache.status_consulta or cache.status,
        "json_resposta": cache.json_resposta or cache.json_completo,
        "erro": cache.erro,
        "data_consulta": cache.data_consulta,
        "data_expiracao": cache.data_expiracao,
    }


def get_cache_valido(db: Session, cnpj: str, fonte: str = DEFAULT_FONTE) -> dict[str, Any] | None:
    cnpj_digits = only_digits(cnpj)
    if not cnpj_digits:
        return None
    cache = (
        db.query(CnpjCache)
        .filter(CnpjCache.cnpj == cnpj_digits)
        .filter(CnpjCache.fonte == fonte)
        .first()
    )
    if cache is None or cache.data_expiracao is None:
        return None
    if cache.data_expiracao < _today():
        return None
    return _cache_to_dict(cache)


def salvar_cache(
    db: Session,
    cnpj: str,
    consulta_simples_api: str,
    codigo_cnae: str | None,
    descricao_cnae: str | None,
    status_consulta: str,
    json_resposta: dict | None,
    erro: str | None = None,
    fonte: str = DEFAULT_FONTE,
    cache_days: int | None = None,
) -> None:
    cnpj_digits = only_digits(cnpj)
    if not cnpj_digits:
        return
    consulta_em = _today()
    validade_dias = max(1, int(cache_days if cache_days is not None else (settings.invertexto_cache_days or 30)))
    expira_em = consulta_em + timedelta(days=validade_dias)
    cache = (
        db.query(CnpjCache)
        .filter(CnpjCache.cnpj == cnpj_digits)
        .filter(CnpjCache.fonte == fonte)
        .first()
    )
    if cache is None:
        cache = CnpjCache(cnpj=cnpj_digits, fonte=fonte)
        db.add(cache)

    cache.consulta_simples_api = consulta_simples_api
    cache.codigo_cnae = codigo_cnae or ""
    cache.descricao_cnae = descricao_cnae or ""
    cache.status_consulta = status_consulta
    cache.json_resposta = json_resposta
    cache.erro = erro
    cache.data_consulta = consulta_em
    cache.data_expiracao = expira_em
    cache.status = status_consulta
    cache.simples_status = consulta_simples_api
    cache.json_completo = json_resposta
    cache.updated_at = datetime.now(timezone.utc)
    db.add(cache)
    db.flush()
