from __future__ import annotations

import io
import logging
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Iterable

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Arquivo, Nota
from backend.app.repositories import arquivos_repo, notas_repo
from backend.app.schemas.notas import NotasDownloadFiltros, NotasDownloadLoteRequest
from backend.app.services import notas_service
from backend.app.services.storage_naming_service import build_nota_base_filename, build_zip_empresa_folder
from backend.app.services.storage_service import StorageService


logger = logging.getLogger(__name__)


class NotasDownloadLoteError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadLoteResult:
    filename: str
    data: bytes
    notas_count: int
    arquivos_count: int
    ausentes_count: int


def _canonical_tipo(value: str | None) -> str:
    normalized = (value or "").lower()
    if normalized == "xml":
        return "XML"
    if normalized in {"pdf_oficial", "pdf_original", "oficial"}:
        return "PDF_ORIGINAL"
    if normalized in {"pdf_espelho", "espelho"}:
        return "PDF_ESPELHO"
    return value or ""


def _dedupe_path(path: str, used: set[str]) -> str:
    normalized = PurePosixPath(path.replace("\\", "/")).as_posix()
    if normalized not in used:
        used.add(normalized)
        return normalized

    pure = PurePosixPath(normalized)
    stem = pure.stem
    suffix = pure.suffix
    parent = pure.parent.as_posix()
    index = 2
    while True:
        candidate_name = f"{stem} ({index}){suffix}"
        candidate = f"{parent}/{candidate_name}" if parent != "." else candidate_name
        if candidate not in used:
            used.add(candidate)
            return candidate
        index += 1


def _friendly_xml_filename(nota: Nota) -> str:
    return f"{build_nota_base_filename(nota)}.xml"


def _friendly_pdf_filename(nota: Nota) -> str:
    return f"{build_nota_base_filename(nota)}.pdf"


def _zip_folder_for_arquivo(nota: Nota, tipo: str) -> str:
    empresa = getattr(nota, "empresa", None)
    empresa_folder = build_zip_empresa_folder(
        getattr(empresa, "nome", None),
        int(nota.empresa_id) if nota.empresa_id is not None else None,
    )
    kind_folder = "xml" if tipo == "XML" else "pdf"
    return f"notas_nfse/{empresa_folder}/{kind_folder}"


def _select_arquivos(
    arquivos: Iterable[Arquivo],
    incluir_xml: bool,
    incluir_pdf: bool,
    preferir_pdf_original: bool,
) -> list[Arquivo]:
    by_tipo: dict[str, list[Arquivo]] = {"XML": [], "PDF_ORIGINAL": [], "PDF_ESPELHO": []}
    for arquivo in arquivos:
        tipo = _canonical_tipo(arquivo.tipo)
        if tipo in by_tipo:
            by_tipo[tipo].append(arquivo)

    selected: list[Arquivo] = []
    if incluir_xml:
        selected.extend(by_tipo["XML"][:1])

    if incluir_pdf:
        originals = by_tipo["PDF_ORIGINAL"]
        espelhos = by_tipo["PDF_ESPELHO"]
        if preferir_pdf_original:
            selected.extend(originals[:1] if originals else espelhos[:1])
        else:
            selected.extend(originals[:1])
            selected.extend(espelhos[:1])
    return selected


def _buscar_notas(db: Session, payload: NotasDownloadLoteRequest, max_notas: int) -> list[Nota]:
    if payload.nota_ids:
        if len(payload.nota_ids) > max_notas:
            raise NotasDownloadLoteError(
                f"Limite de {max_notas} notas por ZIP excedido. Selecione menos notas ou refine os filtros."
            )
        return notas_repo.list_notas_by_ids(db, payload.nota_ids)

    filtros: NotasDownloadFiltros = payload.filtros or NotasDownloadFiltros()
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
        sort=filtros.sort,
        limit=max_notas + 1,
        offset=0,
    )
    if len(notas) > max_notas:
        raise NotasDownloadLoteError(
            f"Limite de {max_notas} notas por ZIP excedido. Refine os filtros para baixar um lote menor."
        )
    return notas


