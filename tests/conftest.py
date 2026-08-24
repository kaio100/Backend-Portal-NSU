from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet


# Esta configuracao precisa acontecer antes da coleta importar qualquer modulo
# do backend. Sem isso, testes que limpam tabelas podem reutilizar o
# DATABASE_URL do terminal e apagar o banco PostgreSQL local.
_TEST_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "test_suite.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH.as_posix()}"
os.environ["API_WORKER_ENABLED"] = "false"
os.environ["API_KEY"] = "api-key-test-with-at-least-32-bytes"
os.environ["JWT_SECRET"] = "jwt-secret-test-with-at-least-32-bytes"
os.environ["SECRETS_KEY"] = Fernet.generate_key().decode("utf-8")
for suffix in ("", "-shm", "-wal"):
    Path(f"{_TEST_DB_PATH}{suffix}").unlink(missing_ok=True)

# Congela as configuracoes de teste antes que os arquivos de teste possam
# sobrescrever variaveis de ambiente durante a coleta.
from backend.app.core.config import settings as _test_settings  # noqa: E402

assert _test_settings.database_url.startswith("sqlite:///")
assert "test_suite.db" in _test_settings.database_url


@pytest.fixture(autouse=True)
def authenticated_portal_user(request):
    """Autentica os testes funcionais legados no novo contrato do portal.

    Os testes de auth continuam usando JWT real. Os demais testam regras de
    negocio com uma identidade de portal conhecida, sem desativar a protecao
    na aplicacao nem precisar repetir a criacao de conta em cada caso.
    """
    if request.path.name == "test_auth_account.py":
        yield
        return

    from backend.app.api.deps import get_current_usuario
    from backend.app.main import app

    usuario = SimpleNamespace(
        id=1,
        empresa_id=1,
        email="portal-test@example.com",
        nome="Portal Test",
        ativo=True,
        grupo="planning_hub",
        is_admin=True,
        papel="admin",
    )
    app.dependency_overrides[get_current_usuario] = lambda: usuario
    try:
        yield usuario
    finally:
        app.dependency_overrides.pop(get_current_usuario, None)
