from types import SimpleNamespace

from backend.app.services import notas_service
from backend.app.services.legacy_ingestion_service import parse_xml_resumo_bytes


def test_parser_separa_cpf_prestador_e_cnpj_tomador():
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <NFSe>
      <infNFSe Id="NFS52119091100030266151884000000000241726031697287574">
        <emit><CPF>30266151884</CPF><xNome>LEANDRO AKIRA MATSUOKA</xNome></emit>
        <DPS><infDPS>
          <prest><CPF>30266151884</CPF></prest>
          <toma><CNPJ>46835429000108</CNPJ><xNome>HAMOA JATAI</xNome></toma>
          <valores><vServ>51.96</vServ><vLiq>49.36</vLiq></valores>
        </infDPS></DPS>
      </infNFSe>
    </NFSe>"""
    result = parse_xml_resumo_bytes(xml, "2417.xml")
    assert result["prestador_cnpj"] == "30266151884"
    assert result["prestador_nome"] == "LEANDRO AKIRA MATSUOKA"
    assert result["tomador_cnpj"] == "46835429000108"
    assert result["tomador_nome"] == "HAMOA JATAI"


def test_parser_nao_confunde_cnpj_tomador_com_prestador_sem_documento():
    xml = b"""<NFSe><prest><xNome>PRESTADOR</xNome></prest>
    <toma><CNPJ>46835429000108</CNPJ><xNome>TOMADOR</xNome></toma></NFSe>"""
    result = parse_xml_resumo_bytes(xml, "sem-chave.xml")
    assert result["prestador_cnpj"] == ""
    assert result["tomador_cnpj"] == "46835429000108"


def test_cpf_prestador_e_nao_optante_sem_consultar_cache(monkeypatch):
    nota = SimpleNamespace(
        id=2417,
        empresa_id=69,
        empresa=SimpleNamespace(cnpj="46835429000108"),
        prestador_cnpj="30266151884",
        tomador_cnpj="46835429000108",
    )
    monkeypatch.setattr(
        notas_service.cnpj_cache_service,
        "get_caches_validos",
        lambda _db, documentos: {} if not documentos else (_ for _ in ()).throw(
            AssertionError("CPF nao deve consultar cache")
        ),
    )
    assert notas_service._consultas_simples_api_lote(object(), [nota]) == {2417: "Não optante"}
