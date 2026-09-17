from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
import logging
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


logger = logging.getLogger(__name__)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
REGRAS_XLSX_PATH = next(
    (
        path
        for path in (
            PROJECT_ROOT / "data" / "RETENCOES_REGRAS.xlsx",
            PROJECT_ROOT / "RETENCOES_REGRAS.xlsx",
        )
        if path.exists()
    ),
    PROJECT_ROOT / "data" / "RETENCOES_REGRAS.xlsx",
)

# Excecoes fiscais aprovadas que devem prevalecer sobre a planilha-base.
# Mantidas em codigo para que uma troca/atualizacao do XLSX nao reverta a regra.
IRRF_ALIQUOTAS_POR_SUBITEM = {
    "7.04": Decimal("0.01"),
}


def _sem_acentos(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalizar_flag_regra(value: str | None) -> str:
    text = _sem_acentos(str(value or "")).strip().upper()
    if not text:
        return "NAO"
    if text in {"SIM", "S"}:
        return "SIM"
    if text in {"NAO", "N", "NO", "NÃO"}:
        return "NAO"
    if text == "DEPENDE":
        return "DEPENDE"
    return "DEPENDE" if "DEPENDE" in text else "NAO"


def normalizar_subitem_lc116(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 6:
        grupo = int(digits[:2])
        return f"{grupo}.{digits[2:4]}"
    if len(digits) == 4:
        grupo = int(digits[:2])
        return f"{grupo}.{digits[2:4]}"
    if len(digits) == 3:
        grupo = int(digits[:1])
        return f"{grupo}.{digits[1:3]}"
    match = re.search(r"(\d{1,2})\D+(\d{1,2})", raw)
    if match:
        return f"{int(match.group(1))}.{int(match.group(2)):02d}"
    return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None


def _regra_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    subitem = normalizar_subitem_lc116(row.get("Subitem"))
    if not subitem:
        return None
    observacao = str(row.get("Observação fiscal essencial") or "").strip()
    if observacao in {"", "-", "—"}:
        observacao = ""
    obs_norm = _sem_acentos(observacao).lower()
    return {
        "subitem": subitem,
        "descricao": str(row.get("Descrição legal resumida") or "").strip(),
        "irrf": normalizar_flag_regra(row.get("IRRF")),
        "irrf_aliquota": _decimal_or_none(row.get("Alíquota")),
        "pcc": normalizar_flag_regra(row.get("PIS/COFINS/CSLL")),
        "inss": normalizar_flag_regra(row.get("INSS")),
        "observacao": observacao or None,
        "inss_optante_simples_retem": "optante do simples tambem retem" in obs_norm,
    }


_REGRAS_CACHE: dict[str, dict[str, Any]] | None = None


def _ler_planilha() -> dict[str, dict[str, Any]]:
    wb = load_workbook(REGRAS_XLSX_PATH, data_only=True, read_only=True)
    try:
        ws = wb["Planilha2"]
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    headers = [str(value or "").strip() for value in rows[0]]
    regras: dict[str, dict[str, Any]] = {}
    for row in rows[1:]:
        regra = _regra_from_row(dict(zip(headers, row)))
        if regra:
            regras[regra["subitem"]] = regra
    return regras


def carregar_regras_retencao() -> dict[str, dict[str, Any]]:
    """Carrega a planilha uma vez por processo.

    Um resultado vazio (arquivo ausente, aba renomeada, falha de leitura) NAO
    e cacheado e e logado como erro: a versao anterior usava lru_cache e uma
    unica falha na inicializacao do container deixava TODAS as notas daquele
    deploy com "Regra fiscal nao encontrada" mesmo com a regra na planilha
    (milhares de notas em producao).
    """
    global _REGRAS_CACHE
    if _REGRAS_CACHE:
        return _REGRAS_CACHE
    if not REGRAS_XLSX_PATH.exists():
        logger.error("Planilha de regras fiscais nao encontrada em %s", REGRAS_XLSX_PATH)
        return {}
    try:
        regras = _ler_planilha()
    except Exception:
        logger.exception("Falha ao ler a planilha de regras fiscais %s", REGRAS_XLSX_PATH)
        return {}
    if not regras:
        logger.error("Planilha de regras fiscais %s carregou 0 regras", REGRAS_XLSX_PATH)
        return {}
    _REGRAS_CACHE = regras
    logger.info("Planilha de regras fiscais carregada: %s subitens de %s", len(regras), REGRAS_XLSX_PATH)
    return regras


def obter_regra_por_subitem(subitem: str | None) -> dict[str, Any] | None:
    normalized = normalizar_subitem_lc116(subitem)
    if not normalized:
        return None
    regra = carregar_regras_retencao().get(normalized)
    if regra is None:
        return None
    aliquota_exclusiva = IRRF_ALIQUOTAS_POR_SUBITEM.get(normalized)
    if aliquota_exclusiva is None:
        return regra
    regra_ajustada = dict(regra)
    regra_ajustada["irrf_aliquota"] = aliquota_exclusiva
    return regra_ajustada


def resolver_subitem_lc116(dados_xml: dict[str, Any]) -> str | None:
    for key in (
        "cTribNac",
        "codigo_servico_nacional",
        "codigo_servico",
        "cTribMun",
        "cServ",
        "cServMun",
        "ItemListaServico",
        "itemListaServico",
        "CodigoServico",
        "codigoServico",
        "CodigoTributacaoMunicipio",
    ):
        subitem = normalizar_subitem_lc116(dados_xml.get(key))
        if subitem:
            return subitem
    return None
