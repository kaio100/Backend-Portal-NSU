from __future__ import annotations

from types import SimpleNamespace

import pytest


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
        is_admin=False,
    )
    app.dependency_overrides[get_current_usuario] = lambda: usuario
    try:
        yield usuario
    finally:
        app.dependency_overrides.pop(get_current_usuario, None)
