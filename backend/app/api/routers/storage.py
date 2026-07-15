from fastapi import APIRouter

from backend.app.core.config import settings
from backend.app.services.storage_service import get_storage_service


router = APIRouter(prefix="/storage", tags=["storage"])

TEST_KEY = "health/storage-test.txt"
TEST_CONTENT = b"storage ok"


@router.get("/health")
def storage_health():
    data = {
        "status": "ok",
        "backend": settings.storage_backend,
    }
    if settings.storage_backend == "local":
        data["root"] = settings.storage_root
    return data


@router.post("/test-write")
def storage_test_write():
    storage = get_storage_service()
    return storage.put_bytes(TEST_KEY, TEST_CONTENT, content_type="text/plain")


@router.get("/test-read")
def storage_test_read():
    storage = get_storage_service()
    data = storage.get_bytes(TEST_KEY)
    response = {
        "backend": storage.backend,
        "key": TEST_KEY,
        "size": len(data),
        "content": data.decode("utf-8"),
    }
    if storage.backend == "local":
        response["path"] = str(storage.get_path(TEST_KEY))
    return response


@router.get("/list")
def storage_list(prefix: str = ""):
    storage = get_storage_service()
    return {
        "backend": storage.backend,
        "prefix": prefix,
        "keys": storage.list_keys(prefix=prefix),
    }
