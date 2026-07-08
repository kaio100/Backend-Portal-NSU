from __future__ import annotations

import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.db.models import Arquivo, Empresa, Evento, Nota, NsuControle, Processo
from backend.app.repositories import arquivos_repo, notas_repo, processos_repo
from backend.app.schemas.notas import NotasDownloadFiltros
from backend.app.services import legacy_ingestion_service, notas_service
from backend.app.services.operational_fields_service import aplicar_campos_operacionais
from backend.app.services.storage_service import StorageService, get_storage_service


class PortalSupportError(RuntimeError):
    pass


def _canonical_tipo_arquivo(tipo: str | None) -> str:
    normalized = (tipo or "").lower()
    if normalized == "xml":
        return "XML"
    if normalized in {"pdf_original", "pdf_oficial", "oficial"}:
        return "PDF_ORIGINAL"
    if normalized in {"pdf_espelho", "espelho"}:
        return "PDF_ESPELHO"
    return tipo or "OUTRO"


def _tipo_documento_frontend(tipo: str | None) -> str:
    canonical = _canonical_tipo_arquivo(tipo)
    if canonical == "XML":
        return "xml"
    if canonical in {"PDF_ORIGINAL", "PDF_ESPELHO"}:
        return "pdf"
    return canonical.lower()


def _matches_tipo_arquivo(arquivo: Arquivo, tipo: str) -> bool:
    tipo_norm = tipo.lower()
    canonical = _canonical_tipo_arquivo(arquivo.tipo).lower()
    frontend = _tipo_documento_frontend(arquivo.tipo)
    filename = (_nome_arquivo(arquivo) or "").lower()
    content_type = (arquivo.content_type or "").lower()
    if tipo_norm in {canonical, frontend}:
        return True
    if tipo_norm == "xlsx":
        return filename.endswith(".xlsx") or "spreadsheet" in content_type
    if tipo_norm == "csv":
        return filename.endswith(".csv") or "csv" in content_type
    if tipo_norm == "zip":
        return filename.endswith(".zip") or "zip" in content_type
    if tipo_norm == "relatorio":
        return canonical == "relatorio" or filename.endswith((".xlsx", ".csv"))
    if tipo_norm == "outro":
        return frontend not in {"xml", "pdf"} and canonical not in {"relatorio"}
    return False


def _nome_arquivo(arquivo: Arquivo) -> str:
    if arquivo.filename:
        return arquivo.filename
    return (arquivo.storage_key or "").replace("\\", "/").split("/")[-1] or f"arquivo_{arquivo.id}"


def _arquivo_disponivel(storage: StorageService | None, arquivo: Arquivo) -> bool:
    if storage is None:
        return True
    try:
        return storage.exists(arquivo.storage_key)
    except Exception:
        return False


def arquivo_item(arquivo: Arquivo, storage: StorageService | None = None) -> dict:
    return {
        "id": int(arquivo.id),
        "arquivo_id": int(arquivo.id),
        "nota_id": arquivo.nota_id,
        "processo_id": arquivo.processo_id,
        "tipo": _tipo_documento_frontend(arquivo.tipo),
        "tipo_canonico": _canonical_tipo_arquivo(arquivo.tipo),
        "nome": _nome_arquivo(arquivo),
        "filename": _nome_arquivo(arquivo),
        "content_type": arquivo.content_type,
        "tamanho": arquivo.tamanho_bytes,
        "size_bytes": arquivo.tamanho_bytes,
        "disponivel": _arquivo_disponivel(storage, arquivo),
        "download_url": None,
        "criado_em": arquivo.created_at,
        "created_at": arquivo.created_at,
    }


def listar_documentos_nota(db: Session, nota_id: int, storage: StorageService | None = None) -> dict:
    notas_service.obter_nota(db, nota_id)
    arquivos = notas_service.listar_arquivos_nota(db, nota_id)
    return {
        "nota_id": nota_id,
        "items": [arquivo_item(arquivo, storage) for arquivo in arquivos],
        "total": len(arquivos),
    }


