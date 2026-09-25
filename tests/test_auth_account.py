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

from backend.app.core.security import create_access_token, hash_password  # noqa: E402
from backend.app.db.models import Empresa, Usuario  # noqa: E402
from backend.app.db.session import SessionLocal, init_db  # noqa: E402
from backend.app.main import app  # noqa: E402


def _reset_db() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(Usuario).delete(synchronize_session=False)
        db.query(Empresa).delete(synchronize_session=False)
        db.commit()


def _criar_usuario(*, email: str, is_admin: bool) -> tuple[Usuario, str]:
    with SessionLocal() as db:
        empresa = Empresa(nome="Empresa Segura", cnpj="12345678000199", ambiente="producao", ativo=True, grupo="planning_hub")
        db.add(empresa)
        db.flush()
        usuario = Usuario(
            empresa_id=empresa.id,
            email=email,
            senha_hash=hash_password("senha-forte-123"),
            nome="Administrador" if is_admin else "Operador",
            ativo=True,
            grupo="planning_hub",
            is_admin=is_admin,
        )
        db.add(usuario)
        db.commit()
        db.refresh(usuario)
        token = create_access_token(usuario.id, usuario.empresa_id)
        db.expunge(usuario)
        return usuario, token


def test_cadastro_sem_convite_valido_nao_cria_registros():
    # Desde 2026-09-25 o cadastro e por convite: sem convite valido nada e criado.
    _reset_db()
    payload = {"nome": "Atacante", "email": "atacante@example.com", "senha": "senha-forte-123", "grupo": "planning_hub", "cnpj": "22333444000155"}
    with TestClient(app) as client:
        sem_convite = client.post("/auth/criar-conta", json=payload)
        convite_falso = client.post("/auth/criar-conta", json={**payload, "convite": "convite-inventado-123"})
        register = client.post("/auth/register", json=payload)

    assert sem_convite.status_code == 422
    assert convite_falso.status_code == 404
    assert register.status_code == 404
    with SessionLocal() as db:
        assert db.query(Usuario).count() == 0
        assert db.query(Empresa).count() == 0


def test_listagem_de_grupos_exige_login_administrativo():
    _reset_db()
    _usuario, token = _criar_usuario(email="operador@example.com", is_admin=False)
    with TestClient(app) as client:
        sem_login = client.get("/auth/grupos")
        operador = client.get("/auth/grupos", headers={"Authorization": f"Bearer {token}"})

    assert sem_login.status_code == 401
    assert operador.status_code == 403


def test_administrador_pode_listar_grupos_e_login_existente_continua_funcionando():
    _reset_db()
    usuario, token = _criar_usuario(email="admin@example.com", is_admin=True)
    with TestClient(app) as client:
        grupos = client.get("/auth/grupos", headers={"Authorization": f"Bearer {token}"})
        login = client.post("/auth/login", json={"email": usuario.email, "senha": "senha-forte-123"})

    assert grupos.status_code == 200
    assert any(item["codigo"] == "planning_hub" for item in grupos.json())
    assert login.status_code == 200
    assert login.json()["usuario"]["email"] == usuario.email


def test_login_local_sem_senha_nao_existe_mais():
    # /auth/local entregava o token do primeiro admin para qualquer requisicao
    # que parecesse local (um tunel ngrok/cloudflared abria isso para fora).
    _reset_db()
    _criar_usuario(email="admin-local@example.com", is_admin=True)
    with TestClient(app) as client:
        resposta = client.post("/auth/local")
    assert resposta.status_code in {404, 405}
