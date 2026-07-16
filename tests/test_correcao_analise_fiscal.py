from __future__ import annotations

from decimal import Decimal
from xml.etree import ElementTree

from backend.app.services.legacy_ingestion_service import (
    extrair_codigo_servico_xml,
    identificar_iss_retido,
    parse_xml_resumo_bytes,
)
from backend.app.services.retencoes_calculo_service import calcular_retencoes_esperadas
from backend.app.services.retencoes_regras_service import normalizar_subitem_lc116


def _xml_com_ctribnac(codigo: str, extra: str = "") -> bytes:
    return f"""
<NFSe>
  <infNFSe Id="NFS53001081237381902000125000000000012326010112345678">
    <DPS><infDPS><serv><cServ><cTribNac>{codigo}</cTribNac></cServ></serv></infDPS></DPS>
    <valores><vBC>320.00</vBC><vISSQN>16.00</vISSQN><pAliqAplic>5.00</pAliqAplic><vLiq>304.00</vLiq>
      <trib><tribMun><tpRetISSQN>2</tpRetISSQN></tribMun></trib>
    {extra}</valores>
  </infNFSe>
</NFSe>
""".encode("utf-8")


# ---------------------------------------------------------------------------
# Teste 1 - Codigo de servico com 6 digitos (110101)
# ---------------------------------------------------------------------------
def test_codigo_servico_seis_digitos_110101():
    root = ElementTree.fromstring(_xml_com_ctribnac("110101"))
    info = extrair_codigo_servico_xml(root)
    assert info["codigo_servico_raw"] == "110101"
    assert info["codigo_servico_display"] == "11.01.01"
    assert info["subitem_lc116"] == "11.01"

    resumo = parse_xml_resumo_bytes(_xml_com_ctribnac("110101"))
    assert resumo["subitem_lc116"] == "11.01"
    assert "Subitem LC116 nao identificado" not in resumo["alertas_fiscais"]


def test_cstat_100_nao_vira_substituida_por_texto_da_descricao():
    xml = _xml_com_ctribnac(
        "110101",
        "<cStat>100</cStat><xDesc>Servico sujeito a substituicao tributaria</xDesc>",
    )
    resumo = parse_xml_resumo_bytes(xml)
    assert resumo["status_documento"] == "autorizada"


# ---------------------------------------------------------------------------
# Teste 2 - Codigo de servico 170101
# ---------------------------------------------------------------------------
def test_codigo_servico_seis_digitos_170101():
    root = ElementTree.fromstring(_xml_com_ctribnac("170101"))
    info = extrair_codigo_servico_xml(root)
    assert info["codigo_servico_raw"] == "170101"
    assert info["codigo_servico_display"] == "17.01.01"
    assert info["subitem_lc116"] == "17.01"


# ---------------------------------------------------------------------------
# Teste 3 - Codigo ja formatado
# ---------------------------------------------------------------------------
def test_codigo_servico_ja_formatado():
    assert normalizar_subitem_lc116("11.01.01") == "11.01"
    assert normalizar_subitem_lc116("11.01") == "11.01"

    root = ElementTree.fromstring(_xml_com_ctribnac("11.01.01"))
    info = extrair_codigo_servico_xml(root)
    assert info["codigo_servico_display"] == "11.01.01"
    assert info["subitem_lc116"] == "11.01"


# ---------------------------------------------------------------------------
# Teste 4 - ISS retido pelo tomador nao gera alerta de valor liquido
# ---------------------------------------------------------------------------
def test_iss_retido_pelo_tomador_nao_gera_alerta_valor_liquido():
    calculo = calcular_retencoes_esperadas(
        {
            "valor_servico": "320.00",
            "valor_base_calculo": "320.00",
            "valor_iss": "16.00",
            "iss_retido": True,
            "valor_liquido": "304.00",
        },
        regra={"irrf": "NAO", "pcc": "NAO", "inss": "NAO", "subitem": "11.01"},
        subitem_lc116="11.01",
    )
    assert calculo["valor_liquido_calculado"] == Decimal("304.00")
    assert calculo["status_valor_liquido"] == "Correto"
    assert "Valor liquido esperado" not in calculo["alertas_fiscais"]


