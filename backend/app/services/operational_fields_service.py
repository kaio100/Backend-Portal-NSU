from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm.attributes import set_committed_value


SLA_THRESHOLDS = {
    "alta": {"warn": 24, "danger": 48},
    "media": {"warn": 36, "danger": 72},
    "baixa": {"warn": 72, "danger": 120},
}

OK_VALUES = {"", "ok", "correto", "correta", "sem divergencia", "sem divergência", "regular", "nao se aplica", "não se aplica"}
DIVERGENT_VALUES = {"divergente", "ausente", "erro", "inconsistente"}
DIVERGENCE_HINTS = (
    "base zerada",
    "diverg",
    "esperado",
    "encontrado",
    "deveria ser",
    "nao retido",
    "não retido",
    "mas veio 0.00",
    "mas veio 0,00",
)


def _strip_accents(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(char)
    )


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", _strip_accents(str(value or "")).strip().lower())


def normalizar_simples_xml(value: str | None) -> str | None:
    text = _norm(value)
    if not text:
        return None
    if text == "mei":
        return "MEI"
    if text in {"optante", "optante s.n", "optante sn", "simples nacional", "simples"}:
        return "Optante S.N"
    if text in {"nao optante", "n?o optante"}:
        return "Não optante"
    return str(value).strip() or None


def simples_xml_from_codes(op_simp_nac: str | None = None, reg_ap_trib_sn: str | None = None) -> str | None:
    op = (op_simp_nac or "").strip()
    if op == "1":
        return "Não optante"
    if op == "2":
        return "MEI"
    if op == "3":
        return "Optante S.N"
    if op:
        normalized = normalizar_simples_xml(op)
        if normalized != op:
            return normalized

    reg = (reg_ap_trib_sn or "").strip()
    if reg == "1":
        return "Simples Nacional"
    if reg:
        normalized = normalizar_simples_xml(reg)
        if normalized != reg:
            return normalized
        return "Não optante"
    return None


def consulta_simples_api_from_payload(payload: dict | None) -> str:
    """Deprecated: Simples Nacional is now sourced only from XML."""
    if payload is None:
        return "Não disponível"
    try:
        simei = payload.get("simei") or {}
        simples = payload.get("simples") or {}
        if simei.get("optante") is True:
            return "MEI"
        if simples.get("optante") is True:
            return "Optante S.N"
        if simples.get("optante") is False:
            return "Não optante"
        return "Não disponível"
    except Exception:
        return "Erro na consulta"


def calcular_status_simples_nacional_xml(simples_xml: str | None) -> str:
    normalized = normalizar_simples_xml(simples_xml)
    if normalized in {"MEI", "Optante S.N", "Simples Nacional", "Não optante"}:
        return "Informado no XML"
    if not normalized:
        return "Não informado no XML"
    return "Indefinido no XML"


def calcular_status_simples_nacional(simples_xml: str | None, consulta_simples_api: str | None = None) -> str:
    xml = normalizar_simples_xml(simples_xml)
    api_raw = (consulta_simples_api or "").strip()
    api = normalizar_simples_xml(api_raw)

    if not api_raw or api_raw in {"Não consultado", "Não disponível"}:
        return "Pendente"
    if api_raw == "Erro na consulta":
        return "Erro"
    if not xml:
        return "Não informado no XML"
    if not api:
        return "Pendente"

    grupos_optantes = {"Optante S.N", "Simples Nacional"}
    conferem = xml == api or (xml in grupos_optantes and api in grupos_optantes)
    return "Correto" if conferem else "Divergente"


def normalizar_status_fila(value: str | None) -> str | None:
    text = _norm(value)
    if not text:
        return None
    if text in {"cancelada", "cancelado"}:
        return "cancelada"
    if text == "pendente":
        return "pendente"
    if text == "divergente":
        return "divergente"
    if text in {"substituida", "substituido"}:
        return "substituida"
    if text in {"correta", "correto", "ok"}:
        return "correta"
    return text


def _contains_divergence_hint(value: str | None) -> bool:
    text = _norm(value)
    return any(_norm(hint) in text for hint in DIVERGENCE_HINTS)


def _status_field_is_divergent(value: str | None) -> bool:
    text = _norm(value)
    if text in OK_VALUES:
        return False
    if text in DIVERGENT_VALUES:
        return True
    return bool(text and text not in OK_VALUES)


