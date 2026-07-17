from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Optional

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

    def list_prefix(self, prefix: str) -> list[str]:
        return self.list_keys(prefix)

    def object_size(self, key: str) -> int | None:
        return len(self.get_bytes(key))

    def generate_presigned_url(self, key: str, expires_seconds: int = 300) -> str:
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

    def generate_presigned_url(self, key: str, expires_seconds: int = 300) -> str:
        return self.get_path(key).as_uri()


class R2StorageService(StorageService):
    backend = "r2"

    def __init__(
        self,
        bucket: str,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        region_name: str = "auto",
        client: Any | None = None,
    ) -> None:
        if not bucket:
            raise RuntimeError("R2_BUCKET_NAME is required when STORAGE_BACKEND=r2.")
        if not endpoint_url:
            raise RuntimeError("R2_ENDPOINT_URL is required when STORAGE_BACKEND=r2.")
        if not access_key_id:
            raise RuntimeError("R2_ACCESS_KEY_ID is required when STORAGE_BACKEND=r2.")
        if not secret_access_key:
            raise RuntimeError("R2_SECRET_ACCESS_KEY is required when STORAGE_BACKEND=r2.")

        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.region_name = region_name or "auto"
        if client is not None:
            self.client = client
        else:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:
                raise RuntimeError("boto3 is required when STORAGE_BACKEND=r2.") from exc

            self.client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                region_name=self.region_name,
                config=Config(
                    signature_version="s3v4",
                    max_pool_connections=max(20, int(settings.download_storage_workers) * 2),
                    connect_timeout=5,
                    read_timeout=60,
                    retries={"max_attempts": 3, "mode": "adaptive"},
                ),
            )

    def put_bytes(self, key: str, data: bytes, content_type: Optional[str] = None) -> dict:
        normalized_key = normalize_storage_key(key)
        kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": normalized_key, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        self.client.put_object(**kwargs)
        return {
            "backend": self.backend,
            "bucket": self.bucket,
            "key": normalized_key,
            "size": len(data),
            "content_type": content_type,
        }

    def get_bytes(self, key: str) -> bytes:
        normalized_key = normalize_storage_key(key)
        response = self.client.get_object(Bucket=self.bucket, Key=normalized_key)
        body = response["Body"]
        return body.read()

    def exists(self, key: str) -> bool:
        return self.object_size(key) is not None

    def delete(self, key: str) -> bool:
        normalized_key = normalize_storage_key(key)
        existed = self.exists(normalized_key)
        self.client.delete_object(Bucket=self.bucket, Key=normalized_key)
        return existed

    def list_keys(self, prefix: str = "") -> list[str]:
        normalized_prefix = normalize_storage_prefix(prefix)
        keys: list[str] = []
        continuation_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": normalized_prefix}
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            response = self.client.list_objects_v2(**kwargs)
            keys.extend(item["Key"] for item in response.get("Contents", []))
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")
            if not continuation_token:
                break
        return keys

    def object_size(self, key: str) -> int | None:
        normalized_key = normalize_storage_key(key)
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=normalized_key)
            return int(response.get("ContentLength", 0))
        except Exception as exc:
            if _is_not_found_error(exc):
                return None
            raise

    def generate_presigned_url(self, key: str, expires_seconds: int = 300) -> str:
        normalized_key = normalize_storage_key(key)
        safe_expires = max(1, min(int(expires_seconds or 300), 3600))
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": normalized_key},
            ExpiresIn=safe_expires,
        )

    def get_path(self, key: str) -> Path:
        raise RuntimeError("R2 storage does not expose local filesystem paths.")


def normalize_storage_key(key: str) -> str:
    raw = str(key or "").replace("\\", "/").strip()
    if not raw:
        raise StorageKeyError("Storage key cannot be empty.")
    if raw.startswith("/") or PurePosixPath(raw).is_absolute():
        raise StorageKeyError("Storage key cannot be an absolute path.")
    if raw.lower().startswith("app/storage/") or raw.lower().startswith("storage/../"):
        raise StorageKeyError("Storage key must be relative to the storage root.")
    if ":" in PurePosixPath(raw).parts[0]:
        raise StorageKeyError("Storage key cannot include a drive or scheme.")
    value = raw.strip("/")
    if not value:
        raise StorageKeyError("Storage key cannot be empty.")

    pure = PurePosixPath(value)
    parts = pure.parts
    if any(part in {"", ".", ".."} for part in parts):
        raise StorageKeyError("Storage key contains an invalid path segment.")

    return "/".join(parts)


def normalize_storage_prefix(prefix: str = "") -> str:
    value = (prefix or "").replace("\\", "/").strip().strip("/")
    if not value:
        return ""
    return normalize_storage_key(value)


def _is_not_found_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str(response.get("Error", {}).get("Code", "")).lower()
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return code in {"404", "notfound", "nosuchkey"} or status == 404
    return False


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
    backend = (settings.storage_backend or "local").strip().lower()
    if backend == "local":
        return LocalFilesystemStorage(settings.storage_root)
    if backend == "r2":
        endpoint_url = settings.r2_endpoint_url
        if not endpoint_url and settings.r2_account_id:
            endpoint_url = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
        return R2StorageService(
            bucket=settings.r2_bucket_name or "",
            endpoint_url=endpoint_url or "",
            access_key_id=settings.r2_access_key_id or "",
            secret_access_key=settings.r2_secret_access_key or "",
            region_name=settings.r2_region or "auto",
        )
    raise RuntimeError(f"Unsupported storage backend: {settings.storage_backend}")
