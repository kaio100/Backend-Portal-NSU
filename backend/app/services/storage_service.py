from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Optional

from backend.app.core.config import settings


class StorageKeyError(ValueError):
    pass


class StorageService:
    backend = "base"

    def put_bytes(self, key: str, data: bytes, content_type: Optional[str] = None) -> dict:
        raise NotImplementedError

    def get_bytes(self, key: str) -> bytes:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        raise NotImplementedError

    def list_keys(self, prefix: str = "") -> list[str]:
        raise NotImplementedError

    def get_path(self, key: str) -> Path:
        raise NotImplementedError


class LocalFilesystemStorage(StorageService):
    backend = "local"

    def __init__(self, root: str | Path = "storage") -> None:
        self.root = Path(root)

    def put_bytes(self, key: str, data: bytes, content_type: Optional[str] = None) -> dict:
        normalized_key = normalize_storage_key(key)
        path = self.get_path(normalized_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {
            "backend": self.backend,
            "key": normalized_key,
            "path": str(path),
            "size": len(data),
            "content_type": content_type,
        }

    def get_bytes(self, key: str) -> bytes:
        return self.get_path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self.get_path(key).exists()

    def delete(self, key: str) -> bool:
        path = self.get_path(key)
        if not path.exists():
            return False
        path.unlink()
        return True

    def list_keys(self, prefix: str = "") -> list[str]:
        normalized_prefix = normalize_storage_prefix(prefix)
        base = self.get_path(normalized_prefix) if normalized_prefix else self.root
        if not base.exists():
            return []
        if base.is_file():
            return [normalized_prefix]

        keys: list[str] = []
        root = self.root.resolve()
        for path in sorted(base.rglob("*")):
            if path.is_file():
                keys.append(path.relative_to(root).as_posix())
        return keys

    def get_path(self, key: str) -> Path:
        normalized_key = normalize_storage_key(key)
        root = self.root.resolve()
        path = (root / Path(*normalized_key.split("/"))).resolve()
        if path != root and root not in path.parents:
            raise StorageKeyError("Storage key escapes the configured root.")
        return path


def normalize_storage_key(key: str) -> str:
    value = (key or "").replace("\\", "/").strip("/")
    if not value:
        raise StorageKeyError("Storage key cannot be empty.")

    pure = PurePosixPath(value)
    if pure.is_absolute():
        raise StorageKeyError("Storage key cannot be an absolute path.")

    parts = pure.parts
    if any(part in {"", ".", ".."} for part in parts):
        raise StorageKeyError("Storage key contains an invalid path segment.")

    return "/".join(parts)


def normalize_storage_prefix(prefix: str = "") -> str:
    value = (prefix or "").replace("\\", "/").strip("/")
    if not value:
        return ""
    return normalize_storage_key(value)


def _clean_segment(value: str, field: str) -> str:
    cleaned = normalize_storage_key(value)
    if "/" in cleaned:
        raise StorageKeyError(f"{field} must be a single path segment.")
    return cleaned


def _date_key(kind: str, cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
    return "/".join(
        [
            _clean_segment(kind, "kind"),
            _clean_segment(cnpj_empresa, "cnpj_empresa"),
            _clean_segment(ano, "ano"),
            _clean_segment(mes, "mes"),
            _clean_segment(filename, "filename"),
        ]
    )


def build_xml_key(cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
    return _date_key("xml", cnpj_empresa, ano, mes, filename)


def build_pdf_oficial_key(cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
    return _date_key("pdf-oficial", cnpj_empresa, ano, mes, filename)


def build_pdf_espelho_key(cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
    return _date_key("pdf-espelho", cnpj_empresa, ano, mes, filename)


def build_export_key(cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
    return _date_key("exports", cnpj_empresa, ano, mes, filename)


def build_raw_key(cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
    return _date_key("raw", cnpj_empresa, ano, mes, filename)


def build_json_key(cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
    return _date_key("json", cnpj_empresa, ano, mes, filename)


def build_log_key(cnpj_empresa: str, processo_id: str) -> str:
    return "/".join(
        [
            "logs",
            _clean_segment(cnpj_empresa, "cnpj_empresa"),
            f"{_clean_segment(processo_id, 'processo_id')}.log",
        ]
    )


def build_certificado_key(cnpj_empresa: str, certificado_id: str, filename: str) -> str:
    return "/".join(
        [
            "certificados",
            _clean_segment(cnpj_empresa, "cnpj_empresa"),
            _clean_segment(certificado_id, "certificado_id"),
            _clean_segment(filename, "filename"),
        ]
    )


def get_storage_service() -> StorageService:
    if settings.storage_backend != "local":
        raise RuntimeError(f"Unsupported storage backend: {settings.storage_backend}")
    return LocalFilesystemStorage(settings.storage_root)
