from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from backend.app.db.session import SessionLocal


router = APIRouter(prefix="/db", tags=["database"])


@router.get("/health")
def db_health():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Database connection failed.") from exc

    return {
        "status": "ok",
        "database": "connected",
    }