# ---------------------------------------------------------------------------
# Teste 5 - ISS nao retido nao gera alerta de valor liquido
# ---------------------------------------------------------------------------
def test_iss_nao_retido_nao_gera_alerta_valor_liquido():
    calculo = calcular_retencoes_esperadas(
        {
            "valor_servico": "320.00",
            "valor_base_calculo": "320.00",
            "valor_iss": "16.00",
            "iss_retido": False,
            "valor_liquido": "320.00",
        },
        regra={"irrf": "NAO", "pcc": "NAO", "inss": "NAO", "subitem": "11.01"},
        subitem_lc116="11.01",
    )
    assert calculo["valor_liquido_calculado"] == Decimal("320.00")
    assert calculo["status_valor_liquido"] == "Correto"
    assert "Valor liquido esperado" not in calculo["alertas_fiscais"]


# ---------------------------------------------------------------------------
# Teste 6 - Subitem realmente ausente no XML
# ---------------------------------------------------------------------------
def test_subitem_ausente_de_verdade_gera_alerta():
    xml = b"""
<NFSe>
  <infNFSe Id="NFS53001081237381902000125000000000012326010112345678">
    <DPS><infDPS><serv><cServ><xDescServ>Sem codigo</xDescServ></cServ></serv></infDPS></DPS>
    <valores><vBC>100.00</vBC></valores>
  </infNFSe>
</NFSe>
"""
    root = ElementTree.fromstring(xml)
    info = extrair_codigo_servico_xml(root)
    assert info["subitem_lc116"] == ""

    resumo = parse_xml_resumo_bytes(xml)
    assert resumo["subitem_lc116"] == ""
    assert "Subitem LC116 nao identificado no XML" in resumo["alertas_fiscais"]
    assert "cTribNac" in resumo["alertas_fiscais"]


# ---------------------------------------------------------------------------
# Teste 7 - Subitem identificado mas sem regra cadastrada
# ---------------------------------------------------------------------------
def test_subitem_identificado_sem_regra_cadastrada():
    calculo = calcular_retencoes_esperadas(
        {"valor_servico": "100.00", "valor_base_calculo": "100.00"},
        regra=None,
        subitem_lc116="99.99",
    )
    assert "Subitem LC116 nao identificado" not in calculo["alertas_fiscais"]
    assert "Regra fiscal nao encontrada para subitem LC116 99.99." in calculo["alertas_fiscais"]


# ---------------------------------------------------------------------------
# Compatibilidade: chamada antiga (sem subitem_lc116) com regra valida nao
# deve gerar alerta de subitem nao identificado.
# ---------------------------------------------------------------------------
def test_compatibilidade_chamada_sem_subitem_param_mas_com_regra():
    calculo = calcular_retencoes_esperadas(
        {"valor_servico": "1000.00", "valor_base_calculo": "1000.00"},
        regra={"subitem": "17.01", "irrf": "SIM", "irrf_aliquota": "0.015", "pcc": "SIM", "inss": "NAO"},
    )
    assert "Subitem LC116 nao identificado" not in calculo["alertas_fiscais"]
    assert "Regra fiscal nao encontrada" not in calculo["alertas_fiscais"]


# ---------------------------------------------------------------------------
# identificar_iss_retido - dominio correto do tpRetISSQN
# ---------------------------------------------------------------------------
def test_identificar_iss_retido_dominio_tpretissqn():
    def _root(tp: str) -> ElementTree.Element:
        return ElementTree.fromstring(
            f"<NFSe><valores><trib><tribMun><tpRetISSQN>{tp}</tpRetISSQN></tribMun></trib></valores></NFSe>"
        )

    retido, descricao = identificar_iss_retido(_root("1"))
    assert retido is False
    assert descricao == "Não Retido"

    retido, descricao = identificar_iss_retido(_root("2"))
    assert retido is True
    assert descricao == "Retido pelo Tomador"

    retido, descricao = identificar_iss_retido(_root("3"))
    assert retido is True
    assert descricao == "Retido pelo Intermediário"


