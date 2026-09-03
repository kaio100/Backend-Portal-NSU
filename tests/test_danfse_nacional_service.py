from pathlib import Path

import pytest

from backend.app.services.danfse_service import DanfseError, DanfseService


def test_danfse_rejeita_xml_invalido():
    with pytest.raises(DanfseError, match="XML invalido"):
        DanfseService().generate(b"<NFSe>")


def test_danfse_rejeita_documento_que_nao_e_nfse():
    with pytest.raises(DanfseError, match="nao e uma NFS-e"):
        DanfseService().generate(b"<root />")


def test_danfse_rejeita_xml_acima_do_limite(monkeypatch):
    monkeypatch.setattr("backend.app.services.danfse_service.settings.danfse_xml_max_bytes", 4)
    with pytest.raises(DanfseError, match="excede o limite"):
        DanfseService().generate(b"<NFSe />")
