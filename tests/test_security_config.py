from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import ValidationError

from backend.app.api.deps import require_api_key
from backend.app.core.config import Settings, settings


def _production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "api_key": "a" * 32,
        "jwt_secret": "j" * 32,
        "secrets_key": Fernet.generate_key().decode("utf-8"),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize("missing", ["api_key", "jwt_secret", "secrets_key"])
def test_producao_recusa_segredo_obrigatorio_ausente(missing: str):
    with pytest.raises(ValidationError, match=missing.upper()):
        _production_settings(**{missing: None})


def test_producao_recusa_chaves_fracas_ou_formato_fernet_invalido():
    with pytest.raises(ValidationError, match="API_KEY"):
        _production_settings(api_key="curta")
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        _production_settings(jwt_secret="curta")
    with pytest.raises(ValidationError, match="Fernet"):
        _production_settings(secrets_key="nao-e-fernet")


def test_railway_production_ativa_validacao_mesmo_com_environment_local():
    with pytest.raises(ValidationError, match="API_KEY"):
        Settings(
            _env_file=None,
            environment="local",
            railway_environment_name="production",
            api_key=None,
            jwt_secret="j" * 32,
            secrets_key=Fernet.generate_key().decode("utf-8"),
        )


def test_local_permite_segredos_ausentes_para_desenvolvimento():
    configured = Settings(
        _env_file=None,
        environment="local",
        railway_environment_name=None,
        api_key=None,
        jwt_secret=None,
        secrets_key=None,
    )
    assert configured.api_key is None


def test_api_key_falha_fechada_quando_nao_configurada(monkeypatch):
    monkeypatch.setattr(settings, "api_key", None)
    with pytest.raises(HTTPException) as exc_info:
        require_api_key(None)
    assert exc_info.value.status_code == 503


def test_api_key_rejeita_invalida_e_aceita_valida(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "k" * 32)
    with pytest.raises(HTTPException) as exc_info:
        require_api_key("incorreta")
    assert exc_info.value.status_code == 401
    assert require_api_key("k" * 32) is None
