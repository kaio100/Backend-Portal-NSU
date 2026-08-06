from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "sqlite:///./data/test_auth_account.db"
os.environ["API_WORKER_ENABLED"] = "false"
os.environ["WORKER_DRY_RUN"] = "true"
os.environ["JWT_SECRET"] = "jwt-secret-test-with-at-least-32-bytes"
os.environ["SECRETS_KEY"] = Fernet.generate_key().decode("utf-8")
Path("data/test_auth_account.db").unlink(missing_ok=True)

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.db.models import Empresa, Usuario  # noqa: E402
from backend.app.db.session import SessionLocal, init_db  # noqa: E402
from backend.app.main import app  # noqa: E402


def _reset_db() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(Usuario).delete(synchronize_session=False)
        db.query(Empresa).delete(synchronize_session=False)
        db.commit()


def test_criar_conta_publica_cria_empresa_padrao_usuario_e_retorna_token():
    _reset_db()
    with TestClient(app) as client:
        response = client.post(
            "/auth/criar-conta",
            json={
                "nome": "Kaio",
                "email": "Kaio@Example.com",
                "senha": "senha-forte-123",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]
    assert payload["usuario"]["email"] == "kaio@example.com"
    assert payload["usuario"]["nome"] == "Kaio"

    with SessionLocal() as db:
        usuario = db.query(Usuario).filter(Usuario.email == "kaio@example.com").one()
        empresa = db.get(Empresa, usuario.empresa_id)
    assert empresa is not None
    assert empresa.nome == "Planning/Hub"
    assert empresa.cnpj.startswith("9")
    assert len(empresa.cnpj) == 14
    assert empresa.grupo == "planning_hub"
    assert usuario.empresa_id == empresa.id
    assert usuario.senha_hash != "senha-forte-123"


def test_register_alias_funciona_com_razao_social_e_cnpj():
    _reset_db()
    with TestClient(app) as client:
        response = client.post(
            "/auth/register",
            json={
                "email": "ana@example.com",
                "senha": "senha-forte-456",
                "razao_social": "Empresa Alias LTDA",
                "cnpj": "22333444000155",
            },
        )

    assert response.status_code == 200
    assert response.json()["usuario"]["email"] == "ana@example.com"


def test_criar_conta_bloqueia_email_duplicado():
    _reset_db()
    payload = {
        "email": "duplicado@example.com",
        "senha": "senha-forte-123",
        "nome": "Duplicado",
    }
    with TestClient(app) as client:
        first = client.post("/auth/criar-conta", json=payload)
        second = client.post("/auth/criar-conta", json=payload)

    assert first.status_code == 200
    assert second.status_code == 400
    assert "Ja existe" in second.json()["detail"]
