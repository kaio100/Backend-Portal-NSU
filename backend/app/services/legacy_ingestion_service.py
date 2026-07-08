from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Evento, Nota, Processo
from backend.app.repositories import arquivos_repo, notas_repo
from backend.app.services.nfse_pdf_service import NfsePdfService, friendly_pdf_filename
from backend.app.services.nfse_xml_parser import extrair_dados_nfse
from backend.app.services.operational_fields_service import (
    calcular_status_simples_nacional_xml,
    normalizar_simples_xml,
    simples_xml_from_codes,
)
from backend.app.services.retencoes_calculo_service import calcular_retencoes_esperadas, parse_decimal_xml
from backend.app.services.retencoes_regras_service import obter_regra_por_subitem, resolver_subitem_lc116
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


def _decimal_equal(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return False
    return left.quantize(Decimal("0.01")) == right.quantize(Decimal("0.01"))


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


def _gerar_pdf_espelho_path(xml_path: Path, row: dict[str, str], filename: str) -> Path:
    output_dir = Path(settings.worker_temp_dir) / "pdf_espelho"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    dados = extrair_dados_nfse(xml_path, prefeitura_info=None)
    return NfsePdfService().gerar_danfse_espelho(dados, output_path)


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


def _bool_iss_retido(value: str, valor_iss_retido: str = "") -> bool:
    text = (value or "").strip().lower()
    if text in {"1", "s", "sim", "true", "retido"}:
        return True
    if text in {"2", "0", "n", "nao", "não", "false"}:
        return False
    return (parse_decimal_xml(valor_iss_retido) or Decimal("0")) > 0


def _to_text(value) -> str:
    return "" if value is None else str(value)


def _xml_contains_text(root: ElementTree.Element, pattern: str) -> bool:
    wanted = pattern.lower()
    for element in root.iter():
        tag = _local_name(element.tag)
        text = (element.text or "").strip()
        if wanted in tag or wanted in text.lower():
            return True
    return False


def _status_from_xml(root: ElementTree.Element) -> tuple[str | None, str | None]:
    cstat = _find_text(root, "cStat")
    motivo = _find_text(root, "xMotivo", "motivo", "descEvento", "xEvento", "xDesc")
    text_blob = " ".join((element.text or "") for element in root.iter()).lower()

    if _xml_contains_text(root, "cancel") or "cancelamento" in text_blob:
        return "cancelada", "Cancelada"
    if _xml_contains_text(root, "subst") or "substitu" in text_blob:
        return "substituida", "Substituida"
    if cstat in {"100", "107"}:
        return "autorizada", "Autorizada"
    if cstat == "101" or "erro" in motivo.lower():
        return "erro_emissao", "Erro na emissao"
    if cstat:
        return f"cstat_{cstat}", motivo or f"Codigo {cstat}"
    if motivo:
        return "evento", motivo
    return None, None


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
    root_name = _local_name(root.tag)
    is_evento = root_name == "evento" or bool(_find_text(root, "chNFSe", "chSubstda")) and _xml_contains_text(root, "evento")
    prestador_cnpj = _text_digits(_find_text(root, "CnpjPrestador", "CNPJPrestador", "CpfCnpjPrestador", "Cnpj"))
    tomador_cnpj = _text_digits(_find_text(root, "CnpjTomador", "CNPJTomador", "CpfCnpjTomador"))
    status_documento, status_rotulo = _status_from_xml(root)
    simples_xml = extrair_simples_nacional_xml(root)
    valor_liquido = _find_text(root, "ValorLiquidoNfse", "ValorLiquido", "vLiq")
    valor_servico = _find_text(root, "ValorServicos", "ValorServico", "vServ")
    valor_base = _find_text(root, "vBC", "BaseCalculo", "ValorBaseCalculo") or valor_servico
    origem_base = "xml" if _find_text(root, "vBC", "BaseCalculo", "ValorBaseCalculo") else "fallback_valor_servico"
    codigo_servico = _find_text(root, "cTribNac")
    pis = _find_text(root, "vPis", "ValorPis", "ValorPIS", "ValorPisRetido")
    cofins = _find_text(root, "vCofins", "ValorCofins", "ValorCOFINS", "ValorCofinsRetido")
    csll = _find_text(root, "vRetCSLL", "vCSLL", "ValorCsll", "ValorCSLL", "ValorCsllRetido")
    csrf_direto = _find_text(root, "ValorCsrf", "ValorCSRF", "ContribuicoesSociaisRetidas", "ValorContribuicoesSociaisRetidas")
    csrf = csrf_direto or _sum_existing_decimals(pis, cofins, csll)
    valor_iss_retido = _find_text(root, "vISSRet", "ValorIssRetido", "ValorISSRetido")
    iss_retido = _bool_iss_retido(_find_text(root, "tpRetISSQN", "ISSRetido", "IssRetido", "indISSRet", "RetencaoISS"), valor_iss_retido)
    subitem_lc116 = resolver_subitem_lc116(
        {
            "cTribNac": codigo_servico,
            "cServ": _find_text(root, "cServ"),
            "cServMun": _find_text(root, "cServMun"),
            "ItemListaServico": _find_text(root, "ItemListaServico", "itemListaServico"),
            "CodigoServico": _find_text(root, "CodigoServico"),
            "CodigoTributacaoMunicipio": _find_text(root, "CodigoTributacaoMunicipio"),
        }
    )
    regra = obter_regra_por_subitem(subitem_lc116)
    dados_fiscais = {
        "valor_servico": valor_servico,
        "valor_base_calculo": valor_base,
        "aliquota_iss": _find_text(root, "pAliqAplic", "pAliq", "Aliquota", "AliquotaServicos", "AliquotaIss"),
        "valor_iss": _find_text(root, "vISSQN", "ValorIss", "ValorISS", "ValorIssqn"),
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
    }
    calculo = calcular_retencoes_esperadas(dados_fiscais, regra)
    return {
        "tipo_xml": "evento" if is_evento else "nota",
        "chave": _extract_chave_from_xml(xml_path, root),
        "chave_afetada": _text_digits(_find_text(root, "chNFSe", "chSubstda")),
        "descricao_evento": _find_text(root, "xDesc", "descEvento", "xEvento"),
        "motivo_evento": _find_text(root, "xMotivo", "motivo"),
        "numero_nfse": _find_text(root, "Numero", "NumeroNfse", "nNFSe"),
        "data_emissao": _find_text(root, "DataEmissao", "dhEmi", "DataHoraEmissao")[:10],
        "competencia": _find_text(root, "Competencia", "DataCompetencia")[:10],
        "prestador_cnpj": prestador_cnpj,
        "prestador_nome": _find_text(root, "RazaoSocialPrestador", "NomePrestador", "xNome"),
        "tomador_cnpj": tomador_cnpj,
        "tomador_nome": _find_text(root, "RazaoSocialTomador", "NomeTomador"),
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
        "codigo_servico_nacional": codigo_servico,
        "subitem_lc116": subitem_lc116 or "",
        "descricao_servico_nacional": _find_text(root, "xTribNac"),
        "descricao_servico_detalhada": _find_text(root, "xDescServ"),
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
) -> None:
    chave_evento = resumo.get("chave") or None
    chave_afetada = resumo.get("chave_afetada") or None
    status_documento = resumo.get("status_documento") or None
    status_rotulo = resumo.get("status_rotulo") or None
    nota = None
    if chave_afetada:
        nota = notas_repo.get_nota_by_chave(db, int(processo.empresa_id), chave_afetada)
        if nota is not None and status_documento in {"cancelada", "substituida"}:
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
                tipo_evento=status_documento,
                descricao=resumo.get("descricao_evento") or resumo.get("motivo_evento"),
                xml_storage_key=xml_storage_key,
                nsu=nsu,
            )
        )
        db.flush()


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
        return {
            "backend": storage.backend,
            "key": storage_key,
            "path": str(storage.get_path(storage_key)),
            "size": len(data),
            "content_type": content_type,
        }, False
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
    }
    if not index_path.exists():
        return _ingerir_por_varredura(db, storage, processo, base_dir, counters, updated_after=updated_after)

    rows = _read_index_rows(index_path)
    if updated_after is not None:
        rows = [
            row
            for row in rows
            if (row_updated_at := _parse_datetime(row.get("atualizado_em", ""))) is not None
            and row_updated_at >= updated_after.replace(tzinfo=None)
        ]
    if max_rows is not None:
        rows = rows[:max(0, max_rows)]
    counters["linhas_index"] = len(rows)
    empresa_cnpj = str(processo.empresa.cnpj if processo.empresa else processo.empresa_id)

    for row in rows:
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
                _registrar_evento_xml(db, processo, xml_resumo, xml_storage_key, nsu_evento)
                counters["eventos_importados"] = int(counters.get("eventos_importados", 0)) + 1
                continue
            status_documento = row.get("status_documento") or xml_resumo.get("status_documento") or None
            status_rotulo = row.get("status_rotulo") or xml_resumo.get("status_rotulo") or None
            pdf_espelho_path = None
            if pdf_storage_key is None:
                pdf_tipo = "pdf_espelho"
                dados_pdf = extrair_dados_nfse(xml_path, prefeitura_info=None)
                pdf_filename = friendly_pdf_filename(dados_pdf)
                pdf_storage_key = build_pdf_espelho_key(empresa_cnpj, ano, mes, pdf_filename)
                pdf_espelho_path = _gerar_pdf_espelho_path(xml_path, row, pdf_filename)

            valor_liquido_planilha = _parse_decimal(row.get("valor_liquido", ""))
            valor_liquido_xml = _parse_decimal(xml_resumo.get("valor_liquido", ""))
            status_valor_liquido = None
            if valor_liquido_xml is not None:
                status_valor_liquido = "OK" if _decimal_equal(valor_liquido_planilha or valor_liquido_xml, valor_liquido_xml) else "Divergente"
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
                "valor_liquido_correto": valor_liquido_xml,
                "status_valor_liquido": status_valor_liquido,
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
            elif pdf_espelho_path is not None and pdf_storage_key is not None:
                pdf_bytes = pdf_espelho_path.read_bytes()
                if storage.exists(pdf_storage_key):
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
        except Exception:
            counters["erros"] += 1

    return counters


