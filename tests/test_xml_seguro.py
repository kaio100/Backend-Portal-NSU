"""SEC-B314: XML de terceiros (upload do DANFSe e saida do ADN) sem entidades.

Um XML com declaracao de entidades (ex.: "billion laughs") deve ser tratado
como XML invalido, nao expandido nem transformado em erro 500.
"""

from __future__ import annotations

import pytest

from backend.app.services import legacy_ingestion_service
from backend.app.services.danfse_service import DanfseError, _numero_nfse
from backend.app.services.nfse_xml_parser import extrair_dados_nfse

XML_COM_ENTIDADES = b"""<?xml version="1.0"?>
<!DOCTYPE NFSe [
  <!ENTITY a "aaaaaaaaaa">
  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
]>
<NFSe><infNFSe><nNFSe>&b;</nNFSe></infNFSe></NFSe>"""


def test_danfse_recusa_xml_com_entidades():
    with pytest.raises(DanfseError, match="XML invalido"):
        _numero_nfse(XML_COM_ENTIDADES)


def test_danfse_continua_lendo_nfse_normal():
    assert _numero_nfse(b"<NFSe><infNFSe><nNFSe>123</nNFSe></infNFSe></NFSe>") == "123"


def test_ingestao_trata_xml_com_entidades_como_ilegivel():
    resumo = legacy_ingestion_service.parse_xml_resumo_bytes(XML_COM_ENTIDADES, "nota.xml")
    # Mesmo caminho de um XML malformado: so a chave pelo nome do arquivo.
    assert set(resumo) == {"chave"}


def test_parser_do_pdf_recusa_xml_com_entidades(tmp_path):
    caminho = tmp_path / "nota.xml"
    caminho.write_bytes(XML_COM_ENTIDADES)
    with pytest.raises(ValueError):
        extrair_dados_nfse(caminho)
