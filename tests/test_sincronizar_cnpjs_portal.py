from backend.app.scripts.sincronizar_cnpjs_portal import _status_simples, montar_cache
from backend.app.services.cnpj_cache_service import RECEITA_FONTE


def test_monta_cache_receita_prioriza_mei():
    item = {
        "cnpj": "62069724000149",
        "cnae_fiscal_principal": "7112000",
        "opcao_simples": "S",
        "opcao_mei": "S",
    }
    result = montar_cache(item, "2026-08", 62)
    assert result["fonte"] == RECEITA_FONTE
    assert result["consulta_simples_api"] == "MEI"
    assert result["codigo_cnae"] == "7112000"
    assert result["json_resposta"]["competencia_base"] == "2026-08"


def test_status_simples():
    assert _status_simples({"opcao_simples": "S", "opcao_mei": "N"}) == "Optante S.N"
    assert _status_simples({"opcao_simples": "N", "opcao_mei": "N"}) == "Não optante"
    assert _status_simples({}) == "Não optante"
