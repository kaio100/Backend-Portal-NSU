from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.services.nfse_xml_parser import extrair_dados_nfse


DOWNLOADS = Path.home() / "Downloads"
NOTA_18_XML = DOWNLOADS / "CNS_PARK_ESTACIONAMENTO_LTDA NFS-e 18.xml"
NOTA_22_XML = DOWNLOADS / "CNS_PARK_ESTACIONAMENTO_LTDA NFS-e 22.xml"


def _require(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"Arquivo de referencia nao encontrado: {path}")
    return path


def test_parser_nota_18_cns_park() -> None:
    dados = extrair_dados_nfse(_require(NOTA_18_XML))

    assert dados["numero_nfse"] == "18"
    assert dados["competencia"] == "17/01/2026"
    assert dados["emit_nome"] == "CNS PARK ESTACIONAMENTO LTDA"
    assert dados["emit_cnpj"] == "21.960.475/0001-08"
    assert dados["tomador_identificado"] is False
    assert dados["valor_servico"] == "14016.00"
    assert dados["desconto_incondicionado"] == "74.00"
    assert dados["bc_issqn"] == "13942.00"
    assert dados["aliquota_aplicada"] == "2.50"
    assert dados["issqn_apurado"] == "348.55"
    assert dados["valor_liquido_nfse"] == "13942.00"
    assert dados["totais_federais"] == "0.00"
    assert dados["totais_estaduais"] == "0.00"
    assert dados["totais_municipais"] == "2.50"
    assert "11.01.01" in dados["codigo_tributacao_nacional"]
    assert "SERVIÇO DE ESTACIONAMENTO" in dados["descricao_servico"]
    assert "São José de Ribamar" in dados["local_prestacao"]
    assert "São José de Ribamar" in dados["municipio_incidencia_issqn"]


def test_parser_nota_22_cns_park() -> None:
    dados = extrair_dados_nfse(_require(NOTA_22_XML))

    assert dados["numero_nfse"] == "22"
    assert dados["competencia"] == "21/01/2026"
    assert dados["emit_nome"] == "CNS PARK ESTACIONAMENTO LTDA"
    assert dados["tomador_identificado"] is False
    assert dados["valor_servico"] == "11229.00"
    assert dados["desconto_incondicionado"] == "370.00"
    assert dados["bc_issqn"] == "10859.00"
    assert dados["aliquota_aplicada"] == "2.50"
    assert dados["issqn_apurado"] == "271.48"
    assert dados["valor_liquido_nfse"] == "10859.00"
    assert dados["nbs"] == "106043000"
    assert dados["totais_municipais"] == "2.50"


def test_parser_tomador_identificado_nao_usa_prestador_como_fallback(tmp_path: Path) -> None:
    xml = tmp_path / "tomador.xml"
    xml.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">
  <infNFSe Id="NFS123">
    <xLocEmi>Hidrolandia</xLocEmi>
    <xLocPrestacao>Hidrolandia</xLocPrestacao>
    <nNFSe>1</nNFSe>
    <dhProc>2026-01-01T10:00:00-03:00</dhProc>
    <emit><CNPJ>11111111000191</CNPJ><xNome>PRESTADOR LTDA</xNome></emit>
    <DPS><infDPS>
      <serie>1</serie><nDPS>1</nDPS><dCompet>2026-01-01</dCompet><dhEmi>2026-01-01T10:00:00-03:00</dhEmi>
      <prest><CNPJ>11111111000191</CNPJ></prest>
      <toma>
        <CNPJ>22222222000182</CNPJ>
        <xNome>TOMADOR REAL LTDA</xNome>
        <end><endNac><cMun>5201405</cMun><UF>GO</UF><CEP>74905730</CEP></endNac><xLgr>Rua Um</xLgr><nro>10</nro></end>
      </toma>
      <serv><cServ><cTribNac>170101</cTribNac><xDescServ>Servico</xDescServ></cServ></serv>
      <valores><vServPrest><vServ>100.00</vServ></vServPrest></valores>
    </infDPS></DPS>
    <valores><vBC>100.00</vBC><pAliqAplic>2.00</pAliqAplic><vISSQN>2.00</vISSQN><vLiq>100.00</vLiq></valores>
  </infNFSe>
</NFSe>
""",
        encoding="utf-8",
    )

    dados = extrair_dados_nfse(xml)

    assert dados["tomador_identificado"] is True
    assert dados["tom_cnpj"] == "22.222.222/0001-82"
    assert dados["tom_nome"] == "TOMADOR REAL LTDA"
    assert "Rua Um" in dados["tom_endereco"]
    assert dados["tom_nome"] != dados["emit_nome"]


def test_parser_extrai_retencoes_federais_variaveis_do_xml(tmp_path: Path) -> None:
    xml = tmp_path / "retencoes.xml"
    xml.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">
  <infNFSe Id="NFS123">
    <xLocEmi>Goiania</xLocEmi>
    <xLocPrestacao>Goiania</xLocPrestacao>
    <nNFSe>10</nNFSe>
    <dhProc>2026-01-01T10:00:00-03:00</dhProc>
    <emit><CNPJ>11111111000191</CNPJ><xNome>PRESTADOR LTDA</xNome></emit>
    <DPS><infDPS>
      <serie>1</serie><nDPS>10</nDPS><dCompet>2026-01-01</dCompet><dhEmi>2026-01-01T10:00:00-03:00</dhEmi>
      <prest><CNPJ>11111111000191</CNPJ></prest>
      <serv><cServ><cTribNac>110201</cTribNac><xDescServ>Servico</xDescServ></cServ></serv>
      <valores>
        <vServPrest><vServ>1000.00</vServ></vServPrest>
        <trib>
          <tribMun><tribISSQN>1</tribISSQN><tpRetISSQN>2</tpRetISSQN><pAliq>3.00</pAliq></tribMun>
          <tribFed>
            <vRetIRRF>10.00</vRetIRRF>
            <vRetCP>20.00</vRetCP>
            <vRetCSLL>3.00</vRetCSLL>
            <piscofins><vPis>1.00</vPis><vCofins>2.00</vCofins></piscofins>
          </tribFed>
        </trib>
      </valores>
    </infDPS></DPS>
    <valores><vBC>1000.00</vBC><pAliqAplic>3.00</pAliqAplic><vISSQN>30.00</vISSQN><vLiq>934.00</vLiq></valores>
  </infNFSe>
</NFSe>
""",
        encoding="utf-8",
    )

    dados = extrair_dados_nfse(xml)

    assert dados["retencao_issqn"] == "Retido pelo Tomador"
    assert dados["issqn_retido"] == "30.00"
    assert dados["irrf"] == "10.00"
    assert dados["contrib_previdenciaria_retida"] == "20.00"
    assert dados["contrib_sociais_retidas"] == "3.00"
    assert dados["pis_retido"] == "1.00"
    assert dados["cofins_retido"] == "2.00"
    assert dados["total_retencoes_federais"] == "36.00"
