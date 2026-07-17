from __future__ import annotations

import logging
import os
import tempfile
import time
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
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

# R2 has a non-trivial round-trip time. Fetching every object serially makes a
# medium-sized ZIP exceed the HTTP timeout even though each individual object
# is available. Keep concurrency bounded so downloads get faster without
# exhausting the API worker or the storage connection pool.
_TEMP_ZIP_PREFIX = "notas_nfse_"


class NotasDownloadLoteError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadLoteResult:
    filename: str
    path: Path
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


def _get_storage_bytes(storage: StorageService, arquivo: Arquivo) -> tuple[Arquivo, bytes | None, Exception | None]:
    try:
        return arquivo, storage.get_bytes(arquivo.storage_key), None
    except Exception as exc:
        return arquivo, None, exc


def limpar_zips_temporarios(max_age_hours: int | None = None) -> int:
    """Remove ZIPs abandonados por reinicios durante a geracao/download."""
    horas = max(1, int(max_age_hours or settings.download_temp_max_age_hours or 24))
    limite = time.time() - (horas * 3600)
    removidos = 0
    temp_root = Path(tempfile.gettempdir())
    for path in temp_root.glob(f"{_TEMP_ZIP_PREFIX}*.zip"):
        try:
            if path.is_file() and path.stat().st_mtime < limite:
                path.unlink()
                removidos += 1
        except OSError:
            logger.warning("Nao foi possivel limpar ZIP temporario: %s", path)
    return removidos


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

    max_notas = max(1, int(settings.download_lote_max_notas or 10000))
    logger.info("Download lote iniciado: filtros=%s nota_ids=%s", payload.filtros, payload.nota_ids)
    notas = _buscar_notas(db, payload, max_notas)
    logger.info("Download lote: %s notas encontradas", len(notas))
    if not notas:
        raise NotasDownloadLoteError("Nenhuma nota encontrada para os filtros informados.")

    used_paths: set[str] = set()
    arquivos_adicionados = 0
    erros: list[str] = []
    registros_disponiveis = 0

    arquivos_por_nota: dict[int, list[Arquivo]] = defaultdict(list)
    arquivos_lote = arquivos_repo.list_arquivos_by_notas(db, [int(nota.id) for nota in notas])
    for arquivo in arquivos_lote:
        if arquivo.nota_id is not None:
            arquivos_por_nota[int(arquivo.nota_id)].append(arquivo)

    arquivos_selecionados: list[tuple[Nota, Arquivo]] = []
    for nota in notas:
        selecionados = _select_arquivos(
            arquivos_por_nota.get(int(nota.id), []),
            incluir_xml=payload.incluir_xml,
            incluir_pdf=payload.incluir_pdf,
            preferir_pdf_original=payload.preferir_pdf_original,
        )
        arquivos_selecionados.extend((nota, arquivo) for arquivo in selecionados)

    registros_disponiveis = len(arquivos_selecionados)
    if registros_disponiveis == 0:
        raise NotasDownloadLoteError("Nenhum arquivo disponivel para as notas filtradas.")

    worker_count = max(1, min(32, int(settings.download_storage_workers or 16)))
    descriptor, temp_name = tempfile.mkstemp(prefix=_TEMP_ZIP_PREFIX, suffix=".zip")
    os.close(descriptor)
    temp_path = Path(temp_name)
    try:
        with (
            zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_STORED) as zip_file,
            ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="zip-storage") as executor,
        ):
            # Processa blocos limitados para que resultados prontos nao mantenham
            # milhares de PDFs simultaneamente na memoria enquanto o ZIP e gravado.
            batch_size = worker_count * 4
            for start in range(0, len(arquivos_selecionados), batch_size):
                batch = arquivos_selecionados[start : start + batch_size]
                resultados = executor.map(
                    lambda item: _get_storage_bytes(storage, item[1]),
                    batch,
                )
                for (nota, _), (arquivo, content, error) in zip(batch, resultados):
                    tipo = _canonical_tipo(arquivo.tipo)
                    filename = _friendly_xml_filename(nota) if tipo == "XML" else _friendly_pdf_filename(nota)
                    folder = _zip_folder_for_arquivo(nota, tipo)
                    zip_path = _dedupe_path(f"{folder}/{filename}", used_paths)
                    if error is None and content is not None:
                        # PDF normalmente ja e comprimido; tentar comprimi-lo de
                        # novo gasta CPU sem reduzir tamanho de forma relevante.
                        if tipo == "XML":
                            zip_file.writestr(
                                zip_path,
                                content,
                                compress_type=zipfile.ZIP_DEFLATED,
                                compresslevel=1,
                            )
                        else:
                            zip_file.writestr(zip_path, content, compress_type=zipfile.ZIP_STORED)
                        arquivos_adicionados += 1
                    else:
                        logger.warning(
                            "Arquivo ausente no storage durante download lote: arquivo_id=%s storage_key=%s erro=%s",
                            arquivo.id,
                            arquivo.storage_key,
                            error,
                        )
                        erros.append(
                            f"Nota {nota.id} ({nota.chave}) - arquivo {arquivo.id} {tipo} indisponivel no storage."
                        )

            if erros:
                report = [
                    "RELATORIO DE ARQUIVOS AUSENTES",
                    "",
                    "Alguns arquivos vinculados no banco nao foram encontrados no storage.",
                    "",
                    *erros,
                ]
                zip_file.writestr(
                    _dedupe_path("notas_nfse/RELATORIO_ERROS.txt", used_paths),
                    "\n".join(report),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=1,
                )
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    if arquivos_adicionados == 0 and not erros:
        temp_path.unlink(missing_ok=True)
        raise NotasDownloadLoteError("Nenhum arquivo disponivel para as notas filtradas.")

    filename = f"notas_nfse_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    logger.info(
        "Download lote finalizado: notas=%s arquivos=%s ausentes=%s tamanho_zip=%s",
        len(notas),
        arquivos_adicionados,
        len(erros),
        temp_path.stat().st_size,
    )
    return DownloadLoteResult(
        filename=filename,
        path=temp_path,
        notas_count=len(notas),
        arquivos_count=arquivos_adicionados,
        ausentes_count=len(erros),
    )
