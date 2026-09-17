from __future__ import annotations

import subprocess

import pytest

from backend.app.services.danfse_service import DanfseError, DanfseService


XML = b"<NFSe><infNFSe><nNFSe>12345</nNFSe></infNFSe></NFSe>"


@pytest.mark.parametrize("watermark", [None, "cancelada", "substituida"])
def test_danfse_gera_pdf_e_envia_carimbo(monkeypatch, watermark):
    comandos: list[list[str]] = []

    def fake_run(command, **kwargs):
        comandos.append(command)
        output_path = command[3]
        with open(output_path, "wb") as output:
            output.write(b"%PDF-1.7\n")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    pdf, filename = DanfseService().generate(XML, watermark=watermark)

    assert pdf.startswith(b"%PDF")
    assert filename == "DANFSe-12345.pdf"
    assert comandos
    assert comandos[0][-1] == watermark if watermark else len(comandos[0]) == 4


def test_danfse_trata_falha_ao_iniciar_php(monkeypatch):
    def fail_run(*_args, **_kwargs):
        raise PermissionError("acesso negado")

    monkeypatch.setattr(subprocess, "run", fail_run)

    with pytest.raises(DanfseError, match="Nao foi possivel executar o PHP"):
        DanfseService().generate(XML)
