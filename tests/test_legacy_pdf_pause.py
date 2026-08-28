from __future__ import annotations

from collections import deque

from backend.app.services import legacy_processing_service


def test_resposta_e2220_nao_e_exibida_como_erro_404(monkeypatch, capsys):
    legacy = legacy_processing_service._load_legacy_module(987654)

    class Resposta:
        status_code = 404
        headers = {"content-type": "application/json; charset=utf-8"}
        text = '{"StatusProcessamento":"NENHUM_DOCUMENTO_LOCALIZADO"}'

        def json(self):
            return {
                "StatusProcessamento": "NENHUM_DOCUMENTO_LOCALIZADO",
                "LoteDFe": [],
                "Erros": [{"Codigo": "E2220"}],
            }

    monkeypatch.setattr(legacy, "mtls_get", lambda *_args, **_kwargs: Resposta())

    resultado = legacy.requisicao_json_com_retry(object(), "https://adn.test/DFe/0", tentativas=1)

    saida = capsys.readouterr().out
    assert resultado["StatusProcessamento"] == "NENHUM_DOCUMENTO_LOCALIZADO"
    assert "ADN sem novos documentos | E2220" in saida
    assert "HTTP 404" not in saida


def test_motor_encerra_certificado_na_primeira_resposta_e2220(tmp_path):
    class Legacy:
        INDEX_FIELDS: list[str] = []
        ROOT_OUT = tmp_path
        DIR_RAW = tmp_path / "raw"

        def __init__(self):
            self.consultas = 0
            self.DIR_RAW.mkdir()

        def carregar_estado(self, _cnpj):
            return {"ultimo_nsu": 0}

        def consultar_dfe(self, _config, _nsu, lote=True):
            self.consultas += 1
            return {"StatusProcessamento": "NENHUM_DOCUMENTO_LOCALIZADO", "LoteDFe": []}

        def salvar_json(self, _path, _resultado):
            return None

    class Config:
        cnpj = "67224704000119"

    legacy = Legacy()
    resultado = legacy_processing_service._executar_baixa_empresa_compat(
        legacy,
        Config(),
        limite=100,
        pausa=0,
        inicio=0,
        gerar_pdf=True,
        baixar_pdf=True,
        consulta_lote_tamanho=1000,
    )

    assert legacy.consultas == 1
    assert resultado["consultas_realizadas"] == 1
    assert resultado["xmls_baixados"] == 0


def test_processa_pdfs_durante_pausa_sem_estourar_janela(monkeypatch):
    relogio = [0.0]
    chamadas: list[tuple[str, float]] = []

    monkeypatch.setattr(legacy_processing_service.time, "monotonic", lambda: relogio[0])
    monkeypatch.setattr(legacy_processing_service.time, "sleep", lambda segundos: relogio.__setitem__(0, relogio[0] + segundos))

    def baixar(_legacy, _config, chave, timeout=240):
        chamadas.append((chave, timeout))
        return chave == "pdf-ok"

    monkeypatch.setattr(legacy_processing_service, "_baixar_pdf_danfse_compat", baixar)
    fila = deque(["pdf-falha", "pdf-ok"])

    baixados = legacy_processing_service._processar_pdfs_durante_pausa(
        object(),
        object(),
        fila,
        pausa=5,
    )

    assert baixados == 1
    assert chamadas == [("pdf-falha", 5.0), ("pdf-ok", 3.0)]
    assert list(fila) == ["pdf-falha"]
    assert relogio[0] == 5.0


def test_pdf_com_falha_so_e_tentado_uma_vez_em_cada_pausa(monkeypatch):
    relogio = [0.0]
    chamadas: list[str] = []

    monkeypatch.setattr(legacy_processing_service.time, "monotonic", lambda: relogio[0])
    monkeypatch.setattr(legacy_processing_service.time, "sleep", lambda segundos: relogio.__setitem__(0, relogio[0] + segundos))
    monkeypatch.setattr(
        legacy_processing_service,
        "_baixar_pdf_danfse_compat",
        lambda _legacy, _config, chave, timeout=240: chamadas.append(chave) or False,
    )
    fila = deque(["pdf-pendente"])

    legacy_processing_service._processar_pdfs_durante_pausa(object(), object(), fila, pausa=8)
    assert chamadas == ["pdf-pendente"]
    assert list(fila) == ["pdf-pendente"]

    legacy_processing_service._processar_pdfs_durante_pausa(object(), object(), fila, pausa=8)
    assert chamadas == ["pdf-pendente", "pdf-pendente"]


def test_pausa_zero_nao_tenta_buscar_pdf(monkeypatch):
    monkeypatch.setattr(
        legacy_processing_service,
        "_baixar_pdf_danfse_compat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("nao deveria buscar")),
    )

    fila = deque(["pdf-pendente"])
    assert legacy_processing_service._processar_pdfs_durante_pausa(object(), object(), fila, pausa=0) == 0
    assert list(fila) == ["pdf-pendente"]