def _ingerir_por_varredura(
    db: Session,
    storage: StorageService,
    processo: Processo,
    base_dir: Path,
    counters: dict[str, Any],
    updated_after: datetime | None = None,
) -> dict[str, Any]:
    xml_files = [path for path in sorted(base_dir.rglob("*.xml")) if _recent_file(path, updated_after)]
    pdf_files = [path for path in sorted(base_dir.rglob("*.pdf")) if _recent_file(path, updated_after)]
    counters["fallback_varredura"] = True
    counters["xmls_encontrados"] = len(xml_files)
    counters["pdfs_encontrados"] = len(pdf_files)
    empresa_cnpj = str(processo.empresa.cnpj if processo.empresa else processo.empresa_id)

    for xml_path in xml_files:
        try:
            resumo = _parse_xml_resumo(xml_path)
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
                _registrar_evento_xml(db, processo, resumo, xml_storage_key, None)
                counters["eventos_importados"] = int(counters.get("eventos_importados", 0)) + 1
                continue
            chave = (resumo.get("chave") or "").strip()
            if not chave:
                counters["erros"] += 1
                continue

            ano, mes = _ano_mes(resumo)
            xml_storage_key = build_xml_key(empresa_cnpj, ano, mes, xml_path.name)
            pdf_path = _find_pdf_for_chave(pdf_files, chave)
            pdf_storage_key = build_pdf_oficial_key(empresa_cnpj, ano, mes, pdf_path.name) if pdf_path else None
            pdf_espelho_path = None
            if pdf_storage_key is None:
                dados_pdf = extrair_dados_nfse(xml_path, prefeitura_info=None)
                pdf_filename = friendly_pdf_filename(dados_pdf)
                pdf_storage_key = build_pdf_espelho_key(empresa_cnpj, ano, mes, pdf_filename)
                pdf_espelho_path = _gerar_pdf_espelho_path(xml_path, resumo, pdf_filename)

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
                "status_documento": resumo.get("status_documento") or None,
                "status_rotulo": resumo.get("status_rotulo") or None,
                "xml_storage_key": xml_storage_key,
                "pdf_oficial_storage_key": pdf_storage_key if pdf_path is not None else None,
                "pdf_espelho_storage_key": pdf_storage_key if pdf_path is None else None,
            }
            _aplicar_campos_fiscais_xml(nota_data, resumo)
            nota, created = notas_repo.upsert_nota_by_chave(db, processo.empresa_id, chave, nota_data)
            counters["notas_criadas" if created else "notas_atualizadas"] += 1

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
        except Exception:
            counters["erros"] += 1

    return counters
