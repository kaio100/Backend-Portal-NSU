from __future__ import annotations

import base64
import gzip

import adn_nfse_downloader as legacy


def _documento(nsu: str, data_emissao: str) -> dict:
    xml = f"<NFSe><nNFSe>{nsu}</nNFSe><DataEmissao>{data_emissao}</DataEmissao></NFSe>"
    return {
        "NSU": nsu,
        "ChaveAcesso": f"chave-{nsu}",
        "TipoDocumento": "NFSE",
        "ArquivoXml": base64.b64encode(gzip.compress(xml.encode())).decode(),
    }


def _configurar_saida(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(legacy, "DIR_JSON", tmp_path / "json")
    monkeypatch.setattr(legacy, "DIR_XML", tmp_path / "xml")
    monkeypatch.setattr(legacy, "INDEX_UNICO_FILE", tmp_path / "index.csv")
    monkeypatch.setattr(legacy, "OCORRENCIAS_FILE", tmp_path / "ocorrencias.csv")
    legacy.DIR_JSON.mkdir()
    legacy.DIR_XML.mkdir()


def test_descarta_documento_anterior_ao_corte_sem_impedir_avanco_do_nsu(monkeypatch, tmp_path):
    _configurar_saida(monkeypatch, tmp_path)
    monkeypatch.setenv("NOTAS_DATA_CORTE", "2026-01-01")

    nsu, persistido = legacy.processar_documento(_documento("15", "2025-12-31"))

    assert (nsu, persistido) == (15, False)
    assert list(tmp_path.rglob("*.*")) == []


def test_persiste_documento_a_partir_do_corte(monkeypatch, tmp_path):
    _configurar_saida(monkeypatch, tmp_path)
    monkeypatch.setenv("NOTAS_DATA_CORTE", "2026-01-01")

    nsu, persistido = legacy.processar_documento(_documento("16", "2026-01-01"))

    assert (nsu, persistido) == (16, True)
    assert len(list((tmp_path / "json").glob("*.json"))) == 1
    assert len(list((tmp_path / "xml").glob("*.xml"))) == 1
