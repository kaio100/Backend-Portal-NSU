from __future__ import annotations

from decimal import Decimal

from backend.app.services.retencoes_calculo_service import calcular_retencoes_esperadas, comparar_valor_fiscal
from backend.app.services.retencoes_regras_service import (
    normalizar_subitem_lc116,
    obter_regra_por_subitem,
    resolver_subitem_lc116,
)


def test_carrega_regras_planilha2_principais():
    assert obter_regra_por_subitem("1.01")["irrf"] == "SIM"
    assert obter_regra_por_subitem("1.01")["irrf_aliquota"] == Decimal("0.015")
    assert obter_regra_por_subitem("1.01")["pcc"] == "SIM"
    assert obter_regra_por_subitem("1.01")["inss"] == "NAO"

    assert obter_regra_por_subitem("1.03")["irrf"] == "NAO"
    assert obter_regra_por_subitem("1.03")["pcc"] == "SIM"
    assert obter_regra_por_subitem("3.02")["irrf_aliquota"] == Decimal("0.15")
    assert obter_regra_por_subitem("7.02")["inss"] == "SIM"
    assert obter_regra_por_subitem("10.05")["pcc"] == "NAO"
    assert obter_regra_por_subitem("11.02")["irrf_aliquota"] == Decimal("0.01")
    assert obter_regra_por_subitem("17.01")["pcc"] == "SIM"
    assert obter_regra_por_subitem("17.14")["irrf"] == "SIM"


def test_normaliza_subitem_de_ctribnac():
    assert resolver_subitem_lc116({"cTribNac": "170101"}) == "17.01"
    assert resolver_subitem_lc116({"cTribNac": "070201"}) == "7.02"
    assert normalizar_subitem_lc116("01.03") == "1.03"
    assert normalizar_subitem_lc116("1.3") == "1.03"


def test_calcula_irrf_csrf_inss_e_simples():
    regra_1701 = obter_regra_por_subitem("17.01")
    calc = calcular_retencoes_esperadas(
        {
            "valor_servico": "1000.00",
            "valor_base_calculo": "1000.00",
            "valor_irrf": "15.00",
            "valor_csrf": "46.50",
            "valor_inss": "0.00",
            "valor_liquido": "938.50",
            "valor_pis": "6.50",
            "valor_cofins": "30.00",
            "valor_csll": "10.00",
        },
        regra_1701,
    )
    assert calc["irrf_calculado"] == Decimal("15.00")
    assert calc["pis_calculado"] == Decimal("6.50")
    assert calc["cofins_calculado"] == Decimal("30.00")
    assert calc["csll_calculado"] == Decimal("10.00")
    assert calc["csrf_calculado"] == Decimal("46.50")
    assert calc["status_irrf"] == "Correto"
    assert calc["status_csrf"] == "Correto"
    assert calc["status_inss"] == "Nao se aplica"

    simples = calcular_retencoes_esperadas(
        {"valor_servico": "1000.00", "valor_base_calculo": "1000.00", "simples_xml": "MEI"},
        regra_1701,
    )
    assert simples["irrf_calculado"] == Decimal("0.00")
    assert simples["csrf_calculado"] == Decimal("0.00")

    inss = calcular_retencoes_esperadas(
        {"valor_servico": "1000.00", "valor_base_calculo": "1000.00", "simples_xml": "MEI"},
        obter_regra_por_subitem("7.02"),
    )
    assert inss["inss_calculado"] == Decimal("110.00")


def test_comparar_valor_fiscal_status():
    assert comparar_valor_fiscal("15.00", Decimal("15.00"), "IRRF") == "Correto"
    assert comparar_valor_fiscal("0.00", Decimal("15.00"), "IRRF") == "Divergente - nao retido"
    assert comparar_valor_fiscal("10.00", Decimal("0.00"), "IRRF") == "Divergente - retido indevido"
    assert comparar_valor_fiscal("0.00", None, "IRRF") == "Depende de analise"
