from __future__ import annotations

from backend.app.core.config import settings
from backend.app.services.storage_service import R2StorageService


def build_r2_storage() -> R2StorageService:
    endpoint_url = settings.r2_endpoint_url
    if not endpoint_url and settings.r2_account_id:
        endpoint_url = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    missing = [
        name
        for name, value in (
            ("R2_BUCKET_NAME", settings.r2_bucket_name),
            ("R2_ENDPOINT_URL or R2_ACCOUNT_ID", endpoint_url),
            ("R2_ACCESS_KEY_ID", settings.r2_access_key_id),
            ("R2_SECRET_ACCESS_KEY", settings.r2_secret_access_key),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Missing R2 environment variables: " + ", ".join(missing))
    return R2StorageService(
        bucket=settings.r2_bucket_name or "",
        endpoint_url=endpoint_url or "",
        access_key_id=settings.r2_access_key_id or "",
        secret_access_key=settings.r2_secret_access_key or "",
        region_name=settings.r2_region or "auto",
    )