def _arquivo_id_por_storage(db: Session, storage_key: str | None) -> int | None:
    if not storage_key:
        return None
    arquivo = arquivos_repo.get_arquivo_by_storage_key(db, storage_key)
    return int(arquivo.id) if arquivo is not None else None


def evento_item(db: Session, evento: Evento) -> dict:
    return {
        "id": int(evento.id),
        "tipo_evento": evento.tipo_evento,
        "codigo_evento": evento.tipo_evento,
        "descricao": evento.descricao,
        "data_evento": evento.data_evento or evento.created_at,
        "protocolo": None,
        "chave_afetada": evento.chave_afetada,
        "status": evento.tipo_evento,
        "arquivo_id": _arquivo_id_por_storage(db, evento.xml_storage_key),
        "nsu": evento.nsu,
    }


def listar_eventos_nota(db: Session, nota_id: int) -> dict:
    nota = notas_service.obter_nota(db, nota_id)
    eventos = (
        db.query(Evento)
        .filter(or_(Evento.nota_id == nota_id, Evento.chave_afetada == nota.chave))
        .order_by(Evento.data_evento.desc().nullslast(), Evento.created_at.desc(), Evento.id.desc())
        .all()
    )
    return {
        "nota_id": nota_id,
        "items": [evento_item(db, evento) for evento in eventos],
        "total": len(eventos),
    }


def listar_eventos(
    db: Session,
    empresa_id: int | None = None,
    nota_id: int | None = None,
    chave_afetada: str | None = None,
    tipo_evento: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    query = db.query(Evento)
    if empresa_id is not None:
        query = query.filter(Evento.empresa_id == empresa_id)
    if nota_id is not None:
        query = query.filter(Evento.nota_id == nota_id)
    if chave_afetada:
        query = query.filter(Evento.chave_afetada == chave_afetada)
    if tipo_evento:
        query = query.filter(Evento.tipo_evento == tipo_evento)
    if data_inicio is not None:
        query = query.filter(Evento.data_evento >= data_inicio)
    if data_fim is not None:
        query = query.filter(Evento.data_evento <= data_fim)
    total = query.count()
    eventos = (
        query.order_by(Evento.data_evento.desc().nullslast(), Evento.created_at.desc(), Evento.id.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 500))
        .all()
    )
    return {"items": [evento_item(db, evento) for evento in eventos], "total": total}


def comparar_tributos_nota(db: Session, nota_id: int) -> dict:
    nota = notas_service.obter_nota(db, nota_id)
    specs = [
        ("IRRF", "irrf", "irrf_calculado", "status_irrf", "IRRF esperado diferente do informado"),
        ("CSRF", "csrf", "csrf_calculado", "status_csrf", "CSRF esperado diferente do informado"),
        ("INSS", "inss", None, "status_inss", "INSS esperado diferente do informado"),
        ("ISS", "iss", "iss_calculado", None, "ISS esperado diferente do informado"),
        ("VALOR_LIQUIDO", "valor_liquido", "valor_liquido_correto", "status_valor_liquido", "Valor liquido esperado diferente do informado"),
    ]
    items: list[dict] = []
    for tributo, informado_field, calculado_field, status_field, observacao in specs:
        informado = getattr(nota, informado_field, None)
        calculado = getattr(nota, calculado_field, None) if calculado_field else None
        status = getattr(nota, status_field, None) if status_field else None
        if informado is None and calculado is None and not status:
            continue
        informado_dec = _decimal(informado) if informado is not None else Decimal("0")
        calculado_dec = _decimal(calculado) if calculado is not None else informado_dec
        diferenca = calculado_dec - informado_dec
        final_status = status or ("ok" if abs(diferenca) < Decimal("0.01") else "divergente")
        items.append(
            {
                "tributo": tributo,
                "informado": float(informado_dec),
                "calculado": float(calculado_dec),
                "diferenca": float(diferenca),
                "status": final_status,
                "observacao": observacao if final_status != "ok" else None,
            }
        )
    return {"nota_id": nota_id, "items": items}


