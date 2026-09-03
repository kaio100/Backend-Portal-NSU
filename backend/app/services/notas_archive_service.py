from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Arquivo, Empresa, Evento, Nota
from backend.app.repositories import arquivos_repo
from backend.app.services.storage_service import StorageService


def filtro_anos_anteriores(ano_operacional: int):
    """Usa competencia e recorre a data_emissao somente quando ela estiver ausente."""
    inicio = date(int(ano_operacional), 1, 1)
    return or_(Nota.competencia < inicio, and_(Nota.competencia.is_(None), Nota.data_emissao < inicio))


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row_dict(row: Any) -> dict[str, Any]:
    return {column.name: _json_value(getattr(row, column.name)) for column in row.__table__.columns}


def _checksum_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _storage_references(notas: list[Nota], arquivos: list[Arquivo], eventos: list[Evento]) -> list[dict[str, Any]]:
    referencias: list[dict[str, Any]] = []
    vistos: set[tuple[str, str, int]] = set()

    def adicionar(key: str | None, origem: str, registro_id: int) -> None:
        if not key:
            return
        identidade = (key, origem, registro_id)
        if identidade not in vistos:
            vistos.add(identidade)
            referencias.append({"storage_key": key, "origem": origem, "registro_id": registro_id})

    for nota in notas:
        adicionar(nota.xml_storage_key, "notas.xml_storage_key", int(nota.id))
        adicionar(nota.pdf_oficial_storage_key, "notas.pdf_oficial_storage_key", int(nota.id))
        adicionar(nota.pdf_espelho_storage_key, "notas.pdf_espelho_storage_key", int(nota.id))
    for arquivo in arquivos:
        adicionar(arquivo.storage_key, "arquivos.storage_key", int(arquivo.id))
    for evento in eventos:
        adicionar(evento.xml_storage_key, "eventos.xml_storage_key", int(evento.id))
    return referencias


def arquivar_notas_anos_anteriores(
    db: Session,
    storage: StorageService,
    *,
    ano_operacional: int = 2026,
    executar: bool = False,
) -> dict[str, Any]:
    """Salva um manifesto no Storage e, depois de validado, exclui as notas antigas."""
    empresas = list(db.query(Empresa).order_by(Empresa.id.asc()).all())
    resumo: dict[str, Any] = {
        "ano_operacional": ano_operacional,
        "criterio_data": "competencia; data_emissao quando competencia estiver ausente",
        "executado": executar,
        "empresas": [],
        "notas": 0,
        "excluidas": 0,
    }

    for empresa in empresas:
        base_query = db.query(Nota).filter(Nota.empresa_id == empresa.id, filtro_anos_anteriores(ano_operacional))
        if not executar:
            quantidade = int(base_query.count())
            if quantidade:
                resumo["notas"] += quantidade
                resumo["empresas"].append({
                    "empresa_id": int(empresa.id), "empresa_nome": empresa.nome, "notas": quantidade,
                    "manifesto": None, "excluidas": 0,
                })
            continue

        notas = list(base_query.order_by(Nota.id.asc()).all())
        if not notas:
            continue
        nota_ids = [int(nota.id) for nota in notas]
        arquivos = arquivos_repo.list_arquivos_by_notas(db, nota_ids)
        eventos = list(db.query(Evento).filter(Evento.nota_id.in_(nota_ids)).order_by(Evento.id.asc()).all())
        criado_em = datetime.now(timezone.utc)
        sufixo = criado_em.strftime("%Y%m%dT%H%M%S%fZ")
        storage_key = f"backups/manifestos-notas/empresa_{empresa.id}/anteriores_{ano_operacional}_{sufixo}.json"
        item = {
            "empresa_id": int(empresa.id), "empresa_nome": empresa.nome, "notas": len(notas),
            "manifesto": storage_key, "excluidas": 0,
        }
        resumo["notas"] += len(notas)
        resumo["empresas"].append(item)
        manifest = {
            "versao": 2,
            "finalidade": "backup anterior a exclusao do banco operacional",
            "criado_em": criado_em.isoformat(),
            "ano_operacional": ano_operacional,
            "criterio_data": "competencia; data_emissao quando competencia estiver ausente",
            "empresa": {"id": int(empresa.id), "nome": empresa.nome, "cnpj": empresa.cnpj},
            "quantidades": {"notas": len(notas), "arquivos": len(arquivos), "eventos": len(eventos)},
            "notas": [_row_dict(nota) for nota in notas],
            "arquivos": [_row_dict(arquivo) for arquivo in arquivos],
            "eventos": [_row_dict(evento) for evento in eventos],
            "referencias_storage": _storage_references(notas, arquivos, eventos),
        }

        try:
            with tempfile.TemporaryDirectory(prefix="nfse_manifest_") as temp_dir:
                manifest_path = Path(temp_dir) / "manifest.json"
                with manifest_path.open("w", encoding="utf-8") as stream:
                    json.dump(manifest, stream, ensure_ascii=False, separators=(",", ":"))
                tamanho = manifest_path.stat().st_size
                checksum = _checksum_file(manifest_path)
                storage.put_file(storage_key, manifest_path, content_type="application/json")
                if storage.object_size(storage_key) != tamanho:
                    raise RuntimeError(f"Manifesto nao confirmado no storage: {storage_key}")

            arquivos_repo.create_arquivo_if_missing(db, {
                "empresa_id": empresa.id, "nota_id": None, "processo_id": None,
                "tipo": "MANIFESTO_NOTAS_EXCLUIDAS", "storage_backend": storage.backend,
                "storage_bucket": settings.storage_bucket, "storage_key": storage_key,
                "filename": Path(storage_key).name, "content_type": "application/json",
                "tamanho_bytes": tamanho, "checksum": checksum,
            })
            db.query(Arquivo).filter(Arquivo.nota_id.in_(nota_ids)).update(
                {Arquivo.nota_id: None}, synchronize_session=False
            )
            db.query(Evento).filter(Evento.nota_id.in_(nota_ids)).update(
                {Evento.nota_id: None}, synchronize_session=False
            )
            excluidas = db.query(Nota).filter(Nota.id.in_(nota_ids)).delete(synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
            raise

        item.update({
            "excluidas": int(excluidas), "arquivos_preservados": len(arquivos),
            "eventos_preservados": len(eventos),
        })
        resumo["excluidas"] += int(excluidas)
    return resumo
