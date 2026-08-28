from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Empresa, Nota, Processo
from backend.app.services import cnpj_cache_service, cnpj_receita_service


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
            # CPF e classificado localmente como nao optante; somente CNPJ
            # precisa de enriquecimento por base externa/cache.
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

    receita_encontrados = 0
    receita_ausentes = 0
    encontrados: dict[str, dict[str, Any]] = {}
    if pendentes:
        base_receita_disponivel = True
        try:
            encontrados = cnpj_receita_service.consultar_cnpjs(pendentes)
        except cnpj_receita_service.CnpjReceitaError:
            base_receita_disponivel = False
            encontrados = {}
        for cnpj, item in encontrados.items():
            consulta = cnpj_receita_service.status_simples(item)
            cnpj_cache_service.salvar_cache(
                db,
                cnpj,
                consulta_simples_api=consulta,
                codigo_cnae=item.get("cnae_fiscal_principal"),
                descricao_cnae="",
                status_consulta="Encontrado",
                json_resposta=item,
                fonte=cnpj_cache_service.RECEITA_FONTE,
                cache_days=settings.cnpj_receita_cache_days,
            )
        # Regra operacional: CNPJ ausente na competencia atual da base da
        # Receita tambem e tratado como nao optante por 30 dias.
        ausentes_receita = (pendentes - set(encontrados)) if base_receita_disponivel else set()
        for cnpj in ausentes_receita:
            cnpj_cache_service.salvar_cache(
                db,
                cnpj,
                consulta_simples_api="Não optante",
                codigo_cnae="",
                descricao_cnae="",
                status_consulta="Não encontrado - regra operacional",
                json_resposta={
                    "cnpj": cnpj,
                    "fonte": cnpj_cache_service.RECEITA_FONTE,
                    "regra": "CNPJ ausente na base da Receita considerado não optante",
                },
                fonte=cnpj_cache_service.RECEITA_FONTE,
                cache_days=settings.cnpj_receita_cache_days,
            )
        if encontrados or ausentes_receita:
            db.commit()
        receita_encontrados = len(encontrados)
        receita_ausentes = len(ausentes_receita)

    # A decisao e integralmente local; CNPJ ausente tambem recebe a
    # classificacao operacional acima e nao consome API externa.
    resultados: dict[str, dict] = {}
    erros = 0
    api_habilitada = bool(settings.invertexto_enabled and settings.invertexto_token)

    return {
        "processo_id": processo_id,
        "certificado_id": certificado_id,
        "cnpjs_total": len(cnpjs),
        "cache_validos": len(cache_validos),
        "pendentes": len(pendentes),
        "receita_encontrados": receita_encontrados,
        "receita_ausentes": receita_ausentes,
        "api_habilitada": api_habilitada,
        "consultados": 0,
        "erros": erros,
    }
