from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Arquivo, Empresa, Nota
from backend.app.repositories import arquivos_repo
from backend.app.services.storage_service import StorageService


def filtro_anos_anteriores(ano_operacional: int):
    inicio = date(int(ano_operacional), 1, 1)
    return or_(Nota.competencia < inicio, Nota.data_emissao < inicio)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _nota_dict(nota: Nota) -> dict[str, Any]:
    return {column.name: _json_value(getattr(nota, column.name)) for column in Nota.__table__.columns}


def _arquivo_dict(arquivo: Arquivo) -> dict[str, Any]:
    return {column.name: _json_value(getattr(arquivo, column.name)) for column in Arquivo.__table__.columns}


def _checksum_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def arquivar_notas_anos_anteriores(
    db: Session,
    storage: StorageService,
    *,
    ano_operacional: int = 2026,
    executar: bool = False,
) -> dict[str, Any]:
    empresas = list(db.query(Empresa).order_by(Empresa.id.asc()).all())
    resumo: dict[str, Any] = {"ano_operacional": ano_operacional, "executado": executar, "empresas": [], "notas": 0}

    for empresa in empresas:
        base_query = (
            db.query(Nota)
            .filter(Nota.empresa_id == empresa.id, Nota.arquivada.is_(False))
            .filter(filtro_anos_anteriores(ano_operacional))
        )
        if not executar:
            quantidade = int(base_query.count())
            if quantidade:
                resumo["notas"] += quantidade
                resumo["empresas"].append({"empresa_id": int(empresa.id), "empresa_nome": empresa.nome, "notas": quantidade, "backup": None, "arquivadas": 0})
            continue
        notas = list(
            base_query
            .order_by(Nota.id.asc())
            .all()
        )
        if not notas:
            continue
        item = {"empresa_id": int(empresa.id), "empresa_nome": empresa.nome, "notas": len(notas), "backup": None, "arquivadas": 0}
        resumo["notas"] += len(notas)
        resumo["empresas"].append(item)
        nota_ids = [int(nota.id) for nota in notas]
        arquivos = arquivos_repo.list_arquivos_by_notas(db, nota_ids)
        storage_key = f"backups/notas-arquivadas/empresa_{empresa.id}/anteriores_{ano_operacional}.zip"
        ausentes: list[str] = []
        with tempfile.TemporaryDirectory(prefix="nfse_archive_") as temp_dir:
            zip_path = Path(temp_dir) / "backup.zip"
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                manifest = {
                    "versao": 1,
                    "criado_em": datetime.now(timezone.utc).isoformat(),
                    "ano_operacional": ano_operacional,
                    "empresa_id": int(empresa.id),
                    "notas": [_nota_dict(nota) for nota in notas],
                    "arquivos": [_arquivo_dict(arquivo) for arquivo in arquivos],
                }
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, default=str))
                for arquivo in arquivos:
                    try:
                        content = storage.get_bytes(arquivo.storage_key)
                    except Exception:
                        ausentes.append(arquivo.storage_key)
                        continue
                    nome = (arquivo.filename or Path(arquivo.storage_key).name or f"arquivo_{arquivo.id}").replace("/", "_").replace("\\", "_")
                    archive.writestr(f"documentos/nota_{arquivo.nota_id}/arquivo_{arquivo.id}_{nome}", content)
                archive.writestr("arquivos_ausentes.json", json.dumps(ausentes, ensure_ascii=False))

            tamanho = zip_path.stat().st_size
            checksum = _checksum_file(zip_path)
            storage.put_file(storage_key, zip_path, content_type="application/zip")
            if storage.object_size(storage_key) != tamanho:
                raise RuntimeError(f"Backup nao confirmado no storage: {storage_key}")

            arquivos_repo.create_arquivo_if_missing(
                db,
                {
                    "empresa_id": empresa.id,
                    "nota_id": None,
                    "processo_id": None,
                    "tipo": "BACKUP_NOTAS",
                    "storage_backend": storage.backend,
                    "storage_bucket": settings.storage_bucket,
                    "storage_key": storage_key,
                    "filename": Path(storage_key).name,
                    "content_type": "application/zip",
                    "tamanho_bytes": tamanho,
                    "checksum": checksum,
                },
            )
        agora = datetime.now(timezone.utc)
        for nota in notas:
            nota.arquivada = True
            nota.arquivada_em = agora
            nota.arquivo_backup_storage_key = storage_key
            db.add(nota)
        db.commit()
        item.update({"backup": storage_key, "arquivadas": len(notas), "arquivos_ausentes": len(ausentes)})

    return resumo
