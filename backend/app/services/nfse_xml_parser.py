from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from pathlib import Path


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
    "5": "Microempresario Individual (MEI)",
    "6": "Microempresario e Empresa de Pequeno Porte (ME/EPP)",
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
    "3": "Retido pelo Intermediario",
}

UF_BY_IBGE_PREFIX = {
    "11": "RO",
    "12": "AC",
    "13": "AM",
    "14": "RR",
    "15": "PA",
    "16": "AP",
    "17": "TO",
    "21": "MA",
    "22": "PI",
    "23": "CE",
    "24": "RN",
    "25": "PB",
    "26": "PE",
    "27": "AL",
    "28": "SE",
    "29": "BA",
    "31": "MG",
    "32": "ES",
    "33": "RJ",
    "35": "SP",
    "41": "PR",
    "42": "SC",
    "43": "RS",
    "50": "MS",
    "51": "MT",
    "52": "GO",
    "53": "DF",
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el: ET.Element | None, name: str | None = None) -> list[ET.Element]:
    if el is None:
        return []
    if name is None:
        return list(el)
    return [child for child in list(el) if _local_name(child.tag) == name]


def _child(el: ET.Element | None, *path: str) -> ET.Element | None:
    current = el
    for name in path:
        matches = _children(current, name)
        if not matches:
            return None
        current = matches[0]
    return current


def _find_first(el: ET.Element | None, name: str) -> ET.Element | None:
    if el is None:
        return None
    for node in el.iter():
        if _local_name(node.tag) == name:
            return node
    return None


def _txt(el: ET.Element | None, *path: str, default: str = "-") -> str:
    node = _child(el, *path) if path else el
    if node is not None and node.text and node.text.strip():
        return node.text.strip()
    return default


def _raw(el: ET.Element | None, *path: str) -> str:
    return _txt(el, *path, default="")


def _raw_first(el: ET.Element | None, *names: str) -> str:
    for name in names:
        value = _raw(_find_first(el, name))
        if value:
            return value
    return ""


def _decimal(value: str) -> Decimal | None:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _money_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def _sum_values(*values: str) -> str:
    total = Decimal("0")
    has_value = False
    for value in values:
        parsed = _decimal(value)
        if parsed is None:
            continue
        total += parsed
        has_value = True
    return _money_text(total) if has_value else ""


