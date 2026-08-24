from __future__ import annotations

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import _documentation_options, app


def test_production_detection_includes_railway_environment():
    settings = Settings(
        environment="local",
        railway_environment_name="production",
        api_key="a" * 32,
        jwt_secret="j" * 32,
        secrets_key=Fernet.generate_key().decode("utf-8"),
    )
    assert settings.is_production is True


def test_documentation_is_disabled_in_production():
    assert _documentation_options(True) == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }


def test_security_headers_are_added_to_responses():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == "camera=(), geolocation=(), microphone=()"