def test_identificar_iss_retido_sem_indicador_no_xml():
    root = ElementTree.fromstring("<NFSe><valores><vISSQN>16.00</vISSQN></valores></NFSe>")
    retido, descricao = identificar_iss_retido(root)
    assert retido is False
    assert descricao == "Não Retido"


# ---------------------------------------------------------------------------
# Cenario completo do relato: valor liquido com ISS retido pelo tomador
# deve bater exatamente com o exemplo do PDF (320,00 - 16,00 = 304,00).
# ---------------------------------------------------------------------------
def test_cenario_relatado_valor_liquido_iss_retido_end_to_end():
    xml = _xml_com_ctribnac("110101")
    resumo = parse_xml_resumo_bytes(xml)

    assert resumo["subitem_lc116"] == "11.01"
    assert resumo["iss_retido"] is True
    assert resumo["valor_liquido_calculado"] == "304.00"
    assert "Subitem LC116 nao identificado" not in resumo["alertas_fiscais"]
    assert "Valor liquido esperado" not in resumo["alertas_fiscais"]


# ---------------------------------------------------------------------------
# Auditoria fiscal: cNBS NUNCA pode derivar subitem_lc116.
#
# cNBS (Nomenclatura Brasileira de Servicos) e uma classificacao diferente
# da LC116. Um codigo NBS numerico pode ter 4 ou 6 digitos por coincidencia
# e, se usado como fallback de LC116, produziria um subitem_lc116 falso e
# aplicaria regra fiscal (IRRF/CSRF/INSS/ISS) do subitem errado.
# ---------------------------------------------------------------------------
def test_cnbs_sozinho_nao_deriva_subitem_lc116():
    xml = b"""
<NFSe>
  <infNFSe Id="NFS53001081237381902000125000000000012326010112345678">
    <DPS><infDPS><serv><cServ><cNBS>170101</cNBS></cServ></serv></infDPS></DPS>
    <valores><vBC>320.00</vBC></valores>
  </infNFSe>
</NFSe>
"""
    root = ElementTree.fromstring(xml)
    info = extrair_codigo_servico_xml(root)
    assert info["codigo_servico_raw"] == ""
    assert info["codigo_servico_display"] == ""
    assert info["subitem_lc116"] == ""

    resumo = parse_xml_resumo_bytes(xml)
    assert resumo["subitem_lc116"] == ""
    # NBS continua disponivel para exibicao/relatorio, so nao vira LC116.
    assert resumo["codigo_nbs"] == "170101"
    assert "Subitem LC116 nao identificado no XML" in resumo["alertas_fiscais"]

    # Sem subitem, nenhuma regra fiscal (IRRF/CSRF/INSS) pode ter sido
    # aplicada com base no NBS: nao deve haver referencia a regra encontrada.
    assert "Regra fiscal nao encontrada" not in resumo["alertas_fiscais"]


def test_cnbs_presente_nao_atrapalha_quando_ctribnac_tambem_existe():
    xml = b"""
<NFSe>
  <infNFSe Id="NFS53001081237381902000125000000000012326010112345678">
    <DPS><infDPS><serv><cServ><cTribNac>110101</cTribNac><cNBS>999999</cNBS></cServ></serv></infDPS></DPS>
    <valores><vBC>320.00</vBC></valores>
  </infNFSe>
</NFSe>
"""
    root = ElementTree.fromstring(xml)
    info = extrair_codigo_servico_xml(root)
    assert info["subitem_lc116"] == "11.01"
    assert info["campo_origem_codigo_servico"] == "cTribNac"


def test_ordem_prioridade_extracao_codigo_servico():
    assert extrair_codigo_servico_xml(
        ElementTree.fromstring("<n><cTribNac>110101</cTribNac><cTribMun>170101</cTribMun></n>")
    )["campo_origem_codigo_servico"] == "cTribNac"

    assert extrair_codigo_servico_xml(
        ElementTree.fromstring("<n><cTribMun>170101</cTribMun><itemListaServico>0101</itemListaServico></n>")
    )["campo_origem_codigo_servico"] == "cTribMun"

    assert extrair_codigo_servico_xml(
        ElementTree.fromstring("<n><itemListaServico>0101</itemListaServico><codigoServico>0703</codigoServico></n>")
    )["campo_origem_codigo_servico"] == "itemListaServico"

    assert extrair_codigo_servico_xml(
        ElementTree.fromstring("<n><codigoServico>0703</codigoServico><cServ>1001</cServ></n>")
    )["campo_origem_codigo_servico"] == "codigoServico"


