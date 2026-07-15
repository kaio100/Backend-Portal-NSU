from __future__ import annotations

import secrets

from backend.app.core.config import settings
from backend.app.scripts.r2_common import build_r2_storage


def main() -> int:
    storage = build_r2_storage()
    key = f"health/r2-test-{secrets.token_hex(8)}.txt"
    data = b"r2 ok"
    expires = int(settings.r2_presigned_expires_seconds or 300)

    storage.put_bytes(key, data, content_type="text/plain")
    if not storage.exists(key):
        raise RuntimeError("Uploaded R2 test object was not found.")
    downloaded = storage.get_bytes(key)
    if downloaded != data:
        raise RuntimeError("Downloaded R2 test object content does not match.")
    storage.generate_presigned_url(key, expires_seconds=expires)
    storage.delete(key)
    if storage.exists(key):
        raise RuntimeError("Deleted R2 test object still exists.")

    print("R2_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
