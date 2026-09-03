from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key in ("event", "job_id", "processo_id", "nota_id", "arquivo_id", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


class Metrics:
    def __init__(self) -> None:
        self._values: dict[str, int] = {}
        self._lock = threading.Lock()

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._values[name] = self._values.get(name, 0) + value

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._values)

    def prometheus(self) -> str:
        lines = []
        for name, value in sorted(self.snapshot().items()):
            safe_name = "nfse_" + name.replace("-", "_")
            lines.append(f"# TYPE {safe_name} counter")
            lines.append(f"{safe_name} {value}")
        return "\n".join(lines) + ("\n" if lines else "")


metrics = Metrics()
logger = logging.getLogger("nfse.observability")


def configure_logging() -> None:
    level = str(settings.log_level or os.getenv("LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


def alert_failure(event: str, error: Exception | str, **context: Any) -> None:
    metrics.inc(f"{event}_failures")
    logger.error("Operacao falhou", extra={"event": event, **context}, exc_info=isinstance(error, Exception))
    webhook = str(settings.alert_webhook_url or os.getenv("ALERT_WEBHOOK_URL", "")).strip()
    if not webhook:
        return
    body = json.dumps({"event": event, "error": str(error)[:500], **context}).encode("utf-8")
    request = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=3):
            pass
    except Exception:
        logger.exception("Falha ao enviar alerta", extra={"event": "alert_webhook"})
