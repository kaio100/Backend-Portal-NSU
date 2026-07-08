from backend.app.db.session import get_db
from backend.app.services.storage_service import get_storage_service


def get_storage():
    return get_storage_service()