def listar_arquivos_processo(
    db: Session,
    processo_id: int,
    tipo: str | None = None,
    storage: StorageService | None = None,
) -> dict:
    processo = processos_repo.get_processo(db, processo_id)
    if processo is None:
        raise PortalSupportError("Processo nao encontrado.")
    arquivos = arquivos_repo.list_arquivos(db, processo_id=processo_id, limit=500, offset=0)
    if tipo:
        arquivos = [arquivo for arquivo in arquivos if _matches_tipo_arquivo(arquivo, tipo)]
    items = [arquivo_item(arquivo, storage) for arquivo in arquivos]
    return {"processo_id": processo_id, "items": items, "total": len(items)}


def listar_notas_processo(
    db: Session,
    processo_id: int,
    status: str | None = None,
    conferencia_status: str | None = None,
    tipo_nota: str | None = None,
    direcao_nota: str | None = None,
    busca: str | None = None,
    somente_divergentes: bool = False,
    valor_min: Decimal | None = None,
    valor_max: Decimal | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    processo = processos_repo.get_processo(db, processo_id)
    if processo is None:
        raise PortalSupportError("Processo nao encontrado.")
    notas = notas_service.listar_notas(
        db,
        processo_id=processo_id,
        status_documento=status,
        conferencia_status=conferencia_status,
        tipo_nota=tipo_nota,
        direcao_nota=direcao_nota,
        busca=busca,
        limit=5000,
        offset=0,
    )
    notas = _filtrar_notas_operacionais(
        notas,
        empresa_cnpj=(db.get(Empresa, processo.empresa_id).cnpj if db.get(Empresa, processo.empresa_id) else ""),
        somente_divergentes=somente_divergentes,
        valor_min=valor_min,
        valor_max=valor_max,
    )
    total = len(notas)
    safe_offset = max(offset, 0)
    safe_limit = min(max(limit, 1), 500)
    return {
        "processo_id": processo_id,
        "items": notas[safe_offset : safe_offset + safe_limit],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


def _tem_divergencia(nota: Nota) -> bool:
    if nota.divergencia:
        return True
    if (nota.conferencia_status or "").lower() == "corrigir":
        return True
    for field in ("status_valor_liquido", "status_csrf", "status_irrf", "status_inss"):
        value = (getattr(nota, field, None) or "").lower()
        if value and value not in {"ok", "sem_divergencia", "regular"}:
            return True
    return False


def _filtrar_notas_operacionais(
    notas: list[Nota],
    empresa_cnpj: str = "",
    tipo_nota: str | None = None,
    somente_divergentes: bool = False,
    valor_min: Decimal | None = None,
    valor_max: Decimal | None = None,
) -> list[Nota]:
    filtradas = list(notas)
    if tipo_nota in {"emitida", "recebida"} and empresa_cnpj:
        filtradas = [
            nota for nota in filtradas
            if getattr(notas_service, "_classificar_nota")(nota, empresa_cnpj) == tipo_nota
        ]
    if somente_divergentes:
        filtradas = [nota for nota in filtradas if _tem_divergencia(nota)]
    if valor_min is not None:
        filtradas = [nota for nota in filtradas if _decimal(nota.valor_servico) >= Decimal(str(valor_min))]
    if valor_max is not None:
        filtradas = [nota for nota in filtradas if _decimal(nota.valor_servico) <= Decimal(str(valor_max))]
    return filtradas


def _decimal(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def resumo_processo(db: Session, processo_id: int) -> dict:
    processo = processos_repo.get_processo(db, processo_id)
    if processo is None:
        raise PortalSupportError("Processo nao encontrado.")
    notas = [aplicar_campos_operacionais(nota) for nota in db.query(Nota).filter(Nota.processo_id == processo_id).all()]
    arquivos = arquivos_repo.list_arquivos(db, processo_id=processo_id, limit=5000, offset=0)
    status_values = [(nota.status_documento or "").lower() for nota in notas]
    return {
        "processo_id": processo_id,
        "total_notas": len(notas),
        "total_xml": sum(1 for arquivo in arquivos if _canonical_tipo_arquivo(arquivo.tipo) == "XML"),
        "total_pdf": sum(1 for arquivo in arquivos if _canonical_tipo_arquivo(arquivo.tipo) in {"PDF_ORIGINAL", "PDF_ESPELHO"}),
        "corretas": sum(1 for nota in notas if getattr(nota, "status_fila_final", None) == "correta"),
        "divergentes": sum(1 for nota in notas if getattr(nota, "divergencia_fila_final", False)),
        "pendentes": sum(1 for nota in notas if getattr(nota, "status_fila_final", None) == "pendente"),
        "canceladas": sum(1 for status in status_values if "cancel" in status),
        "substituidas": sum(1 for status in status_values if "substit" in status),
        "valor_total_servicos": float(sum((_decimal(nota.valor_servico) for nota in notas), Decimal("0"))),
        "valor_total_iss": 0.0,
        "nsu_inicio": processo.nsu_inicio,
        "nsu_final": processo.nsu_final,
    }


def resumo_operacional_empresas(
    db: Session,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    competencia_inicio: date | None = None,
    competencia_fim: date | None = None,
    status: str | None = None,
    conferencia_status: str | None = None,
) -> dict:
    items: list[dict] = []
    empresas = db.query(Empresa).order_by(Empresa.nome.asc()).all()
    for empresa in empresas:
        query = db.query(Nota).filter(Nota.empresa_id == empresa.id)
        if data_inicio is not None:
            query = query.filter(Nota.data_emissao >= data_inicio)
        if data_fim is not None:
            query = query.filter(Nota.data_emissao <= data_fim)
        if competencia_inicio is not None:
            query = query.filter(Nota.competencia >= competencia_inicio)
        if competencia_fim is not None:
            query = query.filter(Nota.competencia <= competencia_fim)
        if status:
            query = query.filter(Nota.status_documento == status)
        if conferencia_status:
            query = query.filter(Nota.conferencia_status == conferencia_status)
        notas = [aplicar_campos_operacionais(nota) for nota in query.all()]
        ultimo_processo = (
            db.query(Processo)
            .filter(Processo.empresa_id == empresa.id)
            .order_by(Processo.updated_at.desc().nullslast(), Processo.id.desc())
            .first()
        )
        ultimo_nsu = (
            db.query(NsuControle)
            .filter(NsuControle.empresa_id == empresa.id)
            .order_by(NsuControle.ultimo_nsu.desc())
            .first()
        )
        items.append(
            {
                "empresa_id": int(empresa.id),
                "empresa_nome": empresa.nome,
                "cnpj": empresa.cnpj,
                "total_notas": len(notas),
                "corretas": sum(1 for nota in notas if getattr(nota, "status_fila_final", None) == "correta"),
                "divergentes": sum(1 for nota in notas if getattr(nota, "divergencia_fila_final", False)),
                "pendentes": sum(1 for nota in notas if getattr(nota, "status_fila_final", None) == "pendente"),
                "ultima_execucao": ultimo_processo.updated_at if ultimo_processo is not None else None,
                "ultimo_status": ultimo_processo.status if ultimo_processo is not None else None,
                "ultimo_nsu": ultimo_nsu.ultimo_nsu if ultimo_nsu is not None else None,
            }
        )
    return {"items": items, "total": len(items)}


def _format_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _buscar_notas_relatorio(db: Session, filtros: NotasDownloadFiltros) -> list[Nota]:
    notas = notas_service.listar_notas(
        db,
        empresa_id=filtros.empresa_id,
        certificado_id=filtros.certificado_id,
        processo_id=filtros.processo_id,
        status_documento=filtros.status_documento,
        numero=filtros.numero,
        prestador_cnpj=filtros.prestador_cnpj,
        tomador_cnpj=filtros.tomador_cnpj,
        chave=filtros.chave,
        busca=filtros.busca,
        data_inicio=filtros.data_inicio,
        data_fim=filtros.data_fim,
        competencia_inicio=filtros.competencia_inicio,
        competencia_fim=filtros.competencia_fim,
        conferencia_status=filtros.conferencia_status,
        prioridade=filtros.prioridade,
        responsavel=filtros.responsavel,
        status_nota_pdf=filtros.status_nota_pdf,
        simples_nacional_xml=filtros.simples_nacional_xml,
        consulta_simples_api=None,
        status_simples_nacional=filtros.status_simples_nacional,
        incidencia_iss=filtros.incidencia_iss,
        divergencia=filtros.divergencia,
        sla_status=filtros.sla_status,
        tipo_nota=filtros.tipo_nota,
        direcao_nota=filtros.direcao_nota,
        limit=5000,
        offset=0,
        sort=filtros.sort,
    )
    empresa_cnpj = ""
    if filtros.empresa_id:
        empresa = db.get(Empresa, filtros.empresa_id)
        empresa_cnpj = empresa.cnpj if empresa is not None else ""
    return _filtrar_notas_operacionais(
        notas,
        empresa_cnpj=empresa_cnpj,
        tipo_nota=filtros.tipo_nota,
        somente_divergentes=filtros.somente_divergentes,
        valor_min=filtros.valor_min,
        valor_max=filtros.valor_max,
    )


def _parse_decimal_optional(value) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None


def _is_blank(value) -> bool:
    return value is None or str(value).strip() == ""


def _nota_field(nota: Nota, field: str, xml_resumo: dict[str, str] | None = None, xml_key: str | None = None):
    value = getattr(nota, field, None)
    if not _is_blank(value):
        return value
    if xml_resumo is None:
        return value
    return xml_resumo.get(xml_key or field) or value


def _nota_decimal_field(nota: Nota, field: str, xml_resumo: dict[str, str] | None = None, xml_key: str | None = None):
    value = getattr(nota, field, None)
    if not _is_blank(value):
        return value
    if xml_resumo is None:
        return value
    return _parse_decimal_optional(xml_resumo.get(xml_key or field))


def _status_valor_liquido(nota: Nota, xml_resumo: dict[str, str] | None = None) -> str:
    status = getattr(nota, "status_valor_liquido", None)
    if not _is_blank(status):
        return _format_value(status)
    if xml_resumo and not _is_blank(xml_resumo.get("status_valor_liquido")):
        return _format_value(xml_resumo.get("status_valor_liquido"))
    if not xml_resumo or not xml_resumo.get("valor_liquido"):
        return ""
    valor_relatorio = _parse_decimal_optional(getattr(nota, "valor_liquido", None))
    valor_xml = _parse_decimal_optional(xml_resumo.get("valor_liquido"))
    if valor_relatorio is None or valor_xml is None:
        return ""
    return "OK" if valor_relatorio.quantize(Decimal("0.01")) == valor_xml.quantize(Decimal("0.01")) else "Divergente"


def _nota_relatorio_row(nota: Nota, xml_resumo: dict[str, str] | None = None) -> list:
    sla = getattr(nota, "sla", None)
    sla_label = sla.get("label") if isinstance(sla, dict) else _format_value(sla)
    return [
        _format_value(nota.competencia),
        _format_value(_nota_field(nota, "municipio", xml_resumo)),
        _format_value(nota.chave),
        _format_value(nota.data_emissao),
        _format_value(nota.prestador_cnpj),
        _format_value(nota.prestador_nome),
        _format_value(nota.numero_nfse),
        nota.valor_servico,
        _nota_decimal_field(nota, "valor_base", xml_resumo),
        _nota_decimal_field(nota, "csrf", xml_resumo),
        _nota_decimal_field(nota, "irrf", xml_resumo),
        _nota_decimal_field(nota, "inss", xml_resumo),
        _nota_decimal_field(nota, "iss", xml_resumo),
        _nota_decimal_field(nota, "aliquota_iss", xml_resumo),
        nota.valor_liquido,
        _nota_decimal_field(nota, "valor_liquido_correto", xml_resumo),
        _status_valor_liquido(nota, xml_resumo),
        ", ".join(getattr(nota, "campos_ausentes_xml", []) or []),
        _format_value(_nota_field(nota, "incidencia_iss", xml_resumo)),
        _format_value(_nota_field(nota, "codigo_servico", xml_resumo)),
        _format_value(_nota_field(nota, "descricao_servico_nacional", xml_resumo)),
        _format_value(_nota_field(nota, "descricao_servico_detalhada", xml_resumo)),
        _format_value(getattr(nota, "cnae", None)),
        _format_value(getattr(nota, "simples_nacional", None) or getattr(nota, "simples_xml", None) or nota.simples_nacional_xml),
        _format_value(nota.status_simples_nacional),
        _format_value(nota.status_documento),
        _format_value(getattr(nota, "divergencia_fila_label", None)),
        _format_value(getattr(nota, "prioridade_fila", None) or nota.prioridade or getattr(nota, "prioridade_manual", None)),
        _format_value(nota.responsavel),
        _format_value(sla_label),
        _format_value(nota.conferencia_observacao),
        _format_value(getattr(nota, "status_csrf", None)),
        _format_value(getattr(nota, "status_irrf", None)),
        _format_value(getattr(nota, "status_inss", None)),
        _format_value(_nota_field(nota, "subitem_lc116", xml_resumo)),
        _format_value(_nota_field(nota, "codigo_servico_nacional", xml_resumo)),
        _format_value(_nota_field(nota, "origem_base_calculo", xml_resumo)),
        _format_value(_nota_field(nota, "iss_retido", xml_resumo)),
        _nota_decimal_field(nota, "valor_iss_retido", xml_resumo),
        _nota_decimal_field(nota, "valor_pis", xml_resumo),
        _nota_decimal_field(nota, "pis_calculado", xml_resumo),
        _nota_decimal_field(nota, "valor_cofins", xml_resumo),
        _nota_decimal_field(nota, "cofins_calculado", xml_resumo),
        _nota_decimal_field(nota, "valor_csll", xml_resumo),
        _nota_decimal_field(nota, "csll_calculado", xml_resumo),
        _nota_decimal_field(nota, "csrf_calculado", xml_resumo),
        _nota_decimal_field(nota, "irrf_calculado", xml_resumo),
        _nota_decimal_field(nota, "inss_calculado", xml_resumo),
        _nota_decimal_field(nota, "iss_calculado", xml_resumo),
        _format_value(_nota_field(nota, "status_iss", xml_resumo)),
        _nota_decimal_field(nota, "valor_liquido_calculado", xml_resumo),
        _format_value(_nota_field(nota, "regra_irrf", xml_resumo)),
        _nota_decimal_field(nota, "regra_irrf_aliquota", xml_resumo),
        _format_value(_nota_field(nota, "regra_pcc", xml_resumo)),
        _format_value(_nota_field(nota, "regra_inss", xml_resumo)),
        _format_value(_nota_field(nota, "regra_observacao", xml_resumo)),
        _format_value(getattr(nota, "alertas_fiscais", None)),
    ]


def _precisa_enriquecimento_xml(nota: Nota) -> bool:
    fields = [
        "municipio",
        "valor_base",
        "csrf",
        "irrf",
        "inss",
        "iss",
        "aliquota_iss",
        "valor_liquido_correto",
        "status_valor_liquido",
        "incidencia_iss",
        "codigo_servico",
        "descricao_servico_nacional",
        "descricao_servico_detalhada",
    ]
    return any(_is_blank(getattr(nota, field, None)) for field in fields)


def _xml_resumos_por_nota(db: Session, notas: list[Nota]) -> dict[int, dict[str, str]]:
    notas_pendentes = [nota for nota in notas if _precisa_enriquecimento_xml(nota)]
    if not notas_pendentes:
        return {}
    try:
        storage = get_storage_service()
    except Exception:
        return {}

    arquivos_por_nota: dict[int, Arquivo] = {}
    arquivos = arquivos_repo.list_arquivos_by_notas(db, [int(nota.id) for nota in notas_pendentes])
    for arquivo in arquivos:
        if _canonical_tipo_arquivo(arquivo.tipo) == "XML" and arquivo.nota_id is not None:
            arquivos_por_nota.setdefault(int(arquivo.nota_id), arquivo)

    resumos: dict[int, dict[str, str]] = {}
    for nota in notas_pendentes:
        arquivo = arquivos_por_nota.get(int(nota.id))
        storage_key = arquivo.storage_key if arquivo is not None else getattr(nota, "xml_storage_key", None)
        if not storage_key:
            continue
        filename = _nome_arquivo(arquivo) if arquivo is not None else storage_key.rsplit("/", 1)[-1]
        try:
            resumo = legacy_ingestion_service.parse_xml_resumo_bytes(storage.get_bytes(storage_key), filename)
        except Exception:
            continue
        if resumo.get("tipo_xml") != "evento":
            resumos[int(nota.id)] = resumo
    return resumos


def exportar_conferencia_xlsx(db: Session, filtros: NotasDownloadFiltros) -> tuple[bytes, str]:
    notas = _buscar_notas_relatorio(db, filtros)
    xml_resumos = _xml_resumos_por_nota(db, notas)
    headers = [
        "Competencia",
        "Municipio",
        "Chave de Acesso",
        "Data de Emissao",
        "CNPJ/CPF",
        "Razao Social",
        "No Documento",
        "Valor Total",
        "Valor B/C",
        "CSRF",
        "IRRF",
        "INSS",
        "ISS",
        "Aliquota ISS",
        "Valor Liquido",
        "Valor Liquido Correto",
        "Status Valor Liquido",
        "Campos ausentes no XML",
        "Incidencia ISS",
        "Codigo de servico",
        "Descricao servico nacional",
        "Descricao detalhada do servico",
        "CNAE",
        "Simples Nacional / XML",
        "Status Simples Nacional",
        "Status nota",
        "Divergencia",
        "Prioridade",
        "Responsavel",
        "SLA",
        "Observacao interna",
        "Status CSRF",
        "Status IRRF",
        "Status INSS",
        "Subitem LC116",
        "Codigo Servico Nacional",
        "Origem Base de Calculo",
        "ISS Retido",
        "Valor ISS Retido",
        "PIS Informado",
        "PIS Calculado",
        "COFINS Informado",
        "COFINS Calculado",
        "CSLL Informado",
        "CSLL Calculado",
        "CSRF Calculado",
        "IRRF Calculado",
        "INSS Calculado",
        "ISS Calculado",
        "Status ISS",
        "Valor Liquido Calculado",
        "Regra IRRF",
        "Aliquota Regra IRRF",
        "Regra PIS/COFINS/CSLL",
        "Regra INSS",
        "Observacao Regra",
        "Alertas Fiscais",
    ]
    wb = Workbook()
    ws = wb.active
    ws.title = "Conferencia"
    ws.append(headers)
    fill = PatternFill("solid", fgColor="1F4E78")
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
    for nota in notas:
        ws.append(_nota_relatorio_row(nota, xml_resumos.get(int(nota.id))))
    for column_cells in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = min(max(max_len + 2, 12), 48)
    output = io.BytesIO()
    wb.save(output)
    filename = f"relatorio_conferencia_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return output.getvalue(), filename