def gerar_zip_notas(
    db: Session,
    storage: StorageService,
    payload: NotasDownloadLoteRequest,
) -> DownloadLoteResult:
    if not payload.incluir_xml and not payload.incluir_pdf:
        raise NotasDownloadLoteError("Selecione XML, PDF ou ambos para gerar o ZIP.")

    max_notas = max(1, int(settings.download_lote_max_notas or 1000))
    logger.info("Download lote iniciado: filtros=%s nota_ids=%s", payload.filtros, payload.nota_ids)
    notas = _buscar_notas(db, payload, max_notas)
    logger.info("Download lote: %s notas encontradas", len(notas))
    if not notas:
        raise NotasDownloadLoteError("Nenhuma nota encontrada para os filtros informados.")

    zip_buffer = io.BytesIO()
    used_paths: set[str] = set()
    arquivos_adicionados = 0
    erros: list[str] = []
    registros_disponiveis = 0

    arquivos_por_nota: dict[int, list[Arquivo]] = defaultdict(list)
    arquivos_lote = arquivos_repo.list_arquivos_by_notas(db, [int(nota.id) for nota in notas])
    for arquivo in arquivos_lote:
        if arquivo.nota_id is not None:
            arquivos_por_nota[int(arquivo.nota_id)].append(arquivo)

    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zip_file:
        for nota in notas:
            arquivos = arquivos_por_nota.get(int(nota.id), [])
            selecionados = _select_arquivos(
                arquivos,
                incluir_xml=payload.incluir_xml,
                incluir_pdf=payload.incluir_pdf,
                preferir_pdf_original=payload.preferir_pdf_original,
            )
            registros_disponiveis += len(selecionados)

            for arquivo in selecionados:
                tipo = _canonical_tipo(arquivo.tipo)
                filename = _friendly_xml_filename(nota) if tipo == "XML" else _friendly_pdf_filename(nota)
                folder = _zip_folder_for_arquivo(nota, tipo)
                zip_path = _dedupe_path(f"{folder}/{filename}", used_paths)
                try:
                    zip_file.writestr(zip_path, storage.get_bytes(arquivo.storage_key))
                    arquivos_adicionados += 1
                except Exception as exc:
                    logger.warning(
                        "Arquivo ausente no storage durante download lote: arquivo_id=%s storage_key=%s erro=%s",
                        arquivo.id,
                        arquivo.storage_key,
                        exc,
                    )
                    erros.append(
                        f"Nota {nota.id} ({nota.chave}) - arquivo {arquivo.id} {tipo} indisponivel no storage."
                    )

        if registros_disponiveis == 0:
            raise NotasDownloadLoteError("Nenhum arquivo disponivel para as notas filtradas.")

        if erros:
            report = [
                "RELATORIO DE ARQUIVOS AUSENTES",
                "",
                "Alguns arquivos vinculados no banco nao foram encontrados no storage.",
                "",
                *erros,
            ]
            zip_file.writestr(_dedupe_path("notas_nfse/RELATORIO_ERROS.txt", used_paths), "\n".join(report))

    data = zip_buffer.getvalue()
    if arquivos_adicionados == 0 and not erros:
        raise NotasDownloadLoteError("Nenhum arquivo disponivel para as notas filtradas.")

    filename = f"notas_nfse_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    logger.info(
        "Download lote finalizado: notas=%s arquivos=%s ausentes=%s tamanho_zip=%s",
        len(notas),
        arquivos_adicionados,
        len(erros),
        len(data),
    )
    return DownloadLoteResult(
        filename=filename,
        data=data,
        notas_count=len(notas),
        arquivos_count=arquivos_adicionados,
        ausentes_count=len(erros),
    )
