from __future__ import annotations

from decimal import Decimal

from types import SimpleNamespace

from backend.app.services.retencoes_calculo_service import calcular_liquido_com_retencoes_salvas, calcular_retencoes_esperadas, comparar_valor_fiscal
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
    assert obter_regra_por_subitem("7.04")["irrf_aliquota"] == Decimal("0.01")
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


def test_subitem_704_calcula_irrf_exclusivamente_a_um_por_cento():
    regra = obter_regra_por_subitem("7.04")
    calculo = calcular_retencoes_esperadas(
        {
            "valor_servico": "1000.00",
            "valor_base_calculo": "1000.00",
            "valor_irrf": "10.00",
        },
        regra,
        subitem_lc116="7.04",
    )

    assert regra["irrf_aliquota"] == Decimal("0.01")
    assert calculo["irrf_calculado"] == Decimal("10.00")
    assert calculo["status_irrf"] == "Correto"


def test_comparar_valor_fiscal_status():
    assert comparar_valor_fiscal("15.00", Decimal("15.00"), "IRRF") == "Correto"
    assert comparar_valor_fiscal("0.00", Decimal("15.00"), "IRRF") == "Divergente - nao retido"
    assert comparar_valor_fiscal("10.00", Decimal("0.00"), "IRRF") == "Divergente - retido indevido"
    assert comparar_valor_fiscal("0.00", None, "IRRF") == "Depende de analise"


def test_calculo_pcc_com_base_zero_permanece_decimal():
    calculo = calcular_retencoes_esperadas(
        {"valor_servico": "0", "valor_base_calculo": "0"},
        obter_regra_por_subitem("17.01"),
    )

    assert calculo["csrf_calculado"] == Decimal("0.00")


def test_liquido_correto_deduz_imposto_calculado_nao_informado_na_nota():
    calculo = calcular_retencoes_esperadas(
        {
            "valor_servico": "4920.00",
            "valor_base_calculo": "4920.00",
            "valor_irrf": "0.00",
            "valor_iss": "246.00",
            "iss_retido": True,
            "aliquota_iss": "5.00",
            "valor_liquido": "4674.00",
        },
        regra={"irrf": "SIM", "irrf_aliquota": "0.015", "pcc": "NAO", "inss": "NAO", "subitem": "17.14"},
        subitem_lc116="17.14",
    )

    assert calculo["irrf_calculado"] == Decimal("73.80")
    assert calculo["iss_calculado"] == Decimal("246.00")
    assert calculo["valor_liquido_calculado"] == Decimal("4600.20")
    assert calculo["status_valor_liquido"] == "Divergente"
    assert "Valor liquido esperado R$ 4600.20, informado R$ 4674.00." in calculo["alertas_fiscais"]


def test_liquido_correto_deduz_irrf_do_cenario_do_comparativo():
    calculo = calcular_retencoes_esperadas(
        {
            "valor_servico": "2170.00",
            "valor_base_calculo": "2170.00",
            "valor_irrf": "0.00",
            "valor_iss": "108.50",
            "iss_retido": True,
            "aliquota_iss": "5.00",
            "valor_liquido": "2061.50",
        },
        regra={"irrf": "SIM", "irrf_aliquota": "0.015", "pcc": "NAO", "inss": "NAO", "subitem": "11.01"},
        subitem_lc116="11.01",
    )

    assert calculo["irrf_calculado"] == Decimal("32.55")
    assert calculo["iss_calculado"] == Decimal("108.50")
    assert calculo["valor_liquido_calculado"] == Decimal("2028.95")
    assert calculo["status_valor_liquido"] == "Divergente"


def test_inss_usa_base_especifica_declarada_na_descricao_da_nota():
    calculo = calcular_retencoes_esperadas(
        {
            "valor_servico": "14367.60",
            "valor_base_calculo": "14367.60",
            "valor_inss": "790.22",
            "valor_iss": "288.79",
            "valor_liquido": "13288.59",
            "iss_retido": True,
            "aliquota_iss": "2.01",
            "simples_xml": "Optante S.N",
            "descricao_servico_detalhada": (
                "A BASE DE CÁLCULO DE RETENÇÃO DO INSS É R$ 7.183,80 X 11% = 790,22"
            ),
        },
        regra={
            "inss": "SIM",
            "inss_optante_simples_retem": True,
            "irrf": "NAO",
            "pcc": "NAO",
            "subitem": "7.02",
        },
        subitem_lc116="7.02",
    )

    assert calculo["base_calculo_inss"] == Decimal("7183.80")
    assert calculo["inss_calculado"] == Decimal("790.22")
    assert calculo["status_inss"] == "Correto"
    assert calculo["valor_liquido_calculado"] == Decimal("13288.59")
    assert calculo["status_valor_liquido"] == "Correto"