def calcular_status_fila(nota) -> str:
    observacao = getattr(nota, "conferencia_observacao", None) or getattr(nota, "observacao_interna", None)
    alertas = getattr(nota, "alertas_fiscais", None)
    tem_alerta_fiscal = bool(alertas) and not any(word in _norm(alertas) for word in ("correto", "correta"))

    # A conferencia manual (marcar ok/corrigir/pendente) e a decisao final do
    # revisor e tem que valer em qualquer lugar que mostre o status da nota
    # (dashboard, conferencia S/Tomados, S/Prestados) assim que ele salva —
    # nao fica condicionada a alertas_fiscais. Como alertas_fiscais agora e
    # somente leitura (preenchido so pela analise automatica, nao editavel
    # por usuario), nao ha risco de o usuario "forjar" esse resultado.
    manual = normalizar_status_fila(getattr(nota, "status_fila_manual", None))
    if manual:
        return manual

    documento = normalizar_status_fila(getattr(nota, "status_documento", None))
    if documento in {"cancelada", "substituida"}:
        return documento

    if _contains_divergence_hint(observacao):
        return "divergente"
    if _contains_divergence_hint(alertas):
        return "divergente"
    if tem_alerta_fiscal:
        return "divergente"
    if alertas:
        return "correta"

    for field in ("status_csrf", "status_irrf", "status_inss", "status_base_calculo", "status_valor_liquido"):
        if _status_field_is_divergent(getattr(nota, field, None)):
            return "divergente"
    return "correta"


def normalizar_prioridade(value: str | None) -> str | None:
    text = _norm(value)
    if not text:
        return None
    if text in {"alta", "high"}:
        return "alta"
    if text in {"media", "medium"}:
        return "media"
    if text in {"baixa", "low"}:
        return "baixa"
    return text


def calcular_prioridade_fila(nota, status_fila_final: str) -> str:
    manual = normalizar_prioridade(getattr(nota, "prioridade_manual", None))
    if manual:
        return manual
    campos_ausentes = getattr(nota, "campos_ausentes_xml", None) or []
    alertas = getattr(nota, "alertas_fiscais", None)
    if status_fila_final == "divergente" and campos_ausentes:
        return "alta"
    if status_fila_final == "divergente" or bool(alertas):
        return "media"
    return "baixa"


def calcular_sla_operacional(entrada_fila: datetime | None, prioridade_fila: str | None) -> dict:
    prioridade = normalizar_prioridade(prioridade_fila) or "baixa"
    thresholds = SLA_THRESHOLDS.get(prioridade, SLA_THRESHOLDS["baixa"])
    if entrada_fila is None:
        return {
            "label": "Sem prazo",
            "tone": "neutral",
            "hours": None,
            "warn_hours": None,
            "danger_hours": None,
        }
    if entrada_fila.tzinfo is None:
        entrada_fila = entrada_fila.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    hours = max(0, int((now - entrada_fila.astimezone(timezone.utc)).total_seconds() // 3600))
    if hours >= thresholds["danger"]:
        tone = "danger"
    elif hours >= thresholds["warn"]:
        tone = "warn"
    else:
        tone = "ok"
    return {
        "label": f"{hours}h",
        "tone": tone,
        "hours": hours,
        "warn_hours": thresholds["warn"],
        "danger_hours": thresholds["danger"],
    }


def montar_campos_operacionais(nota, consulta_simples_api: str | None = None) -> dict:
    simples_xml = normalizar_simples_xml(
        getattr(nota, "simples_xml", None) or getattr(nota, "simples_nacional_xml", None)
    )
    status_simples = calcular_status_simples_nacional(simples_xml, consulta_simples_api)
    status_fila = calcular_status_fila(nota)
    divergente = status_fila in {"divergente", "cancelada", "substituida"}
    prioridade = calcular_prioridade_fila(nota, status_fila)
    entrada = getattr(nota, "entrada", None) or getattr(nota, "updated_at", None) or getattr(nota, "created_at", None)
    sla = calcular_sla_operacional(entrada, prioridade)
    return {
        "simples_xml": simples_xml,
        "simples_nacional": simples_xml,
        "consulta_simples_api": consulta_simples_api,
        "status_simples_nacional": status_simples,
        "incidencia_iss": getattr(nota, "incidencia_iss", None),
        "status_fila": status_fila,
        "status_fila_final": status_fila,
        "divergencia_fila_final": divergente,
        "divergencia_fila_label": "Com divergência" if divergente else "Sem divergência",
        "prioridade_fila": prioridade,
        "entrada_fila": entrada,
        "sla": sla,
    }


def aplicar_campos_operacionais(nota, consulta_simples_api: str | None = None):
    campos = montar_campos_operacionais(nota, consulta_simples_api=consulta_simples_api)
    for key, value in campos.items():
        if key in {"sla", "consulta_simples_api"}:
            # consulta_simples_api vem da tabela cnpj_cache (join externo), nao
            # deve ser persistido de volta na linha de `notas` via commit.
            set_committed_value(nota, key, value)
        else:
            setattr(nota, key, value)
    return nota
