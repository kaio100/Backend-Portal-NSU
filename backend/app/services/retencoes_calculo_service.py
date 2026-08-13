from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any
import unicodedata


TOLERANCIA = Decimal("0.01")
MONEY = Decimal("0.01")


def parse_decimal_xml(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def calcular_liquido_com_retencoes_salvas(nota: Any) -> Decimal:
    """Recalcula o liquido usando os valores informados e esperados persistidos."""
    def decimal_campo(*nomes: str) -> Decimal:
        for nome in nomes:
            valor = parse_decimal_xml(getattr(nota, nome, None))
            if valor is not None:
                return valor
        return Decimal("0")

    def maior(informado: Decimal, calculado: Decimal) -> Decimal:
        return max(informado, calculado)

    valor_servico = decimal_campo("valor_servico", "valor_base")
    irrf = maior(decimal_campo("irrf"), decimal_campo("irrf_calculado"))
    inss = maior(decimal_campo("inss"), decimal_campo("inss_calculado"))
    csrf = maior(decimal_campo("csrf", "valor_csrf"), decimal_campo("csrf_calculado"))

    iss = Decimal("0")
    if bool(getattr(nota, "iss_retido", False)) or decimal_campo("valor_iss_retido") > 0:
        iss_informado = decimal_campo("valor_iss_retido", "iss")
        iss = maior(iss_informado, decimal_campo("iss_calculado"))

    return money(
        valor_servico
        - irrf
        - inss
        - csrf
        - iss
        - decimal_campo("valor_outras_retencoes")
        - decimal_campo("valor_desconto_incondicionado")
        - decimal_campo("valor_desconto_condicionado")
    ) or Decimal("0.00")


def comparar_valor_fiscal(informado: Any, calculado: Any, nome: str = "") -> str:
    inf = money(parse_decimal_xml(informado) or Decimal("0"))
    calc = money(parse_decimal_xml(calculado)) if calculado is not None else None
    if calc is None:
        return "Depende de analise"
    if calc == 0 and inf == 0:
        return "Nao se aplica"
    if calc == 0 and inf and inf > 0:
        return "Divergente - retido indevido"
    if calc > 0 and inf == 0:
        return "Divergente - nao retido"
    if abs(inf - calc) <= TOLERANCIA:
        return "Correto"
    return "Divergente"


def _flag(value: str | None) -> str:
    return (value or "NAO").strip().upper()


def _is_simples(value: str | None) -> bool:
    return (value or "").strip() in {"MEI", "Optante S.N", "Simples Nacional"}


def extrair_base_calculo_inss(descricao: Any) -> Decimal | None:
    """Extrai uma base de INSS declarada explicitamente na descricao da NFS-e."""
    if not descricao:
        return None
    texto = unicodedata.normalize("NFKD", str(descricao))
    texto = "".join(char for char in texto if not unicodedata.combining(char)).upper()
    match = re.search(
        r"BASE\s+DE\s+CALCULO(?:\s+DE\s+RETENCAO)?\s+(?:DO|DE)\s+INSS"
        r"\s*(?:E|:|=)?\s*(?:R\$\s*)?(\d[\d.,]*)",
        texto,
    )
    return money(parse_decimal_xml(match.group(1))) if match else None


SUBITEM_NAO_IDENTIFICADO_MSG = (
    "Subitem LC116 nao identificado no XML. "
    "Campos pesquisados: cTribNac, cTribMun, itemListaServico, codigoServico."
)


def calcular_retencoes_esperadas(
    dados: dict[str, Any],
    regra: dict[str, Any] | None,
    subitem_lc116: str | None = None,
) -> dict[str, Any]:
    base = parse_decimal_xml(dados.get("valor_base_calculo")) or parse_decimal_xml(dados.get("valor_servico")) or Decimal("0")
    valor_servico = parse_decimal_xml(dados.get("valor_servico")) or base
    base_inss = (
        parse_decimal_xml(dados.get("base_calculo_inss"))
        or extrair_base_calculo_inss(dados.get("descricao_servico_detalhada"))
        or base
    )
    simples = _is_simples(dados.get("simples_nacional") or dados.get("simples_xml"))
    regra = regra or {}
    alertas: list[str] = []

    # Compatibilidade: chamadas antigas passavam so a regra, sem o subitem.
    # Nesse caso, se ha uma regra valida, consideramos o subitem dela como identificado.
    if subitem_lc116 is None and regra:
        subitem_lc116 = regra.get("subitem")

    irrf_flag = _flag(regra.get("irrf"))
    pcc_flag = _flag(regra.get("pcc"))
    inss_flag = _flag(regra.get("inss"))
    aliquota_irrf = parse_decimal_xml(regra.get("irrf_aliquota")) or Decimal("0")

    if not subitem_lc116:
        alertas.append(SUBITEM_NAO_IDENTIFICADO_MSG)
    elif not regra:
        alertas.append(f"Regra fiscal nao encontrada para subitem LC116 {subitem_lc116}.")

    if irrf_flag == "DEPENDE":
        irrf_calculado = None
        status_irrf = "Depende de analise"
    elif irrf_flag == "SIM" and not simples:
        irrf_calculado = money(base * aliquota_irrf)
        status_irrf = comparar_valor_fiscal(dados.get("valor_irrf"), irrf_calculado, "IRRF")
    else:
        irrf_calculado = Decimal("0.00")
        status_irrf = comparar_valor_fiscal(dados.get("valor_irrf"), irrf_calculado, "IRRF")

    if pcc_flag == "DEPENDE":
        pis_calculado = cofins_calculado = csll_calculado = csrf_calculado = None
        status_csrf = "Depende de analise"
    elif pcc_flag == "SIM" and not simples:
        pis_calculado = money(base * Decimal("0.0065"))
        cofins_calculado = money(base * Decimal("0.03"))
        csll_calculado = money(base * Decimal("0.01"))
        csrf_calculado = money(
            (pis_calculado or Decimal("0"))
            + (cofins_calculado or Decimal("0"))
            + (csll_calculado or Decimal("0"))
        )
        status_csrf = comparar_valor_fiscal(dados.get("valor_csrf"), csrf_calculado, "CSRF")
    else:
        pis_calculado = cofins_calculado = csll_calculado = csrf_calculado = Decimal("0.00")
        status_csrf = comparar_valor_fiscal(dados.get("valor_csrf"), csrf_calculado, "CSRF")

    if inss_flag == "DEPENDE":
        inss_calculado = None
        status_inss = "Depende de analise"
    elif inss_flag == "SIM" and (not simples or regra.get("inss_optante_simples_retem")):
        inss_calculado = money(base_inss * Decimal("0.11"))
        status_inss = comparar_valor_fiscal(dados.get("valor_inss"), inss_calculado, "INSS")
    else:
        inss_calculado = Decimal("0.00")
        status_inss = comparar_valor_fiscal(dados.get("valor_inss"), inss_calculado, "INSS")

    valor_pis = parse_decimal_xml(dados.get("valor_pis")) or Decimal("0")
    valor_cofins = parse_decimal_xml(dados.get("valor_cofins")) or Decimal("0")
    valor_csll = parse_decimal_xml(dados.get("valor_csll")) or Decimal("0")
    valor_irrf = parse_decimal_xml(dados.get("valor_irrf")) or Decimal("0")
    valor_inss = parse_decimal_xml(dados.get("valor_inss")) or Decimal("0")
    valor_iss_retido = parse_decimal_xml(dados.get("valor_iss_retido")) or Decimal("0")
    valor_iss_apurado = parse_decimal_xml(dados.get("valor_iss")) or Decimal("0")
    outras = parse_decimal_xml(dados.get("valor_outras_retencoes")) or Decimal("0")
    desc_inc = parse_decimal_xml(dados.get("valor_desconto_incondicionado")) or Decimal("0")
    desc_cond = parse_decimal_xml(dados.get("valor_desconto_condicionado")) or Decimal("0")
    iss_retido = bool(dados.get("iss_retido")) or valor_iss_retido > 0

    if iss_retido:
        # Com retencao (tpRetISSQN=2 ou 3), a aliquota (pAliq/pAliqAplic) e
        # obrigatoria no XML para que o valor retido seja calculado.
        aliquota_iss = parse_decimal_xml(dados.get("aliquota_iss"))
        if aliquota_iss is not None and aliquota_iss > 1:
            aliquota_iss = aliquota_iss / Decimal("100")
        iss_calculado = money(base * aliquota_iss) if aliquota_iss is not None else None
        status_iss = comparar_valor_fiscal(dados.get("valor_iss"), iss_calculado, "ISS") if iss_calculado is not None else "Depende de analise"
    else:
        # Sem retencao (tpRetISSQN=1), a aliquota normalmente nao e informada
        # ou vem zerada no XML (nao deve ser preenchida, sob pena de rejeicao
        # no padrao NFS-e Nacional) — nao ha base para calcular um ISS
        # esperado a partir dela, entao nao comparamos/preenchemos o ISS.
        iss_calculado = None
        status_iss = "Nao Retido"

    # O liquido correto deve considerar tanto o que ja foi efetivamente retido
    # na nota quanto uma retencao devida identificada pelo sistema e omitida no
    # XML. Usar apenas os valores informados fazia, por exemplo, um IRRF devido
    # e nao retido aparecer no comparativo sem reduzir o liquido calculado.
    #
    # O maior valor evita dois erros: nao soma o mesmo tributo duas vezes quando
    # informado e calculado coincidem, e preserva uma retencao informada acima
    # do esperado (ela ainda afeta o valor efetivamente recebido da nota).
    def valor_a_abater(informado: Decimal, calculado: Decimal | None) -> Decimal:
        return max(informado, calculado) if calculado is not None else informado

    irrf_a_abater = valor_a_abater(valor_irrf, irrf_calculado)
    inss_a_abater = valor_a_abater(valor_inss, inss_calculado)
    pis_a_abater = valor_a_abater(valor_pis, pis_calculado)
    cofins_a_abater = valor_a_abater(valor_cofins, cofins_calculado)
    csll_a_abater = valor_a_abater(valor_csll, csll_calculado)

    # Quando o ISS e retido pelo tomador mas o XML nao traz um campo especifico
    # com o valor retido (ex.: NFS-e Nacional so tem vISSQN + tpRetISSQN), usa
    # o ISSQN apurado como valor informado a abater.
    valor_iss_informado = valor_iss_retido if valor_iss_retido > 0 else valor_iss_apurado
    iss_a_abater = valor_a_abater(valor_iss_informado, iss_calculado) if iss_retido else Decimal("0")
    liquido_calculado = money(
        valor_servico
        - irrf_a_abater
        - inss_a_abater
        - pis_a_abater
        - cofins_a_abater
        - csll_a_abater
        - iss_a_abater
        - outras
        - desc_inc
        - desc_cond
    )
    status_liquido = comparar_valor_fiscal(dados.get("valor_liquido"), liquido_calculado, "Valor Liquido") if dados.get("valor_liquido") else "Nao informado"

    for nome, informado, calculado, status in (
        ("IRRF", dados.get("valor_irrf"), irrf_calculado, status_irrf),
        ("CSRF", dados.get("valor_csrf"), csrf_calculado, status_csrf),
        ("INSS", dados.get("valor_inss"), inss_calculado, status_inss),
        ("ISS", dados.get("valor_iss"), iss_calculado, status_iss),
    ):
        if status and status.startswith("Divergente"):
            alertas.append(f"{nome} esperado R$ {money(parse_decimal_xml(calculado) or Decimal('0'))}, informado R$ {money(parse_decimal_xml(informado) or Decimal('0'))}.")
        elif status == "Depende de analise":
            alertas.append(f"{nome} depende de analise.")
    if status_liquido.startswith("Divergente"):
        alertas.append(f"Valor liquido esperado R$ {liquido_calculado}, informado R$ {money(parse_decimal_xml(dados.get('valor_liquido')) or Decimal('0'))}.")

    return {
        "irrf_calculado": irrf_calculado,
        "pis_calculado": pis_calculado,
        "cofins_calculado": cofins_calculado,
        "csll_calculado": csll_calculado,
        "csrf_calculado": csrf_calculado,
        "inss_calculado": inss_calculado,
        "base_calculo_inss": money(base_inss),
        "iss_calculado": iss_calculado,
        "valor_liquido_calculado": liquido_calculado,
        "status_irrf": status_irrf,
        "status_csrf": status_csrf,
        "status_inss": status_inss,
        "status_iss": status_iss,
        "status_valor_liquido": status_liquido,
        "alertas_fiscais": "\n".join(alertas),
    }
