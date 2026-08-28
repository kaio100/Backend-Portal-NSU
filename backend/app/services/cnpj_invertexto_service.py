from __future__ import annotations

import time
from typing import Any

import requests
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.services import cnpj_cache_service


FONTE = "Invertexto"


def _flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().upper()
    if normalized in {"S", "SIM", "TRUE", "1"}:
        return True
    if normalized in {"N", "NAO", "NÃO", "FALSE", "0"}:
        return False
    return None


def normalizar_payload(payload: dict | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not payload:
        return None
    simples = payload.get("simples") or {}
    mei = payload.get("mei") or payload.get("simei") or {}
    mei_optante = _flag(mei.get("optante") if "optante" in mei else mei.get("optante_mei"))
    simples_optante = _flag(
        simples.get("optante") if "optante" in simples else simples.get("optante_simples")
    )
    if mei_optante is True:
        consulta = "MEI"
    elif simples_optante is True:
        consulta = "Optante S.N"
    elif simples_optante is False:
        consulta = "Não optante"
    else:
        return None
    atividade = payload.get("atividade_principal") or payload.get("atividadePrincipal") or {}
    if isinstance(atividade, list):
        atividade = atividade[0] if atividade else {}
    return {
        "consulta_simples_api": consulta,
        "codigo_cnae": cnpj_cache_service.only_digits(
            atividade.get("code") or atividade.get("codigo") or payload.get("cnae")
        ),
        "descricao_cnae": str(
            atividade.get("text") or atividade.get("descricao") or payload.get("descricao_cnae") or ""
        ).strip(),
        "json_resposta": payload,
    }


def consultar_cnpj(db: Session, cnpj: str) -> dict[str, Any] | None:
    cnpj = cnpj_cache_service.only_digits(cnpj)
    if len(cnpj) != 14 or not settings.invertexto_enabled or not settings.invertexto_token:
        return None
    response = requests.get(
        f"https://api.invertexto.com/v1/cnpj/{cnpj}",
        params={"token": settings.invertexto_token},
        timeout=20,
    )
    response.raise_for_status()
    resultado = normalizar_payload(response.json())
    if resultado is None:
        return None
    cnpj_cache_service.salvar_cache(
        db,
        cnpj,
        consulta_simples_api=resultado["consulta_simples_api"],
        codigo_cnae=resultado["codigo_cnae"],
        descricao_cnae=resultado["descricao_cnae"],
        status_consulta="OK",
        json_resposta=resultado["json_resposta"],
        fonte=FONTE,
        cache_days=settings.invertexto_cache_days,
    )
    db.commit()
    return resultado


def consultar_cnpjs(db: Session, cnpjs: set[str]) -> dict[str, dict[str, Any]]:
    resultados: dict[str, dict[str, Any]] = {}
    delay = max(float(settings.invertexto_delay_seconds), 60.0 / max(1, int(settings.invertexto_rpm)))
    for index, cnpj in enumerate(sorted(cnpjs)):
        if index:
            time.sleep(delay)
        try:
            resultado = consultar_cnpj(db, cnpj)
        except requests.RequestException:
            db.rollback()
            continue
        if resultado is not None:
            resultados[cnpj_cache_service.only_digits(cnpj)] = resultado
    return resultados
