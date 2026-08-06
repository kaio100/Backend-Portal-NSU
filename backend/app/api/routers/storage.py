from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_usuario, get_db
from backend.app.core.config import settings
from backend.app.db.models import Empresa, Usuario
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
def storage_test_write(usuario: Usuario = Depends(get_current_usuario)):
    storage = get_storage_service()
    key = f"health/{usuario.grupo}/storage-test.txt"
    return storage.put_bytes(key, TEST_CONTENT, content_type="text/plain")


@router.get("/test-read")
def storage_test_read(usuario: Usuario = Depends(get_current_usuario)):
    storage = get_storage_service()
    key = f"health/{usuario.grupo}/storage-test.txt"
    data = storage.get_bytes(key)
    response = {
        "backend": storage.backend,
        "key": key,
        "size": len(data),
        "content": data.decode("utf-8"),
    }
    if storage.backend == "local":
        response["path"] = str(storage.get_path(TEST_KEY))
    return response


@router.get("/list")
def storage_list(prefix: str = "", db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
    storage = get_storage_service()
    cnpjs = {str(cnpj) for (cnpj,) in db.query(Empresa.cnpj).filter(Empresa.grupo == usuario.grupo).all()}
    keys = [key for key in storage.list_keys(prefix=prefix) if any(cnpj in key for cnpj in cnpjs) or f"/{usuario.grupo}/" in key]
    return {
        "backend": storage.backend,
        "prefix": prefix,
        "keys": keys,
    }
