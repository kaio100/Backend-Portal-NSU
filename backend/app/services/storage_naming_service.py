from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


INVALID_PATH_CHARS = r'[\\/:*?"<>|\x00-\x1f]+'


def _clean_name(value: str | None, fallback: str, max_length: int) -> str:
    text = (value or fallback or "").strip()
    text = re.sub(INVALID_PATH_CHARS, " ", text)
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    text = text.replace("..", " ")
    text = text.strip(" .")
    text = text[:max_length].strip(" .")
    if not text or text in {".", ".."} or PurePosixPath(text).is_absolute():
        return fallback
    return text


def safe_folder_name(value: str | None, fallback: str = "sem_nome") -> str:
    return _clean_name(value, fallback, max_length=120)


def safe_file_name(value: str | None, fallback: str = "arquivo") -> str:
    return _clean_name(value, fallback, max_length=160)


def build_zip_empresa_folder(empresa_nome: str | None, empresa_id: int | None) -> str:
    fallback = f"empresa_{empresa_id}" if empresa_id is not None else "empresa_sem_id"
    return safe_folder_name(empresa_nome, fallback=fallback)


def _chave_curta(chave: str | None) -> str:
    cleaned = re.sub(r"\W+", "", chave or "")
    return cleaned[-6:] if cleaned else "SEM_NUMERO"


def build_nota_base_filename(nota: Any) -> str:
    prestador = safe_file_name(getattr(nota, "prestador_nome", None), fallback="PRESTADOR")
    numero = safe_file_name(getattr(nota, "numero_nfse", None), fallback="")
    if not numero:
        numero = _chave_curta(getattr(nota, "chave", None))
    return safe_file_name(f"{prestador} NFS-e {numero}", fallback=f"PRESTADOR NFS-e {numero}")