def _fmt_cnpj_cpf(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 14:
        return f"{digits[0:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:14]}"
    if len(digits) == 11:
        return f"{digits[0:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:11]}"
    return digits or "-"


def _fmt_cep(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 8:
        return f"{digits[0:5]}-{digits[5:8]}"
    return digits or "-"


def _fmt_fone(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11:
        return f"({digits[0:2]}) {digits[2:7]}-{digits[7:11]}"
    if len(digits) == 10:
        return f"({digits[0:2]}) {digits[2:6]}-{digits[6:10]}"
    return digits or "-"


def _fmt_data(value: str) -> str:
    if not value or value == "-":
        return "-"
    try:
        year, month, day = value[:10].split("-")
    except ValueError:
        return value
    return f"{day}/{month}/{year}"


def _fmt_datahora(value: str) -> str:
    if not value or value == "-":
        return "-"
    if "T" not in value:
        return _fmt_data(value)
    data, rest = value.split("T", 1)
    hora = rest.split("-", 1)[0].split("+", 1)[0]
    return f"{_fmt_data(data)} {hora}"


def _montar_endereco(end: ET.Element | None) -> str:
    if end is None:
        return "-"
    parts = [_raw(end, "xLgr"), _raw(end, "nro"), _raw(end, "xCpl"), _raw(end, "xBairro")]
    parts = [part for part in parts if part]
    return ", ".join(parts) if parts else "-"


def _format_codigo_tributacao(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 6:
        return f"{digits[0:2]}.{digits[2:4]}.{digits[4:6]}"
    return value or "-"


def _municipio_uf(nome: str, uf: str = "", codigo_municipio: str = "") -> str:
    nome = (nome or "").strip()
    uf = (uf or "").strip().upper()
    codigo_municipio = re.sub(r"\D", "", codigo_municipio or "")
    if not uf and len(codigo_municipio) >= 2:
        uf = UF_BY_IBGE_PREFIX.get(codigo_municipio[:2], "")
    if nome and uf:
        return f"{nome} - {uf}"
    return nome or "-"


def _extrair_chave(attr_id: str | None, prefixo: str) -> str:
    value = attr_id or ""
    return value[len(prefixo):] if value.startswith(prefixo) else value or "-"


def _has_real_data(el: ET.Element | None) -> bool:
    if el is None:
        return False
    for node in el.iter():
        if node.text and node.text.strip():
            return True
    return False


def extrair_dados_nfse(xml_path: str | Path, prefeitura_info: dict | None = None) -> dict:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    inf_nfse = _find_first(root, "infNFSe")
    if inf_nfse is None:
        raise ValueError("XML sem infNFSe.")

    dps = _child(inf_nfse, "DPS", "infDPS") or _find_first(inf_nfse, "infDPS")
    emit = _child(inf_nfse, "emit")
    prest = _child(dps, "prest")
    toma = _child(dps, "toma")
    serv = _child(dps, "serv")
    c_serv = _child(serv, "cServ")
    loc_prest = _child(serv, "locPrest")
    valores_nfse = _child(inf_nfse, "valores")
    valores_dps = _child(dps, "valores")
    v_serv_prest = _child(valores_dps, "vServPrest")
    descontos = _child(valores_dps, "vDescCondIncond")
    trib = _child(valores_dps, "trib")
    trib_mun = _child(trib, "tribMun")
    trib_fed = _child(trib, "tribFed")
    tot_trib = _child(trib, "totTrib", "pTotTrib")
    reg_trib = _child(prest, "regTrib")
    emit_end = _child(emit, "enderNac")
    tom_end = _child(toma, "end")
    tom_end_nac = _child(tom_end, "endNac")

    chave_acesso = _extrair_chave(inf_nfse.get("Id"), "NFS")
    x_loc_emi = _raw(inf_nfse, "xLocEmi")
    x_loc_prestacao = _raw(inf_nfse, "xLocPrestacao")
    x_loc_incid = _raw(inf_nfse, "xLocIncid")
    c_loc_prestacao = _raw(loc_prest, "cLocPrestacao")
    c_loc_incid = _raw(inf_nfse, "cLocIncid")
    emit_uf = _raw(emit_end, "UF")
    emit_cmun = _raw(emit_end, "cMun") or _raw(dps, "cLocEmi")

    c_trib_nac = _raw(c_serv, "cTribNac")
    x_trib_nac = _raw(inf_nfse, "xTribNac")
    c_trib_nac_fmt = _format_codigo_tributacao(c_trib_nac)
    codigo_tributacao_nacional = (
        f"{c_trib_nac_fmt} - {x_trib_nac}" if c_trib_nac_fmt != "-" and x_trib_nac else c_trib_nac_fmt
    )

    c_trib_mun = _raw(c_serv, "cTribMun")
    x_trib_mun = _raw(inf_nfse, "xTribMun")
    codigo_tributacao_municipal = f"{c_trib_mun} - {x_trib_mun}" if c_trib_mun and x_trib_mun else c_trib_mun or "-"

    tomador_identificado = _has_real_data(toma)
    tom_uf = _raw(tom_end_nac, "UF")
    tom_cmun = _raw(tom_end_nac, "cMun")

    municipio_prefeitura = (prefeitura_info or {}).get("municipio_prefeitura")
    if not municipio_prefeitura and x_loc_emi:
        municipio_prefeitura = x_loc_emi

    nbs = _raw(c_serv, "cNBS")
    descricao_nbs = _raw(inf_nfse, "xNBS")
    info_complementar = _raw(_child(serv, "infoCompl"), "xInfComp")
    retencao_iss_codigo = _raw(trib_mun, "tpRetISSQN")
    issqn_apurado = _raw(valores_nfse, "vISSQN")
    valor_irrf = _raw_first(trib_fed, "vRetIRRF")
    valor_inss = _raw_first(trib_fed, "vRetCP")
    valor_csll = _raw_first(trib_fed, "vRetCSLL")
    valor_pis = _raw_first(trib_fed, "vPis")
    valor_cofins = _raw_first(trib_fed, "vCofins")
    total_retencoes_federais = _raw(valores_nfse, "vTotalRet") or _sum_values(
        valor_irrf,
        valor_inss,
        valor_csll,
        valor_pis,
        valor_cofins,
    )

    return {
        "municipio_prefeitura": municipio_prefeitura or "",
        "orgao_prefeitura": (prefeitura_info or {}).get("orgao_prefeitura", ""),
        "telefone_prefeitura": (prefeitura_info or {}).get("telefone_prefeitura", ""),
        "email_prefeitura": (prefeitura_info or {}).get("email_prefeitura", ""),
        "chave_acesso": chave_acesso,
        "numero_nfse": _txt(inf_nfse, "nNFSe"),
        "competencia": _fmt_data(_raw(dps, "dCompet")),
        "data_emissao_nfse": _fmt_datahora(_raw(inf_nfse, "dhProc")),
        "numero_dps": _txt(dps, "nDPS"),
        "serie_dps": _txt(dps, "serie"),
        "data_emissao_dps": _fmt_datahora(_raw(dps, "dhEmi")),
        "emit_cnpj": _fmt_cnpj_cpf(_raw(emit, "CNPJ") or _raw(emit, "CPF") or _raw(emit, "NIF")),
        "emit_inscricao_municipal": _txt(emit, "IM"),
        "emit_telefone": _fmt_fone(_raw(emit, "fone") or _raw(prest, "fone")),
        "emit_nome": _txt(emit, "xNome"),
        "emit_email": _txt(emit, "email", default=_txt(prest, "email")),
        "emit_endereco": _montar_endereco(emit_end),
        "emit_municipio": _municipio_uf(x_loc_emi or x_loc_prestacao, emit_uf, emit_cmun),
        "emit_cep": _fmt_cep(_raw(emit_end, "CEP")),
        "emit_simples_nacional": OP_SIMP_NAC.get(_raw(reg_trib, "opSimpNac"), "-"),
        "emit_regime_apuracao": (
            "Regime de apuracao dos tributos federais e municipal pelo Simples Nacional"
            if _raw(reg_trib, "opSimpNac") in {"2", "3"}
            else "-"
        ),
        "tomador_identificado": tomador_identificado,
        "tom_cnpj": _fmt_cnpj_cpf(_raw(toma, "CNPJ") or _raw(toma, "CPF") or _raw(toma, "NIF")) if tomador_identificado else "-",
        "tom_inscricao_municipal": _txt(toma, "IM") if tomador_identificado else "-",
        "tom_telefone": _fmt_fone(_raw(toma, "fone")) if tomador_identificado else "-",
        "tom_nome": _txt(toma, "xNome") if tomador_identificado else "-",
        "tom_email": _txt(toma, "email") if tomador_identificado else "-",
        "tom_endereco": _montar_endereco(tom_end) if tomador_identificado else "-",
        "tom_municipio": _municipio_uf(_raw(tom_end_nac, "xMun"), tom_uf, tom_cmun) if tomador_identificado else "-",
        "tom_cep": _fmt_cep(_raw(tom_end_nac, "CEP")) if tomador_identificado else "-",
        "codigo_tributacao_nacional": codigo_tributacao_nacional,
        "codigo_tributacao_municipal": codigo_tributacao_municipal,
        "local_prestacao": _municipio_uf(x_loc_prestacao, emit_uf, c_loc_prestacao or emit_cmun),
        "pais_prestacao": "-",
        "descricao_servico": _txt(c_serv, "xDescServ"),
        "nbs": nbs,
        "descricao_nbs": descricao_nbs,
        "informacoes_complementares": info_complementar,
        "tributacao_issqn": TRIB_ISSQN.get(_raw(trib_mun, "tribISSQN"), "-"),
        "municipio_incidencia_issqn": _municipio_uf(x_loc_incid, emit_uf, c_loc_incid or emit_cmun),
        "regime_especial_tributacao": REG_ESP_TRIB.get(_raw(reg_trib, "regEspTrib"), "Nenhum"),
        "retencao_issqn": TP_RET_ISSQN.get(retencao_iss_codigo, "-"),
        "suspensao_exigibilidade_issqn": "Nao",
        "valor_servico": _raw(v_serv_prest, "vServ"),
        "desconto_incondicionado": _raw(descontos, "vDescIncond"),
        "desconto_incondicionado_mun": _raw(descontos, "vDescIncond"),
        "desconto_condicionado": _raw(descontos, "vDescCond"),
        "bc_issqn": _raw(valores_nfse, "vBC"),
        "aliquota_aplicada": _raw(valores_nfse, "pAliqAplic") or _raw(trib_mun, "pAliq"),
        "issqn_apurado": issqn_apurado,
        "issqn_retido": issqn_apurado if retencao_iss_codigo in {"2", "3"} else "",
        "valor_liquido_nfse": _raw(valores_nfse, "vLiq"),
        "total_retencoes_federais": total_retencoes_federais,
        "irrf": valor_irrf,
        "contrib_previdenciaria_retida": valor_inss,
        "contrib_sociais_retidas": valor_csll,
        "pis_retido": valor_pis,
        "cofins_retido": valor_cofins,
        "totais_federais": _raw(tot_trib, "pTotTribFed") or _raw(valores_nfse, "vTotTribFed"),
        "totais_estaduais": _raw(tot_trib, "pTotTribEst") or _raw(valores_nfse, "vTotTribEst"),
        "totais_municipais": _raw(tot_trib, "pTotTribMun") or _raw(valores_nfse, "vTotTribMun"),
        "nfse_subst": "-",
    }


if __name__ == "__main__":
    import json
    import sys

    print(json.dumps(extrair_dados_nfse(sys.argv[1]), indent=2, ensure_ascii=False))
