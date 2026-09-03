from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from backend.app.core.observability import metrics


router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "nfse-backend",
        "version": "0.1.0",
    }


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics_endpoint():
    return metrics.prometheus()
