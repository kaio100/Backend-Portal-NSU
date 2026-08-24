from __future__ import annotations

from backend.app.services import legacy_processing_service


def test_consulta_adn_nao_imprime_url_parametros_ou_cnpj(monkeypatch, capsys):
    legacy = legacy_processing_service._load_legacy_module(123456)

    class Resposta:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"StatusProcessamento":"OK","LoteDFe":[]}'

        def json(self):
            return {"StatusProcessamento": "OK", "LoteDFe": []}

    monkeypatch.setattr(legacy, "mtls_get", lambda *_args, **_kwargs: Resposta())
    cnpj = "00603139000120"
    url = "https://adn.test/contribuintes/DFe/123"

    legacy.requisicao_json_com_retry(
        object(),
        url,
        params={"cnpjConsulta": cnpj, "lote": "true"},
        tentativas=1,
    )

    output = capsys.readouterr().out
    assert "HTTP 200" in output
    assert "Parametros da consulta ADN omitidos" in output
    assert cnpj not in output
    assert url not in output


def test_falha_adn_nao_imprime_corpo_da_resposta(monkeypatch, capsys):
    legacy = legacy_processing_service._load_legacy_module(123457)

    class Resposta:
        status_code = 500
        headers = {"content-type": "text/plain"}
        text = "senha=nao-pode-aparecer"

        def json(self):
            raise ValueError

    monkeypatch.setattr(legacy, "mtls_get", lambda *_args, **_kwargs: Resposta())

    try:
        legacy.requisicao_json_com_retry(object(), "https://adn.test", tentativas=1)
    except RuntimeError:
        pass

    assert "nao-pode-aparecer" not in capsys.readouterr().out
