"""
Parser de XML da NFS-e (padrão nacional) -> dicionário de dados para o
NfsePdfService (nfse_pdf_service_reportlab.py).

Uso:
    from nfse_xml_parser import extrair_dados_nfse
    dados = extrair_dados_nfse("caminho/para/nota.xml")
    NfsePdfService().gerar_danfse_espelho(dados, "saida.pdf")

Cobre os XMLs no padrão nacional da NFS-e (xmlns
"http://www.sped.fazenda.gov.br/nfse"), com <infNFSe> e <DPS>/<infDPS>
aninhados, que é o modelo usado pela maioria dos municípios que já
migraram para o padrão nacional (ex: Fortaleza, Hidrolândia etc.).
"""

import re
import xml.etree.ElementTree as ET

NS = {"nfse": "http://www.sped.fazenda.gov.br/nfse"}

# --------------------------------------------------------------------
# Tabelas de domínio (padrão nacional NFS-e)
# --------------------------------------------------------------------

OP_SIMP_NAC = {
    "1": "Não Optante",
    "2": "Optante - Microempreendedor Individual (MEI)",
    "3": "Optante - Microempresa ou Empresa de Pequeno Porte (ME/EPP)",
}

REG_ESP_TRIB = {
    "0": "Nenhum",
    "1": "Ato Cooperado",
    "2": "Estimativa",
    "3": "Sociedade de Profissionais",
    "4": "Cooperativa",
    "5": "Microempresário Individual (MEI)",
    "6": "Microempresário e Empresa de Pequeno Porte (ME/EPP)",
}

TRIB_ISSQN = {
    "1": "Operação Tributável",
    "2": "Imunidade",
    "3": "Exportação de Serviço",
    "4": "Não Incidência",
    "5": "Isenção",
    "6": "Exigibilidade Suspensa",
}

TP_RET_ISSQN = {
    "1": "Não Retido",
    "2": "Retido pelo Tomador",
    "3": "Retido pelo Intermediário",
}

# ATENÇÃO: valide esses de-para com a tabela de domínios oficial mais
# recente do MDF-e/NFS-e nacional (podem mudar ou ter mais opções).
# Fonte de referência: manual do DANFSe / layout nacional da NFS-e.


# --------------------------------------------------------------------
# Helpers de formatação
# --------------------------------------------------------------------

def _fmt_cnpj_cpf(v: str) -> str:
    if not v:
        return "-"
    v = re.sub(r"\D", "", v)
    if len(v) == 14:
        return f"{v[0:2]}.{v[2:5]}.{v[5:8]}/{v[8:12]}-{v[12:14]}"
    if len(v) == 11:
        return f"{v[0:3]}.{v[3:6]}.{v[6:9]}-{v[9:11]}"
    return v


def _fmt_cep(v: str) -> str:
    if not v:
        return "-"
    v = re.sub(r"\D", "", v)
    return f"{v[0:5]}-{v[5:8]}" if len(v) == 8 else v


def _fmt_fone(v: str) -> str:
    if not v:
        return "-"
    v = re.sub(r"\D", "", v)
    if len(v) == 11:  # celular com 9 dígitos
        return f"({v[0:2]}) {v[2:7]}-{v[7:11]}"
    if len(v) == 10:  # fixo
        return f"({v[0:2]}) {v[2:6]}-{v[6:10]}"
    return v


def _fmt_datahora(v: str) -> str:
    # "2025-12-10T19:47:04-03:00" -> "10/12/2025 19:47:04"
    if not v:
        return "-"
    data, resto = v.split("T")
    hora = resto.split("-")[0].split("+")[0]
    y, m, d = data.split("-")
    return f"{d}/{m}/{y} {hora}"


def _fmt_data(v: str) -> str:
    # "2025-12-10" -> "10/12/2025"
    if not v:
        return "-"
    y, m, d = v.split("-")
    return f"{d}/{m}/{y}"


def _fmt_moeda(v: str) -> str:
    if v in (None, ""):
        return "-"
    try:
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except ValueError:
        return v


def _txt(el, path, default=None):
    node = el.find(path, NS)
    return node.text if node is not None and node.text else default


def _montar_endereco(xLgr, nro, xCpl, xBairro):
    partes = [p for p in [xLgr, nro, xCpl, xBairro] if p]
    return ", ".join(partes) if partes else "-"


