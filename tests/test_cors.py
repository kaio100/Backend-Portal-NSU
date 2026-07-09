from __future__ import annotations

import os

from cryptography.fernet import Fernet

os.environ["API_WORKER_ENABLED"] = "false"
os.environ["CORS_ORIGINS"] = "https://frontend-portal-nsu.vercel.app/"
os.environ["DATABASE_URL"] = "sqlite:///./data/test_cors.db"
os.environ["SECRETS_KEY"] = Fernet.generate_key().decode("utf-8")
os.environ["WORKER_DRY_RUN"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app, cors_origins  # noqa: E402


FRONTEND_ORIGIN = "https://frontend-portal-nsu.vercel.app"


def test_cors_origins_remove_trailing_slash() -> None:
    assert FRONTEND_ORIGIN in cors_origins
    assert f"{FRONTEND_ORIGIN}/" not in cors_origins


def test_cors_allows_frontend_origin_preflight() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": FRONTEND_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )

    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == FRONTEND_ORIGIN
    assert response.headers.get("access-control-allow-methods")
    assert response.headers.get("access-control-allow-headers")


def test_cors_allows_frontend_origin_get() -> None:
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": FRONTEND_ORIGIN})

    assert response.headers.get("access-control-allow-origin") == FRONTEND_ORIGIN


def test_cors_does_not_allow_unlisted_origin() -> None:
    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "https://example.invalid"})

    assert "access-control-allow-origin" not in response.headers


def test_cors_applies_to_notas_route() -> None:
    with TestClient(app) as client:
        response = client.get("/notas", headers={"Origin": FRONTEND_ORIGIN})

    assert response.headers.get("access-control-allow-origin") == FRONTEND_ORIGIN
