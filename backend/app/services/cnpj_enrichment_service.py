from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Empresa, Nota, Processo
from backend.app.services import cnpj_cache_service, portal_support_service


def _only_digits(value: str | None) -> str:
    return cnpj_cache_service.only_digits(value)


def coletar_cnpjs_para_enriquecimento(
    db: Session,
    processo_id: int,
    certificado_id: int | None = None,
) -> set[str]:
    processo = db.get(Processo, int(processo_id))
    if processo is None:
        return set()

    empresa = db.get(Empresa, int(processo.empresa_id))
    empresa_cnpj = _only_digits(empresa.cnpj if empresa is not None else None)

    cnpjs: set[str] = set()
    rows = db.query(Nota.prestador_cnpj, Nota.tomador_cnpj).filter(Nota.processo_id == int(processo_id)).all()
    for prestador_cnpj, tomador_cnpj in rows:
        for cnpj in (_only_digits(prestador_cnpj), _only_digits(tomador_cnpj)):
            if len(cnpj) == 14 and cnpj != empresa_cnpj:
                cnpjs.add(cnpj)
    return cnpjs


def enriquecer_cnpjs_do_processo(
    db: Session,
    processo_id: int,
    certificado_id: int | None = None,
) -> dict[str, Any]:
    cnpjs = coletar_cnpjs_para_enriquecimento(db, processo_id, certificado_id=certificado_id)
    cache_validos = {
        cnpj
        for cnpj in cnpjs
        if cnpj_cache_service.get_cache_valido(db, cnpj) is not None
    }
    pendentes = cnpjs - cache_validos

    if not cnpjs:
        return {
            "processo_id": processo_id,
            "certificado_id": certificado_id,
            "cnpjs_total": 0,
            "cache_validos": 0,
            "pendentes": 0,
            "api_habilitada": bool(settings.invertexto_enabled and settings.invertexto_token),
            "consultados": 0,
            "erros": 0,
        }

    resultados = portal_support_service._consultar_invertexto_cnpjs(db, cnpjs)
    erros = sum(1 for result in resultados.values() if result.get("consulta") == "Erro na consulta")
    api_habilitada = bool(settings.invertexto_enabled and settings.invertexto_token)

    return {
        "processo_id": processo_id,
        "certificado_id": certificado_id,
        "cnpjs_total": len(cnpjs),
        "cache_validos": len(cache_validos),
        "pendentes": len(pendentes),
        "api_habilitada": api_habilitada,
        "consultados": len(pendentes) if api_habilitada else 0,
        "erros": erros,
    }
