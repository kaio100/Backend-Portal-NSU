from __future__ import annotations

import csv
import hashlib
import io
import re
import tempfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.tempo import hoje_local
from backend.app.core.observability import alert_failure
from backend.app.db.models import Evento, Nota, Processo
from backend.app.repositories import arquivos_repo, notas_repo
from backend.app.services.danfse_service import DanfseService, friendly_pdf_filename
from backend.app.services.nfse_status_service import (
    ROTULO_SUBSTITUIDA,
    STATUS_SUBSTITUIDA,
    classificar_xml,
    prioridade_status,
)
from backend.app.services.nfse_xml_parser import extrair_dados_nfse
from backend.app.services.operational_fields_service import (
    calcular_status_simples_nacional_xml,
    normalizar_simples_xml,
    simples_xml_from_codes,
)
from backend.app.services.retencoes_calculo_service import calcular_retencoes_esperadas, parse_decimal_xml
from backend.app.services.retencoes_regras_service import (
    normalizar_subitem_lc116,
    obter_regra_por_subitem,
)
from backend.app.services.storage_service import (
    StorageService,
    build_pdf_espelho_key,
    build_pdf_oficial_key,
    build_xml_key,
)


class LegacyIngestionError(RuntimeError):
    pass


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def _parse_datetime(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_int(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_decimal(value: str) -> Decimal | None:
    value = (value or "").strip().replace(",", ".")
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _ano_mes(row: dict[str, str]) -> tuple[str, str]:
    data_ref = _parse_date(row.get("competencia", "")) or _parse_date(row.get("data_emissao", ""))
    if data_ref is None:
        return "0000", "00"
    return f"{data_ref.year:04d}", f"{data_ref.month:02d}"


def _resolve_path(path_text: str, base_dir: Path) -> Path | None:
    path_text = (path_text or "").strip()
    if not path_text:
        return None
    path = Path(path_text)
    if path.exists():
        return path
    candidate = base_dir / path
    if candidate.exists():
        return candidate
    return None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_tipo(tipo: str) -> str:
    normalized = (tipo or "").lower()
    if normalized == "xml":
        return "XML"
    if normalized in {"pdf_oficial", "pdf_original", "oficial"}:
        return "PDF_ORIGINAL"
    if normalized in {"pdf_espelho", "espelho"}:
        return "PDF_ESPELHO"
    return tipo


def _gerar_pdf_espelho_path(
    xml_path: Path,
    row: dict[str, str],
    filename: str,
    status_documento: str | None = None,
) -> Path:
    output_dir = Path(settings.worker_temp_dir) / "pdf_espelho"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    pdf_bytes, _ = DanfseService().generate(xml_path.read_bytes(), watermark=status_documento)
    output_path.write_bytes(pdf_bytes)
    return output_path


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _find_text(root: ElementTree.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for element in root.iter():
        if _local_name(element.tag) in wanted and element.text:
            value = element.text.strip()
            if value:
                return value
    return ""


def _child_by_local_name(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    wanted = name.lower()
    for child in list(element):
        if _local_name(child.tag) == wanted:
            return child
    return None


def _find_path_text(root: ElementTree.Element, *path: str) -> str:
    contexts = [root]
    for part in path:
        next_contexts: list[ElementTree.Element] = []
        for context in contexts:
            if _local_name(context.tag) == part.lower():
                next_contexts.append(context)
            child = _child_by_local_name(context, part)
            if child is not None:
                next_contexts.append(child)
        contexts = next_contexts
        if not contexts:
            return ""
    for context in contexts:
        value = (context.text or "").strip()
        if value:
            return value
    return ""


def _find_scoped_text(
    root: ElementTree.Element,
    contexts: tuple[str, ...],
    names: tuple[str, ...],
) -> str:
    """Busca um campo somente dentro do bloco fiscal informado.

    Identificadores genericos como ``CNPJ``/``CPF`` e ``xNome`` aparecem nos
    blocos de prestador e tomador. Uma busca global pode atribuir a parte
    errada, especialmente quando o prestador e pessoa fisica.
    """
    wanted_contexts = {name.lower() for name in contexts}
    wanted_names = {name.lower() for name in names}
    for context in root.iter():
        if _local_name(context.tag) not in wanted_contexts:
            continue
        for element in context.iter():
            if _local_name(element.tag) in wanted_names and element.text:
                value = element.text.strip()
                if value:
                    return value
    return ""


def extrair_simples_nacional_xml(root: ElementTree.Element) -> str | None:
    op_simp = _find_path_text(root, "prest", "regTrib", "opSimpNac") or _find_text(root, "opSimpNac")
    reg_ap = _find_path_text(root, "prest", "regTrib", "regApTribSN") or _find_text(root, "regApTribSN")
    return simples_xml_from_codes(op_simp, reg_ap) or normalizar_simples_xml(op_simp or reg_ap)


def extrair_incidencia_iss_xml(root: ElementTree.Element, dados_nota: dict | None = None) -> str | None:
    dados_nota = dados_nota or {}
    return (
        _find_text(root, "xLocIncid")
        or _find_text(root, "cLocIncid")
        or str(dados_nota.get("municipio_incidencia") or "").strip()
        or _find_text(root, "xLocPrestacao")
        or _find_text(root, "cLocPrestacao")
        or str(dados_nota.get("municipio_prestacao") or "").strip()
        or str(dados_nota.get("municipio") or "").strip()
        or _find_text(root, "municipio", "xMun", "xMunicipio")
        or _find_text(root, "cMun")
    )


def extrair_municipio_prestacao_xml(root: ElementTree.Element, dados_nota: dict | None = None) -> str | None:
    dados_nota = dados_nota or {}
    return (
        _find_text(root, "xLocPrestacao")
        or _find_text(root, "cLocPrestacao")
        or str(dados_nota.get("municipio_prestacao") or "").strip()
        or str(dados_nota.get("municipio") or "").strip()
        or _find_text(root, "municipio", "xMun", "xMunicipio")
        or _find_text(root, "cMun")
    )


def _sum_existing_decimals(*values: str) -> str:
    parsed = [_parse_decimal(value) for value in values if (value or "").strip()]
    valid = [value for value in parsed if value is not None]
    if not valid:
        return ""
    return str(sum(valid))


TP_RET_ISSQN_DESCRICAO = {
    "1": "Não Retido",
    "2": "Retido pelo Tomador",
    "3": "Retido pelo Intermediário",
}


def identificar_iss_retido(root: ElementTree.Element) -> tuple[bool, str]:
    """Determina se o ISS foi retido, usando o XML como fonte principal.

    A NFS-e Nacional usa `tpRetISSQN` com dominio proprio (1=Nao Retido,
    2=Retido pelo Tomador, 3=Retido pelo Intermediario) - diferente do
    dominio booleano ("1"=Sim/"2"=Nao) usado por campos legados no estilo
    ABRASF (IssRetido/indISSRet/RetencaoISS). Por isso cada campo precisa
    da sua propria interpretacao, em vez de tratar todos como sinonimos.
    """
    tp_ret = _find_text(root, "tpRetISSQN")
    if tp_ret:
        retido = tp_ret in {"2", "3"}
        descricao = TP_RET_ISSQN_DESCRICAO.get(tp_ret, "Retido pelo Tomador" if retido else "Não Retido")
        return retido, descricao

    flag = _find_text(root, "ISSRetido", "IssRetido", "indISSRet", "RetencaoISS")
    if flag:
        text = flag.strip().lower()
        retido = text in {"1", "s", "sim", "true", "retido"}
        return retido, "Retido pelo Tomador" if retido else "Não Retido"

    valor_iss_retido = _find_text(root, "vISSRet", "ValorIssRetido", "ValorISSRetido")
    if (parse_decimal_xml(valor_iss_retido) or Decimal("0")) > 0:
        return True, "Retido pelo Tomador"

    return False, "Não Retido"


CAMPOS_CODIGO_SERVICO_PRIORIDADE: tuple[str, ...] = (
    "cTribNac",
    "cTribMun",
    "itemListaServico",
    "ItemListaServico",
    "codigoServico",
    "CodigoServico",
    "CodigoTributacaoMunicipio",
    "cServMun",
    "cServ",
)
# cNBS (Nomenclatura Brasileira de Servicos) e proposital-mente EXCLUIDO
# daqui: e uma classificacao diferente da LC116 e um codigo NBS numerico
# pode coincidir em tamanho (4 ou 6 digitos) com um codigo LC116 valido,
# levando a derivar um subitem_lc116 errado e aplicar regra fiscal (IRRF/
# CSRF/INSS/ISS) do subitem errado. O NBS e capturado separadamente no
# campo "codigo_nbs" do resumo, sem nunca alimentar subitem_lc116.


def _formatar_codigo_servico_display(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    digits = _text_digits(raw)
    if len(digits) == 6:
        return f"{digits[0:2]}.{digits[2:4]}.{digits[4:6]}"
    if len(digits) == 4:
        return f"{digits[0:2]}.{digits[2:4]}"
    if re.fullmatch(r"\d{1,2}\.\d{1,2}(\.\d{1,2})?", raw):
        return raw
    return raw


def extrair_codigo_servico_xml(root: ElementTree.Element) -> dict[str, str]:
    """Extrai codigo de servico/subitem LC116 do XML, testando varios campos
    por local-name (sem depender de namespace), na ordem de prioridade da
    NFS-e Nacional -> campos municipais -> nomenclaturas legadas ABRASF.

    Nunca usa um default silencioso: se nenhum campo produzir um subitem
    valido, retorna subitem_lc116 vazio para que o alerta correto seja gerado.
    """
    primeiro_valor_bruto: tuple[str, str] | None = None
    for nome in CAMPOS_CODIGO_SERVICO_PRIORIDADE:
        valor = _find_text(root, nome)
        if not valor:
            continue
        if primeiro_valor_bruto is None:
            primeiro_valor_bruto = (nome, valor)
        subitem = normalizar_subitem_lc116(valor)
        if subitem:
            return {
                "codigo_servico_raw": valor,
                "codigo_servico_display": _formatar_codigo_servico_display(valor),
                "subitem_lc116": subitem,
                "campo_origem_codigo_servico": nome,
            }

    if primeiro_valor_bruto is not None:
        nome, valor = primeiro_valor_bruto
        return {
            "codigo_servico_raw": valor,
            "codigo_servico_display": _formatar_codigo_servico_display(valor),
            "subitem_lc116": "",
            "campo_origem_codigo_servico": nome,
        }

    return {
        "codigo_servico_raw": "",
        "codigo_servico_display": "",
        "subitem_lc116": "",
        "campo_origem_codigo_servico": "",
    }


def _to_text(value) -> str:
    return "" if value is None else str(value)


def _text_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _extract_chave_from_xml(xml_path: Path, root: ElementTree.Element | None = None) -> str:
    if root is not None:
        for element in root.iter():
            for attr_value in element.attrib.values():
                digits = _text_digits(attr_value)
                if len(digits) >= 40:
                    return digits[-50:] if len(digits) > 50 else digits
        chave = _find_text(root, "chNFSe", "ChaveAcesso", "ChaveNFe", "ChaveNFSe", "Chave")
        digits = _text_digits(chave)
        if len(digits) >= 40:
            return digits[-50:] if len(digits) > 50 else digits

    filename_digits = _text_digits(xml_path.stem)
    if len(filename_digits) >= 40:
        return filename_digits[-50:]
    return xml_path.stem


def _parse_xml_resumo_root(root: ElementTree.Element, xml_path: Path) -> dict[str, str]:
    classificacao = classificar_xml(root)
    is_evento = classificacao.tipo == "evento"
    prestador_cnpj = _text_digits(
        _find_scoped_text(root, ("prest", "prestador", "emit"), ("cnpj", "cpf", "cpfcnpj"))
        or _find_text(root, "CnpjPrestador", "CNPJPrestador", "CpfCnpjPrestador", "CpfPrestador")
    )
    tomador_cnpj = _text_digits(
        _find_scoped_text(root, ("toma", "tomador"), ("cnpj", "cpf", "cpfcnpj"))
        or _find_text(root, "CnpjTomador", "CNPJTomador", "CpfCnpjTomador", "CpfTomador")
    )
    prestador_nome = (
        _find_scoped_text(root, ("prest", "prestador", "emit"), ("xnome", "razaosocial", "nome"))
        or _find_text(root, "RazaoSocialPrestador", "NomePrestador")
    )
    tomador_nome = (
        _find_scoped_text(root, ("toma", "tomador"), ("xnome", "razaosocial", "nome"))
        or _find_text(root, "RazaoSocialTomador", "NomeTomador")
    )
    status_documento, status_rotulo = classificacao.status, classificacao.rotulo
    simples_xml = extrair_simples_nacional_xml(root)
    valor_liquido = _find_text(root, "ValorLiquidoNfse", "ValorLiquido", "vLiq")
    valor_servico = _find_text(root, "ValorServicos", "ValorServico", "vServ")
    valor_base = _find_text(root, "vBC", "BaseCalculo", "ValorBaseCalculo") or valor_servico
    origem_base = "xml" if _find_text(root, "vBC", "BaseCalculo", "ValorBaseCalculo") else "fallback_valor_servico"
    pis = _find_text(root, "vPis", "ValorPis", "ValorPIS", "ValorPisRetido")
    cofins = _find_text(root, "vCofins", "ValorCofins", "ValorCOFINS", "ValorCofinsRetido")
    csll = _find_text(root, "vRetCSLL", "vCSLL", "ValorCsll", "ValorCSLL", "ValorCsllRetido")
    csrf_direto = _find_text(root, "ValorCsrf", "ValorCSRF", "ContribuicoesSociaisRetidas", "ValorContribuicoesSociaisRetidas")
    csrf = csrf_direto or _sum_existing_decimals(pis, cofins, csll)
    valor_iss_apurado = _find_text(root, "vISSQN", "ValorIss", "ValorISS", "ValorIssqn")
    iss_retido, descricao_retencao_iss = identificar_iss_retido(root)
    valor_iss_retido_raw = _find_text(root, "vISSRet", "ValorIssRetido", "ValorISSRetido")
    # Quando o ISS e retido mas o XML nao traz um campo dedicado com o valor
    # retido (comum na NFS-e Nacional), usa o ISSQN apurado como o valor retido.
    valor_iss_retido = valor_iss_retido_raw or (valor_iss_apurado if iss_retido else "")

    codigo_info = extrair_codigo_servico_xml(root)
    codigo_servico = codigo_info["codigo_servico_raw"] or _find_text(root, "cTribNac")
    codigo_servico_raw = codigo_info["codigo_servico_raw"]
    codigo_servico_display = codigo_info["codigo_servico_display"]
    subitem_lc116 = codigo_info["subitem_lc116"]
    regra = obter_regra_por_subitem(subitem_lc116) if subitem_lc116 else None
    descricao_servico_detalhada = _find_text(root, "xDescServ")
    dados_fiscais = {
        "valor_servico": valor_servico,
        "valor_base_calculo": valor_base,
        "aliquota_iss": _find_text(root, "pAliqAplic", "pAliq", "Aliquota", "AliquotaServicos", "AliquotaIss"),
        "valor_iss": valor_iss_apurado,
        "iss_retido": iss_retido,
        "valor_iss_retido": valor_iss_retido,
        "valor_irrf": _find_text(root, "vRetIRRF", "vIRRF", "ValorIr", "ValorIR", "ValorIrRetido", "ValorIRRF"),
        "valor_inss": _find_text(root, "vRetCP", "vINSS", "ValorInss", "ValorINSS", "ValorInssRetido"),
        "valor_pis": pis,
        "valor_cofins": cofins,
        "valor_csll": csll,
        "valor_csrf": csrf,
        "valor_outras_retencoes": _find_text(root, "OutrasRetencoes", "ValorOutrasRetencoes"),
        "valor_deducoes": _find_text(root, "ValorDeducoes"),
        "valor_desconto_incondicionado": _find_text(root, "DescontoIncondicionado"),
        "valor_desconto_condicionado": _find_text(root, "DescontoCondicionado"),
        "valor_liquido": valor_liquido,
        "simples_xml": simples_xml,
        "descricao_servico_detalhada": descricao_servico_detalhada,
    }
    calculo = calcular_retencoes_esperadas(dados_fiscais, regra, subitem_lc116=subitem_lc116 or None)
    return {
        "tipo_xml": "evento" if is_evento else "nota",
        "chave": _extract_chave_from_xml(xml_path, root),
        "chave_afetada": classificacao.chave_afetada or "",
        "chave_substituida": classificacao.chave_substituida or "",
        "codigo_evento": classificacao.codigo_evento or "",
        "descricao_evento": _find_text(root, "xDesc", "descEvento", "xEvento"),
        "motivo_evento": _find_text(root, "xMotivo", "motivo"),
        "numero_nfse": _find_text(root, "Numero", "NumeroNfse", "nNFSe"),
        "data_emissao": _find_text(root, "DataEmissao", "dhEmi", "DataHoraEmissao")[:10],
        # NFS-e Nacional usa dCompet; os demais nomes sao do padrao municipal.
        "competencia": _find_text(root, "dCompet", "Competencia", "DataCompetencia")[:10],
        "prestador_cnpj": prestador_cnpj,
        "prestador_nome": prestador_nome,
        "tomador_cnpj": tomador_cnpj,
        "tomador_nome": tomador_nome,
        "valor_servico": valor_servico,
        "valor_base": valor_base,
        "origem_base_calculo": origem_base,
        "iss": dados_fiscais["valor_iss"],
        "irrf": dados_fiscais["valor_irrf"],
        "inss": dados_fiscais["valor_inss"],
        "csrf": csrf,
        "valor_pis": pis,
        "valor_cofins": cofins,
        "valor_csll": csll,
        "valor_csrf": csrf,
        "valor_iss_retido": valor_iss_retido,
        "iss_retido": iss_retido,
        "descricao_retencao_iss": descricao_retencao_iss,
        "valor_outras_retencoes": dados_fiscais["valor_outras_retencoes"],
        "valor_deducoes": dados_fiscais["valor_deducoes"],
        "valor_desconto_incondicionado": dados_fiscais["valor_desconto_incondicionado"],
        "valor_desconto_condicionado": dados_fiscais["valor_desconto_condicionado"],
        "aliquota_iss": dados_fiscais["aliquota_iss"],
        "valor_liquido": valor_liquido,
        "valor_liquido_correto": _to_text(calculo.get("valor_liquido_calculado") or valor_liquido),
        "valor_liquido_calculado": _to_text(calculo.get("valor_liquido_calculado")),
        "status_valor_liquido": calculo.get("status_valor_liquido") or ("OK" if valor_liquido else ""),
        "simples_xml": simples_xml or "",
        "simples_nacional_xml": simples_xml or "",
        "status_simples_nacional": calcular_status_simples_nacional_xml(simples_xml),
        "incidencia_iss": extrair_incidencia_iss_xml(root) or "",
        "municipio": extrair_municipio_prestacao_xml(root) or "",
        "codigo_servico": codigo_servico,
        "codigo_servico_raw": codigo_servico_raw,
        "codigo_servico_display": codigo_servico_display,
        "codigo_servico_nacional": codigo_servico,
        "subitem_lc116": subitem_lc116 or "",
        "descricao_servico_nacional": _find_text(root, "xTribNac"),
        "descricao_servico_detalhada": descricao_servico_detalhada,
        "codigo_nbs": _find_text(root, "cNBS", "CodigoNBS", "CodigoNbs"),
        "codigo_cnae": _find_text(root, "CNAE", "cCNAE", "cnae", "CodigoCNAE"),
        "descricao_cnae": _find_text(root, "xCNAE", "DescricaoCNAE", "DescricaoCnae"),
        "data_pagamento": _find_text(root, "DataPagamento", "dtPagamento", "dPag", "dataPagamento")[:10],
        "irrf_calculado": _to_text(calculo.get("irrf_calculado")),
        "inss_calculado": _to_text(calculo.get("inss_calculado")),
        "pis_calculado": _to_text(calculo.get("pis_calculado")),
        "cofins_calculado": _to_text(calculo.get("cofins_calculado")),
        "csll_calculado": _to_text(calculo.get("csll_calculado")),
        "csrf_calculado": _to_text(calculo.get("csrf_calculado")),
        "iss_calculado": _to_text(calculo.get("iss_calculado")),
        "status_irrf": calculo.get("status_irrf") or "",
        "status_inss": calculo.get("status_inss") or "",
        "status_csrf": calculo.get("status_csrf") or "",
        "status_iss": calculo.get("status_iss") or "",
        "regra_irrf": (regra or {}).get("irrf") or "",
        "regra_irrf_aliquota": _to_text((regra or {}).get("irrf_aliquota")),
        "regra_pcc": (regra or {}).get("pcc") or "",
        "regra_inss": (regra or {}).get("inss") or "",
        "regra_observacao": (regra or {}).get("observacao") or "",
        "alertas_fiscais": calculo.get("alertas_fiscais") or "",
        "status_documento": status_documento or "",
        "status_rotulo": status_rotulo or "",
    }


def _parse_xml_resumo(xml_path: Path) -> dict[str, str]:
    try:
        root = ElementTree.parse(xml_path).getroot()
    except ElementTree.ParseError:
        root = None

    if root is None:
        return {"chave": _extract_chave_from_xml(xml_path)}
    return _parse_xml_resumo_root(root, xml_path)


def parse_xml_resumo_bytes(data: bytes, filename: str = "nota.xml") -> dict[str, str]:
    xml_path = Path(filename)
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return {"chave": _extract_chave_from_xml(xml_path)}
    return _parse_xml_resumo_root(root, xml_path)


def _registrar_evento_xml(
    db: Session,
    processo: Processo,
    resumo: dict[str, str],
    xml_storage_key: str | None,
    nsu: int | None,
) -> Nota | None:
    chave_evento = resumo.get("chave") or None
    chave_afetada = resumo.get("chave_afetada") or None
    status_documento = resumo.get("status_documento") or None
    status_rotulo = resumo.get("status_rotulo") or None
    nota = None
    aplicado = False
    if chave_afetada:
        nota = notas_repo.get_nota_by_chave(db, int(processo.empresa_id), chave_afetada)
        # Cancelada prevalece sobre substituida: um evento de substituicao que
        # chega depois nao desfaz um cancelamento ja registrado.
        if (
            nota is not None
            and status_documento in {"cancelada", "substituida"}
            and prioridade_status(status_documento) > prioridade_status(nota.status_documento)
        ):
            aplicado = True
            observacao = status_rotulo or status_documento
            motivo = resumo.get("motivo_evento") or resumo.get("descricao_evento")
            if motivo:
                observacao = f"{observacao} - motivo: {motivo}"
            notas_repo.update_nota(
                db,
                nota,
                {
                    "status_documento": status_documento,
                    "status_rotulo": status_rotulo,
                    "conferencia_observacao": nota.conferencia_observacao or observacao,
                    "ultimo_nsu": nsu or nota.ultimo_nsu,
                },
            )

    exists = None
    if chave_evento:
        exists = (
            db.query(Evento)
            .filter(Evento.empresa_id == processo.empresa_id)
            .filter(Evento.chave_evento == chave_evento)
            .first()
        )
    if exists is None:
        db.add(
            Evento(
                empresa_id=processo.empresa_id,
                nota_id=nota.id if nota is not None else None,
                chave_evento=chave_evento,
                chave_afetada=chave_afetada,
                tipo_evento=status_documento or "evento",
                descricao=resumo.get("descricao_evento") or resumo.get("motivo_evento"),
                xml_storage_key=xml_storage_key,
                nsu=nsu,
            )
        )
        db.flush()
    # So devolve a nota quando o status mudou: quem chama regenera o espelho
    # com o carimbo do evento e nao pode carimbar uma nota que nao mudou.
    return nota if aplicado else None


def _prever_status_por_chave(mapa: dict[str, tuple[str, str | None]], resumo: dict[str, Any]) -> None:
    """Anota o status que um documento impoe a outra nota do mesmo lote.

    Evento de cancelamento/substituicao atinge a nota de chave_afetada; nota
    substituta (chSubstda) atinge a nota antiga. Vale o status de maior
    prioridade, independente da ordem das linhas no indice.
    """
    status = str(resumo.get("status_documento") or "").strip().lower()
    if resumo.get("tipo_xml") == "evento":
        if status not in {"cancelada", "substituida"}:
            return
        alvo = str(resumo.get("chave_afetada") or "").strip()
        previsto = (status, resumo.get("status_rotulo") or status.capitalize())
    else:
        alvo = str(resumo.get("chave_substituida") or "").strip()
        previsto = (STATUS_SUBSTITUIDA, ROTULO_SUBSTITUIDA)
    if not alvo:
        return
    atual = mapa.get(alvo)
    if atual is None or prioridade_status(previsto[0]) > prioridade_status(atual[0]):
        mapa[alvo] = previsto


def _status_por_eventos_gravados(db: Session, empresa_id: int, chave: str) -> tuple[str, str | None] | None:
    """Status imposto por eventos ja gravados para esta chave.

    O evento pode chegar antes da nota (ou numa execucao anterior, com o disco
    do container ja apagado). Sem esta consulta a nota entrava como
    autorizada e ia para as exportacoes mesmo cancelada.
    """
    tipos = {
        str(tipo or "").strip().lower()
        for (tipo,) in db.query(Evento.tipo_evento)
        .filter(Evento.empresa_id == empresa_id, Evento.chave_afetada == chave)
        .filter(Evento.tipo_evento.in_(["cancelada", "substituida"]))
        .all()
    }
    if not tipos:
        return None
    status = max(tipos, key=prioridade_status)
    return status, status.capitalize()


def _vincular_eventos_orfaos(db: Session, empresa_id: int, nota: Nota) -> None:
    """Liga a nota os eventos que chegaram antes dela (nota_id vazio)."""
    (
        db.query(Evento)
        .filter(Evento.empresa_id == empresa_id, Evento.chave_afetada == nota.chave, Evento.nota_id.is_(None))
        .update({Evento.nota_id: nota.id}, synchronize_session=False)
    )


def _status_final_nota(
    status_xml: tuple[str | None, str | None],
    status_previsto: tuple[str, str | None] | None,
    nota_existente: Nota | None,
    status_eventos_gravados: tuple[str, str | None] | None = None,
) -> tuple[str | None, str | None]:
    """Status gravado na nota: o de maior prioridade entre XML, lote e banco.

    Reprocessar o XML original nunca desfaz um cancelamento ou substituicao ja
    conhecidos, e um evento (do lote ou ja gravado) prevalece sobre o status
    "autorizada".
    """
    candidatos = [status_xml]
    if status_previsto is not None:
        candidatos.append(status_previsto)
    if status_eventos_gravados is not None:
        candidatos.append(status_eventos_gravados)
    existente = str(getattr(nota_existente, "status_documento", None) or "").strip().lower()
    if existente in {"cancelada", "substituida"}:
        candidatos.append((existente, getattr(nota_existente, "status_rotulo", None) or existente.capitalize()))
    return max(candidatos, key=lambda item: prioridade_status(item[0]))


def _aplicar_substituicao(
    db: Session,
    storage: StorageService,
    processo: Processo,
    chave_substituida: str | None,
    gerar_pdf_espelho: bool,
    counters: dict[str, Any],
) -> None:
    """A nota substituta (chSubstda) marca a nota antiga como substituida,
    mesmo que o evento de substituicao ainda nao tenha chegado."""
    if not chave_substituida:
        return
    antiga = notas_repo.get_nota_by_chave(db, int(processo.empresa_id), chave_substituida)
    if antiga is None or prioridade_status(antiga.status_documento) >= prioridade_status(STATUS_SUBSTITUIDA):
        return
    notas_repo.update_nota(db, antiga, {"status_documento": STATUS_SUBSTITUIDA, "status_rotulo": ROTULO_SUBSTITUIDA})
    counters["notas_marcadas_substituidas"] = int(counters.get("notas_marcadas_substituidas", 0)) + 1
    if not gerar_pdf_espelho:
        return
    try:
        _regenerar_pdf_espelho_evento(db, storage, processo, antiga, STATUS_SUBSTITUIDA)
    except Exception as exc:
        alert_failure("event_pdf_regeneration", exc, nota_id=antiga.id)
        counters["avisos_pdf"] += 1


def _regenerar_pdf_espelho_evento(
    db: Session,
    storage: StorageService,
    processo: Processo,
    nota: Nota,
    status_documento: str,
) -> None:
    """Regrava o espelho existente assim que um evento muda seu status."""
    if not nota.xml_storage_key:
        raise LegacyIngestionError("Nota afetada pelo evento nao possui XML armazenado.")

    xml_bytes = storage.get_bytes(nota.xml_storage_key)
    with tempfile.TemporaryDirectory(prefix="danfse_evento_") as temp_dir:
        xml_path = Path(temp_dir) / "nota.xml"
        xml_path.write_bytes(xml_bytes)
        dados_pdf = extrair_dados_nfse(xml_path, prefeitura_info=None)
        filename = friendly_pdf_filename(dados_pdf)
        pdf_bytes, _ = DanfseService().generate(xml_bytes, watermark=status_documento)

    storage_key = nota.pdf_espelho_storage_key
    if not storage_key:
        competencia = nota.competencia or nota.data_emissao or hoje_local()
        empresa_cnpj = str(processo.empresa.cnpj if processo.empresa else processo.empresa_id)
        storage_key = build_pdf_espelho_key(
            empresa_cnpj,
            str(competencia.year),
            f"{competencia.month:02d}",
            filename,
        )
        nota.pdf_espelho_storage_key = storage_key

    meta = storage.put_bytes(storage_key, pdf_bytes, content_type="application/pdf")
    nota.pdf_espelho_storage_key = storage_key
    _registrar_arquivo(
        db,
        storage,
        processo.empresa_id,
        processo.id,
        nota.id,
        "pdf_espelho",
        storage_key,
        "application/pdf",
        int(meta.get("size") or len(pdf_bytes)),
        _sha256(pdf_bytes),
        filename,
    )


def _aplicar_campos_fiscais_xml(nota_data: dict[str, Any], resumo: dict[str, Any]) -> None:
    decimal_fields = {
        "valor_pis",
        "valor_cofins",
        "valor_csll",
        "valor_csrf",
        "valor_iss_retido",
        "valor_outras_retencoes",
        "valor_deducoes",
        "valor_desconto_incondicionado",
        "valor_desconto_condicionado",
        "valor_liquido_calculado",
        "irrf_calculado",
        "inss_calculado",
        "pis_calculado",
        "cofins_calculado",
        "csll_calculado",
        "csrf_calculado",
        "iss_calculado",
        "regra_irrf_aliquota",
    }
    text_fields = {
        "subitem_lc116",
        "codigo_servico_raw",
        "codigo_servico_display",
        "codigo_servico_nacional",
        "origem_base_calculo",
        "status_iss",
        "regra_irrf",
        "regra_pcc",
        "regra_inss",
        "regra_observacao",
        "alertas_fiscais",
        "status_irrf",
        "status_inss",
        "status_csrf",
    }
    for field in decimal_fields:
        if field in resumo:
            nota_data[field] = _parse_decimal(str(resumo.get(field) or ""))
    for field in text_fields:
        value = resumo.get(field)
        if value not in {None, ""}:
            nota_data[field] = value
    # Alertas sao o resultado completo do calculo: "nenhum alerta" tambem e
    # um resultado e precisa sobrescrever o texto anterior. Sem isto, uma nota
    # que um dia recebeu "Regra fiscal nao encontrada" (planilha indisponivel
    # naquele momento) carregava o aviso para sempre, mesmo com regra_irrf/
    # regra_pcc ja preenchidos por um recalculo posterior.
    if "alertas_fiscais" in resumo:
        nota_data["alertas_fiscais"] = resumo.get("alertas_fiscais") or None
    if "iss_retido" in resumo:
        nota_data["iss_retido"] = bool(resumo.get("iss_retido"))


def _find_pdf_for_chave(pdf_files: list[Path], chave: str) -> Path | None:
    if not chave:
        return None
    for pdf_path in pdf_files:
        if chave in pdf_path.stem or chave[-8:] in pdf_path.stem:
            return pdf_path
    return None


def _recent_file(path: Path, updated_after: datetime | None) -> bool:
    if updated_after is None:
        return True
    return datetime.fromtimestamp(path.stat().st_mtime) >= updated_after.replace(tzinfo=None)


def _read_index_rows(index_path: Path) -> list[dict[str, str]]:
    text = index_path.read_text(encoding="utf-8-sig", errors="replace").replace("\x00", "")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def _linhas_fora_do_indice(base_dir: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Documentos que o indice unico esconde, lidos de ocorrencias_nsu.csv.

    O indice tem uma linha por chave, e o ADN manda o evento com a chave da
    nota que ele atinge. Quando a nota ja esta no indice, o evento so atualiza
    o NSU da linha e o XML dele nunca e lido: cancelamentos de notas baixadas
    no mesmo container sumiam sem aviso. As ocorrencias guardam cada NSU com
    o proprio XML.
    """
    ocorrencias_path = base_dir / "ocorrencias_nsu.csv"
    if not ocorrencias_path.exists():
        return []
    referenciados = {
        str(resolvido)
        for row in rows
        if (resolvido := _resolve_path(row.get("xml_path", ""), Path.cwd())) is not None
    }
    extras: list[dict[str, str]] = []
    for ocorrencia in _read_index_rows(ocorrencias_path):
        resolvido = _resolve_path(ocorrencia.get("xml_path", ""), Path.cwd())
        if resolvido is None or str(resolvido) in referenciados:
            continue
        referenciados.add(str(resolvido))
        registrado_em = str(ocorrencia.get("registrado_em") or "")
        extras.append(
            {
                "chave": ocorrencia.get("chave", ""),
                "xml_path": ocorrencia.get("xml_path", ""),
                "primeiro_nsu": ocorrencia.get("nsu", ""),
                "ultimo_nsu": ocorrencia.get("nsu", ""),
                "tipo_documento": ocorrencia.get("tipo_documento", ""),
                "data_emissao": registrado_em[:10],
                "atualizado_em": registrado_em,
            }
        )
    return extras


def _arquivo_tipo_pdf(row: dict[str, str]) -> str:
    pdf_tipo = (row.get("pdf_tipo") or "").strip().lower()
    if pdf_tipo == "oficial":
        return "pdf_oficial"
    return "pdf_espelho"


def _build_pdf_key(cnpj: str, ano: str, mes: str, filename: str, tipo: str) -> str:
    if tipo == "pdf_oficial":
        return build_pdf_oficial_key(cnpj, ano, mes, filename)
    return build_pdf_espelho_key(cnpj, ano, mes, filename)


def _put_file_if_needed(storage: StorageService, storage_key: str, source_path: Path, content_type: str) -> tuple[dict[str, Any], bool]:
    data = source_path.read_bytes()
    if storage.exists(storage_key):
        meta = {
            "backend": storage.backend,
            "key": storage_key,
            "size": len(data),
            "content_type": content_type,
        }
        if storage.backend == "local":
            meta["path"] = str(storage.get_path(storage_key))
        return meta, False
    return storage.put_bytes(storage_key, data, content_type=content_type), True


def _registrar_arquivo(
    db: Session,
    storage: StorageService,
    empresa_id: int,
    processo_id: int,
    nota_id: int | None,
    tipo: str,
    storage_key: str,
    content_type: str,
    size: int,
    checksum: str,
    filename: str | None = None,
) -> bool:
    _, created = arquivos_repo.create_arquivo_if_missing(
        db,
        {
            "empresa_id": empresa_id,
            "nota_id": nota_id,
            "processo_id": processo_id,
            "tipo": _canonical_tipo(tipo),
            "storage_backend": storage.backend,
            "storage_bucket": settings.storage_bucket,
            "storage_key": storage_key,
            "filename": filename or Path(storage_key).name,
            "content_type": content_type,
            "tamanho_bytes": size,
            "checksum": checksum,
        },
    )
    return created


def ingerir_saida_legado(
    db: Session,
    storage: StorageService,
    processo: Processo,
    pasta_saida: str | Path,
    max_rows: int | None = None,
    updated_after: datetime | None = None,
    only_chaves: set[str] | None = None,
    commit_every: int | None = None,  # mantido por compatibilidade; cada linha e confirmada sozinha
    start_row: int = 0,
    gerar_pdf_espelho: bool = True,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    base_dir = Path(pasta_saida)
    index_path = base_dir / "index_nfse.csv"
    counters: dict[str, Any] = {
        "ok": True,
        "pasta_saida": str(base_dir),
        "index_encontrado": index_path.exists(),
        "linhas_index": 0,
        "notas_criadas": 0,
        "notas_atualizadas": 0,
        "arquivos_importados": 0,
        "arquivos_existentes": 0,
        "arquivos_registrados": 0,
        "arquivos_ausentes": 0,
        "erros": 0,
        "avisos_pdf": 0,
        "erros_detalhes": [],
    }
    if not index_path.exists():
        return _ingerir_por_varredura(
            db,
            storage,
            processo,
            base_dir,
            counters,
            updated_after=updated_after,
            gerar_pdf_espelho=gerar_pdf_espelho,
        )

    rows = _read_index_rows(index_path)
    rows.extend(_linhas_fora_do_indice(base_dir, rows))
    # Eventos de cancelamento/substituicao podem aparecer depois da linha da
    # nota no indice. Levantamos os estados antes de gerar qualquer espelho
    # para que a ordem das linhas nao produza um PDF autorizado sem carimbo.
    status_evento_por_chave: dict[str, tuple[str, str | None]] = {}
    for event_row in rows:
        event_xml_path = _resolve_path(event_row.get("xml_path", ""), Path.cwd())
        if event_xml_path is None:
            continue
        try:
            event_resumo = _parse_xml_resumo(event_xml_path)
        except Exception:
            # A leitura principal abaixo continua responsavel por registrar
            # XMLs invalidos nos contadores normais da ingestao.
            continue
        _prever_status_por_chave(status_evento_por_chave, event_resumo)
    if only_chaves is not None:
        rows = [row for row in rows if (row.get("chave") or "").strip() in only_chaves]
    if updated_after is not None:
        rows = [
            row
            for row in rows
            if (row_updated_at := _parse_datetime(row.get("atualizado_em", ""))) is not None
            and row_updated_at >= updated_after.replace(tzinfo=None)
        ]
    total_rows = len(rows)
    safe_start_row = min(max(0, int(start_row or 0)), total_rows)
    rows = rows[safe_start_row:]
    if max_rows is not None:
        rows = rows[:max(0, max_rows)]
    counters["linhas_index_total"] = total_rows
    counters["linha_inicial"] = safe_start_row
    counters["linhas_index"] = len(rows)
    counters["proxima_linha_index"] = safe_start_row + len(rows)
    empresa_cnpj = str(processo.empresa.cnpj if processo.empresa else processo.empresa_id)

    linhas_processadas = 0
    for indice_linha, row in enumerate(rows):
        # A ingestao incremental roda em thread separada enquanto o motor
        # legado consulta o ADN. Sem um ponto de parada aqui ela sobrevive ao
        # fim do job e passa a gravar em paralelo com a sessao principal, o
        # que no SQLite estoura "database is locked".
        if should_stop is not None and should_stop():
            counters["interrompido"] = True
            counters["proxima_linha_index"] = safe_start_row + indice_linha
            break
        try:
            chave = (row.get("chave") or "").strip()
            if not chave:
                counters["erros"] += 1
                continue

            ano, mes = _ano_mes(row)
            xml_storage_key = None
            pdf_storage_key = None
            xml_path = _resolve_path(row.get("xml_path", ""), Path.cwd())
            if xml_path is not None:
                xml_storage_key = build_xml_key(empresa_cnpj, ano, mes, xml_path.name)

            pdf_path = _resolve_path(row.get("pdf_path", ""), Path.cwd())
            pdf_tipo = _arquivo_tipo_pdf(row)
            if pdf_path is not None:
                pdf_storage_key = _build_pdf_key(empresa_cnpj, ano, mes, pdf_path.name, pdf_tipo)

            if xml_path is None:
                counters["arquivos_ausentes"] += 1
                continue

            xml_resumo = _parse_xml_resumo(xml_path)
            if xml_resumo.get("tipo_xml") == "evento":
                nsu_evento = _parse_int(row.get("ultimo_nsu", "")) or _parse_int(row.get("primeiro_nsu", ""))
                if xml_storage_key is not None:
                    xml_bytes = xml_path.read_bytes()
                    meta, imported = _put_file_if_needed(storage, xml_storage_key, xml_path, "application/xml")
                    counters["arquivos_importados" if imported else "arquivos_existentes"] += 1
                    if _registrar_arquivo(
                        db,
                        storage,
                        processo.empresa_id,
                        processo.id,
                        None,
                        "xml",
                        xml_storage_key,
                        "application/xml",
                        int(meta["size"]),
                        _sha256(xml_bytes),
                        xml_path.name,
                    ):
                        counters["arquivos_registrados"] += 1
                nota_evento = _registrar_evento_xml(db, processo, xml_resumo, xml_storage_key, nsu_evento)
                if (
                    gerar_pdf_espelho
                    and nota_evento is not None
                    and xml_resumo.get("status_documento") in {"cancelada", "substituida"}
                ):
                    try:
                        _regenerar_pdf_espelho_evento(
                            db,
                            storage,
                            processo,
                            nota_evento,
                            str(xml_resumo["status_documento"]),
                        )
                        counters["pdfs_espelho_regenerados"] = int(counters.get("pdfs_espelho_regenerados", 0)) + 1
                    except Exception as exc:
                        alert_failure("event_pdf_regeneration", exc, nota_id=nota_evento.id)
                        counters["avisos_pdf"] += 1
                        if len(counters["erros_detalhes"]) < 20:
                            counters["erros_detalhes"].append(
                                {
                                    "chave": xml_resumo.get("chave") or "",
                                    "etapa": "pdf_espelho_evento",
                                    "erro": str(exc)[:500],
                                }
                            )
                counters["eventos_importados"] = int(counters.get("eventos_importados", 0)) + 1
                db.commit()
                continue
            nota_existente = notas_repo.get_nota_by_chave(db, int(processo.empresa_id), chave)
            status_documento, status_rotulo = _status_final_nota(
                (xml_resumo.get("status_documento") or None, xml_resumo.get("status_rotulo") or None),
                status_evento_por_chave.get(chave),
                nota_existente,
                _status_por_eventos_gravados(db, int(processo.empresa_id), chave),
            )
            pdf_espelho_path = None
            pdf_espelho_reutilizado = False
            pdf_filename = ""
            if pdf_storage_key is None and gerar_pdf_espelho:
                try:
                    pdf_tipo = "pdf_espelho"
                    dados_pdf = extrair_dados_nfse(xml_path, prefeitura_info=None)
                    pdf_filename = friendly_pdf_filename(dados_pdf)
                    pdf_storage_key = build_pdf_espelho_key(empresa_cnpj, ano, mes, pdf_filename)
                    precisa_carimbo = str(status_documento or "").strip().lower() in {"cancelada", "substituida"}
                    if not precisa_carimbo and storage.exists(pdf_storage_key):
                        # A ingestao pos-processamento revisita todas as linhas
                        # da corrida, quase todas ja ingeridas pela incremental.
                        # Gerar o PDF via PHP (1-2 s cada) para descarta-lo em
                        # seguida custava ~40 min por job de 1.600 notas.
                        pdf_espelho_reutilizado = True
                    else:
                        pdf_espelho_path = _gerar_pdf_espelho_path(
                            xml_path,
                            row,
                            pdf_filename,
                            status_documento=status_documento,
                        )
                except Exception as exc:
                    # Falha ao montar o PDF nao pode impedir que a nota e o
                    # XML, que sao os documentos fiscais de origem, entrem
                    # no banco e aparecam no portal.
                    pdf_tipo = ""
                    pdf_storage_key = None
                    pdf_espelho_path = None
                    counters["avisos_pdf"] += 1
                    if len(counters["erros_detalhes"]) < 20:
                        counters["erros_detalhes"].append(
                            {
                                "chave": chave,
                                "nsu": row.get("ultimo_nsu") or row.get("primeiro_nsu"),
                                "etapa": "pdf_espelho",
                                "erro": str(exc)[:500],
                            }
                        )

            valor_liquido_planilha = _parse_decimal(row.get("valor_liquido", ""))
            valor_liquido_xml = _parse_decimal(xml_resumo.get("valor_liquido", ""))
            nota_data = {
                "empresa_id": processo.empresa_id,
                "processo_id": processo.id,
                "chave": chave,
                "primeiro_nsu": _parse_int(row.get("primeiro_nsu", "")),
                "ultimo_nsu": _parse_int(row.get("ultimo_nsu", "")),
                "numero_nfse": row.get("numero_nfse") or None,
                "data_emissao": _parse_date(row.get("data_emissao", "")),
                "competencia": _parse_date(row.get("competencia", "")),
                "prestador_cnpj": row.get("prestador_cnpj") or None,
                "prestador_nome": row.get("prestador_nome") or None,
                "tomador_cnpj": row.get("tomador_cnpj") or None,
                "tomador_nome": row.get("tomador_nome") or None,
                "valor_servico": _parse_decimal(row.get("valor_servico", "")) or _parse_decimal(xml_resumo.get("valor_servico", "")),
                "valor_base": _parse_decimal(xml_resumo.get("valor_base", "")),
                "iss": _parse_decimal(xml_resumo.get("iss", "")),
                "irrf": _parse_decimal(xml_resumo.get("irrf", "")),
                "inss": _parse_decimal(xml_resumo.get("inss", "")),
                "csrf": _parse_decimal(xml_resumo.get("csrf", "")),
                "valor_liquido": valor_liquido_planilha or valor_liquido_xml,
                # Usa o valor liquido REALMENTE calculado (base - retencoes,
                # considerando ISS retido/IRRF/INSS/CSRF) que ja vem pronto em
                # xml_resumo (via calcular_retencoes_esperadas). Antes isto
                # comparava planilha x XML (dois valores informados, quase
                # sempre iguais entre si) e nunca detectava divergencia real,
                # deixando o comparativo de tributos com um "OK" que nao
                # batia com o alerta fiscal (que usa o valor calculado certo).
                "valor_liquido_correto": _parse_decimal(xml_resumo.get("valor_liquido_correto", "")),
                "status_valor_liquido": xml_resumo.get("status_valor_liquido") or None,
                "simples_xml": row.get("simples_xml") or xml_resumo.get("simples_xml") or None,
                "simples_nacional_xml": row.get("simples_nacional_xml") or xml_resumo.get("simples_nacional_xml") or None,
                "status_simples_nacional": xml_resumo.get("status_simples_nacional") or None,
                "incidencia_iss": row.get("incidencia_iss") or xml_resumo.get("incidencia_iss") or None,
                "municipio": row.get("municipio") or xml_resumo.get("municipio") or None,
                "codigo_servico": row.get("codigo_servico") or xml_resumo.get("codigo_servico") or None,
                "descricao_servico_nacional": xml_resumo.get("descricao_servico_nacional") or None,
                "descricao_servico_detalhada": xml_resumo.get("descricao_servico_detalhada") or None,
                "aliquota_iss": _parse_decimal(xml_resumo.get("aliquota_iss", "")),
                "status_documento": status_documento,
                "status_rotulo": status_rotulo,
                "xml_storage_key": xml_storage_key,
                "pdf_oficial_storage_key": pdf_storage_key if pdf_tipo == "pdf_oficial" else None,
                "pdf_espelho_storage_key": pdf_storage_key if pdf_tipo == "pdf_espelho" else None,
            }
            _aplicar_campos_fiscais_xml(nota_data, xml_resumo)
            nota, created = notas_repo.upsert_nota_by_chave(db, processo.empresa_id, chave, nota_data)
            if created:
                counters["notas_criadas"] += 1
            else:
                counters["notas_atualizadas"] += 1
            _vincular_eventos_orfaos(db, int(processo.empresa_id), nota)
            _aplicar_substituicao(
                db, storage, processo, xml_resumo.get("chave_substituida"), gerar_pdf_espelho, counters
            )

            if xml_path is not None and xml_storage_key is not None:
                xml_bytes = xml_path.read_bytes()
                meta, imported = _put_file_if_needed(storage, xml_storage_key, xml_path, "application/xml")
                counters["arquivos_importados" if imported else "arquivos_existentes"] += 1
                if _registrar_arquivo(
                    db,
                    storage,
                    processo.empresa_id,
                    processo.id,
                    nota.id,
                    "xml",
                    xml_storage_key,
                    "application/xml",
                    int(meta["size"]),
                    _sha256(xml_bytes),
                    xml_path.name,
                ):
                    counters["arquivos_registrados"] += 1
            elif row.get("xml_path"):
                counters["arquivos_ausentes"] += 1

            if pdf_path is not None and pdf_storage_key is not None:
                pdf_bytes = pdf_path.read_bytes()
                meta, imported = _put_file_if_needed(storage, pdf_storage_key, pdf_path, "application/pdf")
                counters["arquivos_importados" if imported else "arquivos_existentes"] += 1
                if _registrar_arquivo(
                    db,
                    storage,
                    processo.empresa_id,
                    processo.id,
                    nota.id,
                    pdf_tipo,
                    pdf_storage_key,
                    "application/pdf",
                    int(meta["size"]),
                    _sha256(pdf_bytes),
                    pdf_path.name,
                ):
                    counters["arquivos_registrados"] += 1
            elif pdf_espelho_reutilizado and pdf_storage_key is not None:
                pdf_bytes = storage.get_bytes(pdf_storage_key)
                counters["arquivos_existentes"] += 1
                if _registrar_arquivo(
                    db,
                    storage,
                    processo.empresa_id,
                    processo.id,
                    nota.id,
                    pdf_tipo,
                    pdf_storage_key,
                    "application/pdf",
                    len(pdf_bytes),
                    _sha256(pdf_bytes),
                    pdf_filename or Path(pdf_storage_key).name,
                ):
                    counters["arquivos_registrados"] += 1
            elif pdf_espelho_path is not None and pdf_storage_key is not None:
                pdf_bytes = pdf_espelho_path.read_bytes()
                if storage.exists(pdf_storage_key):
                    if str(status_documento or "").strip().lower() in {"cancelada", "substituida"}:
                        # O status pode ter chegado por evento depois da
                        # primeira geracao. Substitui o espelho antigo para
                        # garantir que o arquivo entregue pelo portal tenha o
                        # carimbo, preservando a mesma chave de storage.
                        meta = storage.put_bytes(pdf_storage_key, pdf_bytes, content_type="application/pdf")
                        imported = True
                        counters["pdfs_espelho_regenerados"] = int(counters.get("pdfs_espelho_regenerados", 0)) + 1
                    else:
                        meta = {
                            "size": len(storage.get_bytes(pdf_storage_key)),
                        }
                        imported = False
                else:
                    meta = storage.put_bytes(pdf_storage_key, pdf_bytes, content_type="application/pdf")
                    imported = True
                    counters["pdfs_espelho_gerados"] = int(counters.get("pdfs_espelho_gerados", 0)) + 1
                counters["arquivos_importados" if imported else "arquivos_existentes"] += 1
                if _registrar_arquivo(
                    db,
                    storage,
                    processo.empresa_id,
                    processo.id,
                    nota.id,
                    "pdf_espelho",
                    pdf_storage_key,
                    "application/pdf",
                    int(meta["size"]),
                    _sha256(pdf_bytes),
                    pdf_espelho_path.name,
                ):
                    counters["arquivos_registrados"] += 1
            elif row.get("pdf_path"):
                counters["arquivos_ausentes"] += 1
            linhas_processadas += 1
            # Cada linha e confirmada sozinha: com commits em blocos, o
            # rollback de uma linha com erro desfazia as anteriores do bloco,
            # que ja tinham sido contadas e enviadas ao storage, e elas nunca
            # voltavam (o cursor da ingestao incremental ja tinha passado).
            db.commit()
        except Exception as exc:
            # A falha desfaz so esta linha; as anteriores ja estao gravadas.
            db.rollback()
            counters["erros"] += 1
            if len(counters["erros_detalhes"]) < 20:
                counters["erros_detalhes"].append(
                    {
                        "chave": (row.get("chave") or "").strip(),
                        "nsu": row.get("ultimo_nsu") or row.get("primeiro_nsu"),
                        "etapa": "ingestao",
                        "erro": str(exc)[:500],
                    }
                )

    return counters


def _ingerir_por_varredura(
    db: Session,
    storage: StorageService,
    processo: Processo,
    base_dir: Path,
    counters: dict[str, Any],
    updated_after: datetime | None = None,
    gerar_pdf_espelho: bool = True,
) -> dict[str, Any]:
    xml_files = [path for path in sorted(base_dir.rglob("*.xml")) if _recent_file(path, updated_after)]
    pdf_files = [path for path in sorted(base_dir.rglob("*.pdf")) if _recent_file(path, updated_after)]
    counters["fallback_varredura"] = True
    counters["xmls_encontrados"] = len(xml_files)
    counters["pdfs_encontrados"] = len(pdf_files)
    empresa_cnpj = str(processo.empresa.cnpj if processo.empresa else processo.empresa_id)

    resumos_por_xml: dict[Path, dict[str, str]] = {}
    status_evento_por_chave: dict[str, tuple[str, str | None]] = {}
    for candidate in xml_files:
        try:
            candidate_resumo = _parse_xml_resumo(candidate)
        except Exception:
            continue
        resumos_por_xml[candidate] = candidate_resumo
        _prever_status_por_chave(status_evento_por_chave, candidate_resumo)

    for xml_path in xml_files:
        try:
            resumo = resumos_por_xml.get(xml_path) or _parse_xml_resumo(xml_path)
            if resumo.get("tipo_xml") == "evento":
                ano, mes = _ano_mes(resumo)
                xml_storage_key = build_xml_key(empresa_cnpj, ano, mes, xml_path.name)
                xml_bytes = xml_path.read_bytes()
                meta, imported = _put_file_if_needed(storage, xml_storage_key, xml_path, "application/xml")
                counters["arquivos_importados" if imported else "arquivos_existentes"] += 1
                if _registrar_arquivo(
                    db,
                    storage,
                    processo.empresa_id,
                    processo.id,
                    None,
                    "xml",
                    xml_storage_key,
                    "application/xml",
                    int(meta["size"]),
                    _sha256(xml_bytes),
                    xml_path.name,
                ):
                    counters["arquivos_registrados"] += 1
                nota_evento = _registrar_evento_xml(db, processo, resumo, xml_storage_key, None)
                if (
                    gerar_pdf_espelho
                    and nota_evento is not None
                    and resumo.get("status_documento") in {"cancelada", "substituida"}
                ):
                    try:
                        _regenerar_pdf_espelho_evento(
                            db,
                            storage,
                            processo,
                            nota_evento,
                            str(resumo["status_documento"]),
                        )
                        counters["pdfs_espelho_regenerados"] = int(counters.get("pdfs_espelho_regenerados", 0)) + 1
                    except Exception as exc:
                        alert_failure("event_pdf_regeneration", exc, nota_id=nota_evento.id)
                        counters["avisos_pdf"] += 1
                        if len(counters["erros_detalhes"]) < 20:
                            counters["erros_detalhes"].append(
                                {
                                    "chave": resumo.get("chave") or "",
                                    "etapa": "pdf_espelho_evento",
                                    "erro": str(exc)[:500],
                                }
                            )
                counters["eventos_importados"] = int(counters.get("eventos_importados", 0)) + 1
                db.commit()
                continue
            chave = (resumo.get("chave") or "").strip()
            if not chave:
                counters["erros"] += 1
                continue

            nota_existente = notas_repo.get_nota_by_chave(db, int(processo.empresa_id), chave)
            status_documento, status_rotulo = _status_final_nota(
                (resumo.get("status_documento") or None, resumo.get("status_rotulo") or None),
                status_evento_por_chave.get(chave),
                nota_existente,
                _status_por_eventos_gravados(db, int(processo.empresa_id), chave),
            )

            ano, mes = _ano_mes(resumo)
            xml_storage_key = build_xml_key(empresa_cnpj, ano, mes, xml_path.name)
            pdf_path = _find_pdf_for_chave(pdf_files, chave)
            pdf_storage_key = build_pdf_oficial_key(empresa_cnpj, ano, mes, pdf_path.name) if pdf_path else None
            pdf_espelho_path = None
            if pdf_storage_key is None and gerar_pdf_espelho:
                dados_pdf = extrair_dados_nfse(xml_path, prefeitura_info=None)
                pdf_filename = friendly_pdf_filename(dados_pdf)
                pdf_storage_key = build_pdf_espelho_key(empresa_cnpj, ano, mes, pdf_filename)
                pdf_espelho_path = _gerar_pdf_espelho_path(
                    xml_path,
                    resumo,
                    pdf_filename,
                    status_documento=status_documento,
                )

            nota_data = {
                "empresa_id": processo.empresa_id,
                "processo_id": processo.id,
                "chave": chave,
                "primeiro_nsu": None,
                "ultimo_nsu": None,
                "numero_nfse": resumo.get("numero_nfse") or None,
                "data_emissao": _parse_date(resumo.get("data_emissao", "")),
                "competencia": _parse_date(resumo.get("competencia", "")),
                "prestador_cnpj": resumo.get("prestador_cnpj") or None,
                "prestador_nome": resumo.get("prestador_nome") or None,
                "tomador_cnpj": resumo.get("tomador_cnpj") or None,
                "tomador_nome": resumo.get("tomador_nome") or None,
                "valor_servico": _parse_decimal(resumo.get("valor_servico", "")),
                "valor_base": _parse_decimal(resumo.get("valor_base", "")),
                "iss": _parse_decimal(resumo.get("iss", "")),
                "irrf": _parse_decimal(resumo.get("irrf", "")),
                "inss": _parse_decimal(resumo.get("inss", "")),
                "csrf": _parse_decimal(resumo.get("csrf", "")),
                "valor_liquido": _parse_decimal(resumo.get("valor_liquido", "")),
                "valor_liquido_correto": _parse_decimal(resumo.get("valor_liquido_correto", "")),
                "status_valor_liquido": resumo.get("status_valor_liquido") or None,
                "simples_xml": resumo.get("simples_xml") or None,
                "simples_nacional_xml": resumo.get("simples_nacional_xml") or None,
                "status_simples_nacional": resumo.get("status_simples_nacional") or None,
                "incidencia_iss": resumo.get("incidencia_iss") or None,
                "municipio": resumo.get("municipio") or None,
                "codigo_servico": resumo.get("codigo_servico") or None,
                "descricao_servico_nacional": resumo.get("descricao_servico_nacional") or None,
                "descricao_servico_detalhada": resumo.get("descricao_servico_detalhada") or None,
                "aliquota_iss": _parse_decimal(resumo.get("aliquota_iss", "")),
                "status_documento": status_documento,
                "status_rotulo": status_rotulo,
                "xml_storage_key": xml_storage_key,
                "pdf_oficial_storage_key": pdf_storage_key if pdf_path is not None else None,
                "pdf_espelho_storage_key": pdf_storage_key if pdf_path is None else None,
            }
            _aplicar_campos_fiscais_xml(nota_data, resumo)
            nota, created = notas_repo.upsert_nota_by_chave(db, processo.empresa_id, chave, nota_data)
            counters["notas_criadas" if created else "notas_atualizadas"] += 1
            _vincular_eventos_orfaos(db, int(processo.empresa_id), nota)
            _aplicar_substituicao(
                db, storage, processo, resumo.get("chave_substituida"), gerar_pdf_espelho, counters
            )

            xml_bytes = xml_path.read_bytes()
            meta, imported = _put_file_if_needed(storage, xml_storage_key, xml_path, "application/xml")
            counters["arquivos_importados" if imported else "arquivos_existentes"] += 1
            if _registrar_arquivo(
                db,
                storage,
                processo.empresa_id,
                processo.id,
                nota.id,
                "xml",
                xml_storage_key,
                "application/xml",
                int(meta["size"]),
                _sha256(xml_bytes),
                xml_path.name,
            ):
                counters["arquivos_registrados"] += 1

            if pdf_path is not None and pdf_storage_key is not None:
                pdf_bytes = pdf_path.read_bytes()
                meta, imported = _put_file_if_needed(storage, pdf_storage_key, pdf_path, "application/pdf")
                counters["arquivos_importados" if imported else "arquivos_existentes"] += 1
                if _registrar_arquivo(
                    db,
                    storage,
                    processo.empresa_id,
                    processo.id,
                    nota.id,
                    "pdf_oficial",
                    pdf_storage_key,
                    "application/pdf",
                    int(meta["size"]),
                    _sha256(pdf_bytes),
                    pdf_path.name,
                ):
                    counters["arquivos_registrados"] += 1
            elif pdf_espelho_path is not None and pdf_storage_key is not None:
                pdf_bytes = pdf_espelho_path.read_bytes()
                if storage.exists(pdf_storage_key):
                    if str(status_documento or "").strip().lower() in {"cancelada", "substituida"}:
                        meta = storage.put_bytes(pdf_storage_key, pdf_bytes, content_type="application/pdf")
                        imported = True
                        counters["pdfs_espelho_regenerados"] = int(counters.get("pdfs_espelho_regenerados", 0)) + 1
                    else:
                        meta = {
                            "size": len(storage.get_bytes(pdf_storage_key)),
                        }
                        imported = False
                else:
                    meta = storage.put_bytes(pdf_storage_key, pdf_bytes, content_type="application/pdf")
                    imported = True
                    counters["pdfs_espelho_gerados"] = int(counters.get("pdfs_espelho_gerados", 0)) + 1
                counters["arquivos_importados" if imported else "arquivos_existentes"] += 1
                if _registrar_arquivo(
                    db,
                    storage,
                    processo.empresa_id,
                    processo.id,
                    nota.id,
                    "pdf_espelho",
                    pdf_storage_key,
                    "application/pdf",
                    int(meta["size"]),
                    _sha256(pdf_bytes),
                    pdf_espelho_path.name,
                ):
                    counters["arquivos_registrados"] += 1
            # Mesma regra da ingestao pelo indice: uma linha por transacao.
            db.commit()
        except Exception:
            db.rollback()
            counters["erros"] += 1

    return counters