def _extrair_chave(attr_id: str, prefixo: str) -> str:
    """Remove o prefixo (NFS/DPS) do atributo Id para obter a chave de acesso."""
    if attr_id and attr_id.startswith(prefixo):
        return attr_id[len(prefixo):]
    return attr_id or "-"


# --------------------------------------------------------------------
# Parser principal
# --------------------------------------------------------------------

def extrair_dados_nfse(xml_path: str, prefeitura_info: dict | None = None) -> dict:
    """
    Lê um XML de NFS-e (padrão nacional) e retorna o dicionário pronto
    para NfsePdfService.gerar_danfse_espelho().

    prefeitura_info (opcional): dict com dados fixos do município, ex:
        {
            "municipio_prefeitura": "Hidrolândia-GO",
            "orgao_prefeitura": "Departamento de Arrecadação e Fiscalização.",
            "telefone_prefeitura": "(62)99506-8320",
            "email_prefeitura": "coletoria.hidrolandia@gmail.com",
        }
    Se não vier, esses campos ficam em branco (não inventamos contato).
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    infNFSe = root.find("nfse:infNFSe", NS)
    dps = infNFSe.find("nfse:DPS/nfse:infDPS", NS)
    emit = infNFSe.find("nfse:emit", NS)
    prest = dps.find("nfse:prest", NS)
    toma = dps.find("nfse:toma", NS)
    serv = dps.find("nfse:serv", NS)
    cServ = serv.find("nfse:cServ", NS)
    valores_nfse = infNFSe.find("nfse:valores", NS)
    valores_dps = dps.find("nfse:valores", NS)
    vServPrest = valores_dps.find("nfse:vServPrest", NS)
    trib = valores_dps.find("nfse:trib", NS)
    tribMun = trib.find("nfse:tribMun", NS) if trib is not None else None
    regTrib = prest.find("nfse:regTrib", NS) if prest is not None else None

    # Chaves de acesso
    chave_acesso = _extrair_chave(infNFSe.get("Id"), "NFS")

    # Endereço emitente
    enderNac = emit.find("nfse:enderNac", NS)
    emit_endereco = _montar_endereco(
        _txt(enderNac, "nfse:xLgr"), _txt(enderNac, "nfse:nro"),
        _txt(enderNac, "nfse:xCpl"), _txt(enderNac, "nfse:xBairro"),
    )

    # Endereço tomador
    tom_end = toma.find("nfse:end", NS) if toma is not None else None
    tom_endereco = "-"
    tom_cep = "-"
    tom_municipio = "-"
    if tom_end is not None:
        tom_endereco = _montar_endereco(
            _txt(tom_end, "nfse:xLgr"), _txt(tom_end, "nfse:nro"),
            _txt(tom_end, "nfse:xCpl"), _txt(tom_end, "nfse:xBairro"),
        )
        tom_cep = _fmt_cep(_txt(tom_end, "nfse:endNac/nfse:CEP"))

    xLocPrestacao = _txt(infNFSe, "nfse:xLocPrestacao", "-")
    xLocIncid = _txt(infNFSe, "nfse:xLocIncid", "-")

    op_simp_nac = _txt(regTrib, "nfse:opSimpNac") if regTrib is not None else None
    reg_esp_trib = _txt(regTrib, "nfse:regEspTrib") if regTrib is not None else None
    trib_issqn_cod = _txt(tribMun, "nfse:tribISSQN") if tribMun is not None else None
    tp_ret_issqn_cod = _txt(tribMun, "nfse:tpRetISSQN") if tribMun is not None else None

    cTribNac = _txt(cServ, "nfse:cTribNac", "")
    cTribNac_fmt = f"{cTribNac[0:2]}.{cTribNac[2:4]}.{cTribNac[4:6]}" if len(cTribNac) == 6 else cTribNac
    xTribNac = _txt(infNFSe, "nfse:xTribNac", "")
    cTribMun = _txt(cServ, "nfse:cTribMun")
    xTribMun = _txt(infNFSe, "nfse:xTribMun")

    dados = {
        # Cabeçalho / prefeitura (não vem no XML — vem do seu cadastro por município)
        "municipio_prefeitura": (prefeitura_info or {}).get("municipio_prefeitura", f"{xLocPrestacao}"),
        "orgao_prefeitura": (prefeitura_info or {}).get("orgao_prefeitura", ""),
        "telefone_prefeitura": (prefeitura_info or {}).get("telefone_prefeitura", ""),
        "email_prefeitura": (prefeitura_info or {}).get("email_prefeitura", ""),

        # Identificação
        "chave_acesso": chave_acesso,
        "numero_nfse": _txt(infNFSe, "nfse:nNFSe"),
        "competencia": _fmt_data(_txt(dps, "nfse:dCompet")),
        "data_emissao_nfse": _fmt_datahora(_txt(infNFSe, "nfse:dhProc")),
        "numero_dps": _txt(dps, "nfse:nDPS"),
        "serie_dps": _txt(dps, "nfse:serie"),
        "data_emissao_dps": _fmt_datahora(_txt(dps, "nfse:dhEmi")),

        # Emitente
        "emit_cnpj": _fmt_cnpj_cpf(_txt(emit, "nfse:CNPJ") or _txt(emit, "nfse:CPF")),
        "emit_inscricao_municipal": _txt(emit, "nfse:IM", "-"),
        "emit_telefone": _fmt_fone(_txt(emit, "nfse:fone")),
        "emit_nome": _txt(emit, "nfse:xNome"),
        "emit_email": _txt(emit, "nfse:email", "-"),
        "emit_endereco": emit_endereco,
        "emit_municipio": f"{xLocPrestacao} - " + (enderNac.find('nfse:UF', NS).text if enderNac is not None and enderNac.find('nfse:UF', NS) is not None else ""),
        "emit_cep": _fmt_cep(_txt(enderNac, "nfse:CEP")),
        "emit_simples_nacional": OP_SIMP_NAC.get(op_simp_nac, "-"),
        "emit_regime_apuracao": (
            "Regime de apuração dos tributos federais e municipal pelo Simples Nacional"
            if op_simp_nac in ("2", "3") else "-"
        ),

        # Tomador
        "tom_cnpj": _fmt_cnpj_cpf(_txt(toma, "nfse:CNPJ") or _txt(toma, "nfse:CPF")) if toma is not None else "-",
        "tom_inscricao_municipal": _txt(toma, "nfse:IM", "-") if toma is not None else "-",
        "tom_telefone": _fmt_fone(_txt(toma, "nfse:fone")) if toma is not None else "-",
        "tom_nome": _txt(toma, "nfse:xNome", "-") if toma is not None else "-",
        "tom_email": _txt(toma, "nfse:email", "-") if toma is not None else "-",
        "tom_endereco": tom_endereco,
        "tom_municipio": xLocPrestacao,
        "tom_cep": tom_cep,

        # Serviço
        "codigo_tributacao_nacional": f"{cTribNac_fmt} - {xTribNac}".strip(" -"),
        "codigo_tributacao_municipal": f"{cTribMun} - {xTribMun}" if cTribMun else "-",
        "local_prestacao": xLocPrestacao,
        "pais_prestacao": "-",
        "descricao_servico": _txt(cServ, "nfse:xDescServ", "-"),

        # Tributação municipal
        "tributacao_issqn": TRIB_ISSQN.get(trib_issqn_cod, "-"),
        "municipio_incidencia_issqn": xLocIncid,
        "regime_especial_tributacao": REG_ESP_TRIB.get(reg_esp_trib, "Nenhum"),
        "retencao_issqn": TP_RET_ISSQN.get(tp_ret_issqn_cod, "-"),
        "valor_servico": _fmt_moeda(_txt(vServPrest, "nfse:vServ")),

        # Valor total
        "total_retencoes_federais": _fmt_moeda(_txt(valores_nfse, "nfse:vTotalRet")),
        "valor_liquido_nfse": _fmt_moeda(_txt(valores_nfse, "nfse:vLiq")),

        "nfse_subst": "-",
    }
    return dados


if __name__ == "__main__":
    import sys
    import json

    caminho = sys.argv[1] if len(sys.argv) > 1 else None
    if not caminho:
        print("Uso: python nfse_xml_parser.py caminho/para/arquivo.xml")
        sys.exit(1)

    dados = extrair_dados_nfse(caminho)
    print(json.dumps(dados, indent=2, ensure_ascii=False))