def test_liquido_salvo_deduz_irrf_calculado_nao_informado():
    nota = SimpleNamespace(
        valor_servico="10096.00", irrf="0", irrf_calculado="151.44",
        inss="0", inss_calculado="0", csrf="0", csrf_calculado="0",
        iss_retido=False, valor_iss_retido="0", iss="0", iss_calculado="0",
        valor_outras_retencoes="0", valor_desconto_incondicionado="0", valor_desconto_condicionado="0",
    )
    assert calcular_liquido_com_retencoes_salvas(nota) == Decimal("9944.56")


def test_liquido_salvo_deduz_csrf_informado_e_irrf_calculado():
    nota = SimpleNamespace(
        valor_servico="14160.00", irrf="0", irrf_calculado="212.40",
        inss="0", inss_calculado="0", csrf="516.84", csrf_calculado="0",
        iss_retido=False, valor_iss_retido="0", iss="0", iss_calculado="0",
        valor_outras_retencoes="0", valor_desconto_incondicionado="0", valor_desconto_condicionado="0",
    )
    assert calcular_liquido_com_retencoes_salvas(nota) == Decimal("13430.76")


def test_planilha_ausente_nao_fica_cacheada_como_vazia(monkeypatch, tmp_path):
    # Regressao: com lru_cache, uma falha de leitura na inicializacao do
    # container deixava todas as notas do deploy com "Regra fiscal nao
    # encontrada" mesmo com a regra na planilha.
    from backend.app.services import retencoes_regras_service as svc

    monkeypatch.setattr(svc, "_REGRAS_CACHE", None)
    monkeypatch.setattr(svc, "REGRAS_XLSX_PATH", tmp_path / "nao_existe.xlsx")
    assert svc.carregar_regras_retencao() == {}
    assert svc._REGRAS_CACHE is None  # nada cacheado

    # Planilha volta a estar disponivel: proxima chamada carrega de verdade.
    monkeypatch.setattr(svc, "REGRAS_XLSX_PATH", svc.PROJECT_ROOT / "RETENCOES_REGRAS.xlsx")
    regras = svc.carregar_regras_retencao()
    assert "17.02" in regras and "7.10" in regras
    assert svc._REGRAS_CACHE is regras


def test_liquido_com_retencoes_salvas_abate_pis_cofins_csll_por_componente():
    # Regressao: o backfill de startup tratava o CSRF como bloco unico e
    # divergia da analise fiscal (componente a componente), reescrevendo o
    # valor_liquido_correto a cada deploy sem atualizar os alertas.
    from decimal import Decimal
    from types import SimpleNamespace
    from backend.app.services.retencoes_calculo_service import calcular_liquido_com_retencoes_salvas

    nota = SimpleNamespace(
        valor_servico=Decimal("550.66"), irrf=None, irrf_calculado=Decimal("8.26"),
        inss=None, inss_calculado=Decimal("0"),
        valor_pis=Decimal("9.09"), valor_cofins=Decimal("41.85"), valor_csll=None,
        pis_calculado=Decimal("3.58"), cofins_calculado=Decimal("16.52"), csll_calculado=Decimal("5.51"),
        csrf=Decimal("50.94"), csrf_calculado=Decimal("25.61"), iss_retido=False,
    )
    # 550.66 - 8.26 - max(9.09,3.58) - max(41.85,16.52) - max(0,5.51) = 485.95
    assert calcular_liquido_com_retencoes_salvas(nota) == Decimal("485.95")

    antiga = SimpleNamespace(valor_servico=Decimal("100"), csrf=Decimal("4.65"), csrf_calculado=Decimal("0"), iss_retido=False)
    assert calcular_liquido_com_retencoes_salvas(antiga) == Decimal("95.35")


def test_backfill_de_startup_nao_toca_nota_conferida(monkeypatch):
    from backend.app.services import valor_liquido_backfill_service as svc
    from backend.app.db.session import SessionLocal, init_db
    from backend.app.db.models import Empresa, Nota
    from decimal import Decimal

    init_db()
    with SessionLocal() as db:
        db.query(Nota).delete(); db.query(Empresa).delete(); db.commit()
        empresa = Empresa(nome="Backfill LTDA", cnpj="22333444000157", ambiente="producao", ativo=True, grupo="planning_hub")
        db.add(empresa); db.flush()
        conferida = Nota(empresa_id=empresa.id, chave="C" * 44, valor_servico=Decimal("100"), valor_liquido=Decimal("100"), valor_liquido_correto=Decimal("77.00"), conferencia_status="ok", responsavel="Revisor")
        pendente = Nota(empresa_id=empresa.id, chave="P" * 44, valor_servico=Decimal("100"), valor_liquido=Decimal("100"), valor_liquido_correto=Decimal("77.00"), conferencia_status="pendente")
        db.add_all([conferida, pendente]); db.commit()
        ids = (conferida.id, pendente.id)

    svc.recalcular_notas_salvas()
    with SessionLocal() as db:
        assert db.get(Nota, ids[0]).valor_liquido_correto == Decimal("77.00")   # preservada
        assert db.get(Nota, ids[1]).valor_liquido_correto == Decimal("100.00")  # recalculada
        db.query(Nota).delete(); db.query(Empresa).delete(); db.commit()
