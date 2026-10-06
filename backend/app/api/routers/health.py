import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.core.config import settings
from backend.app.core.observability import metrics
from backend.app.services import operacao_service


router = APIRouter(tags=["health"])


def exigir_token_operacao(authorization: str | None = Header(default=None)) -> None:
    """/metrics e /health/operacao expoem contadores internos.

    Com METRICS_TOKEN definido exigem "Authorization: Bearer <token>". Sem ele
    ficam abertos so fora de producao; em producao respondem 404.
    """
    token = str(settings.metrics_token or "").strip()
    if not token:
        if settings.is_production:
            raise HTTPException(status_code=404, detail="Not Found")
        return
    recebido = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(recebido.encode("utf-8"), token.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Token de monitoramento invalido.")


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "nfse-backend",
        "version": "0.1.0",
    }


@router.get("/metrics", response_class=PlainTextResponse, dependencies=[Depends(exigir_token_operacao)])
async def metrics_endpoint():
    return metrics.prometheus()


@router.get("/health/operacao", dependencies=[Depends(exigir_token_operacao)])
def health_operacao(db: Session = Depends(get_db)):
    estado = operacao_service.estado_operacao(db)
    problemas = operacao_service.problemas(estado)
    return {"status": "alerta" if problemas else "ok", "problemas": problemas, **estado}