# ---------------------------------------------------------------------------
# tpRetISSQN=1 (nao retido): a aliquota (pAliq) normalmente nao e informada
# ou vem zerada no XML (nao deve ser preenchida, sob pena de rejeicao no
# padrao NFS-e Nacional). Sem retencao, nao ha base para calcular um ISS
# esperado a partir da aliquota — nao devemos preencher/comparar o ISS.
# ---------------------------------------------------------------------------
def test_iss_nao_retido_nao_calcula_nem_compara_aliquota():
    calculo = calcular_retencoes_esperadas(
        {
            "valor_servico": "320.00",
            "valor_base_calculo": "320.00",
            "aliquota_iss": "0",
            "valor_iss": "16.00",
            "iss_retido": False,
        },
        regra={"irrf": "NAO", "pcc": "NAO", "inss": "NAO", "subitem": "11.01"},
        subitem_lc116="11.01",
    )
    assert calculo["iss_calculado"] is None
    assert calculo["status_iss"] == "Nao Retido"
    assert "ISS" not in calculo["alertas_fiscais"]


def test_iss_nao_retido_mesmo_com_aliquota_presente_nao_gera_calculo():
    # Mesmo que o XML traga uma aliquota preenchida por engano/legado, sem
    # retencao (tpRetISSQN=1) nao ha o que comparar.
    calculo = calcular_retencoes_esperadas(
        {
            "valor_servico": "320.00",
            "valor_base_calculo": "320.00",
            "aliquota_iss": "5.00",
            "valor_iss": "16.00",
            "iss_retido": False,
        },
        regra={"irrf": "NAO", "pcc": "NAO", "inss": "NAO", "subitem": "11.01"},
        subitem_lc116="11.01",
    )
    assert calculo["iss_calculado"] is None
    assert calculo["status_iss"] == "Nao Retido"
    assert "ISS" not in calculo["alertas_fiscais"]


def test_iss_retido_com_aliquota_correta_nao_gera_alerta():
    calculo = calcular_retencoes_esperadas(
        {
            "valor_servico": "320.00",
            "valor_base_calculo": "320.00",
            "aliquota_iss": "5.00",
            "valor_iss": "16.00",
            "iss_retido": True,
        },
        regra={"irrf": "NAO", "pcc": "NAO", "inss": "NAO", "subitem": "11.01"},
        subitem_lc116="11.01",
    )
    assert calculo["iss_calculado"] == Decimal("16.00")
    assert calculo["status_iss"] == "Correto"
    assert "ISS" not in calculo["alertas_fiscais"]


def test_iss_retido_com_valor_divergente_gera_alerta():
    calculo = calcular_retencoes_esperadas(
        {
            "valor_servico": "320.00",
            "valor_base_calculo": "320.00",
            "aliquota_iss": "5.00",
            "valor_iss": "10.00",
            "iss_retido": True,
        },
        regra={"irrf": "NAO", "pcc": "NAO", "inss": "NAO", "subitem": "11.01"},
        subitem_lc116="11.01",
    )
    assert calculo["iss_calculado"] == Decimal("16.00")
    assert calculo["status_iss"] == "Divergente"
    assert "ISS esperado R$ 16.00, informado R$ 10.00." in calculo["alertas_fiscais"]


def test_iss_retido_sem_aliquota_no_xml_fica_depende_de_analise():
    calculo = calcular_retencoes_esperadas(
        {
            "valor_servico": "320.00",
            "valor_base_calculo": "320.00",
            "valor_iss": "16.00",
            "iss_retido": True,
        },
        regra={"irrf": "NAO", "pcc": "NAO", "inss": "NAO", "subitem": "11.01"},
        subitem_lc116="11.01",
    )
    assert calculo["iss_calculado"] is None
    assert calculo["status_iss"] == "Depende de analise"
