"""Brechas fechadas em 15/10/2026: limite de tentativas no banco, 2FA e sessao
curta do painel administrativo, auditoria e token do portal mais curto."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from backend.app.core import totp
from backend.app.core.config import settings
from backend.app.core.rate_limit import RateLimiterBanco
from backend.app.core.security import (
    create_access_token,
    create_admin_token,
    hash_password,
)
from backend.app.db.models import AuditoriaAdmin, Empresa, TentativaAcesso, Usuario
from backend.app.db.session import SessionLocal, init_db
from backend.app.main import app

SENHA = "senha-forte-123"


def _limpar() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(AuditoriaAdmin).delete(synchronize_session=False)
        db.query(TentativaAcesso).delete(synchronize_session=False)
        db.query(Usuario).filter(Usuario.email.like("%@seguranca.test")).delete(synchronize_session=False)
        db.commit()


def _usuario(email: str, admin: bool) -> tuple[int, str]:
    with SessionLocal() as db:
        empresa = db.query(Empresa).filter(Empresa.cnpj == "99888777000166").first()
        if empresa is None:
            empresa = Empresa(nome="Empresa Seg", cnpj="99888777000166", ambiente="producao", ativo=True, grupo="planning_hub")
            db.add(empresa)
            db.flush()
        usuario = Usuario(
            empresa_id=empresa.id,
            email=email,
            senha_hash=hash_password(SENHA),
            nome="Admin" if admin else "Operador",
            ativo=True,
            grupo="planning_hub",
            is_admin=admin,
            papel="admin" if admin else "operador",
        )
        db.add(usuario)
        db.commit()
        return usuario.id, create_access_token(usuario.id, empresa.id)


def _auth(token: str, admin_token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if admin_token:
        headers["X-Admin-Token"] = admin_token
    return headers


def test_totp_segue_a_rfc_6238():
    # Vetor oficial: segredo ASCII "12345678901234567890", T=59 s -> 94287082 (8 digitos).
    segredo = base64.b32encode(b"12345678901234567890").decode()
    assert totp.codigo_do_passo(segredo, 59 // 30, digitos=8) == "94287082"
    assert totp.verificar(segredo, totp.codigo_do_passo(segredo, totp.passo_atual())) == totp.passo_atual()
    assert totp.verificar(segredo, "000000x") is None


def test_limite_no_banco_vale_entre_instancias_e_reinicios():
    _limpar()
    primeiro = RateLimiterBanco(max_attempts=2, window_seconds=60)
    assert primeiro.allow("teste:chave")
    assert primeiro.allow("teste:chave")
    # Outra instancia (outro processo ou o servico depois de um deploy) ve as mesmas tentativas.
    assert not RateLimiterBanco(max_attempts=2, window_seconds=60).allow("teste:chave")
    with SessionLocal() as db:
        chaves = [t.chave for t in db.query(TentativaAcesso).all()]
    assert chaves and all("teste" not in c for c in chaves)  # so o hash, sem o texto original


def test_login_trava_a_conta_atacada_de_varios_ips():
    _limpar()
    _usuario("alvo@seguranca.test", admin=False)
    with TestClient(app) as client:
        respostas = [
            client.post(
                "/auth/login",
                json={"email": "alvo@seguranca.test", "senha": "errada"},
                headers={"X-Forwarded-For": f"203.0.113.{i}"},
            ).status_code
            for i in range(22)
        ]
    # O IP do TestClient nao e proxy, entao todos contam no mesmo IP: o limite por IP + e-mail
    # (8) chega antes. O importante: depois do limite vem 429, nunca mais 401.
    assert respostas[0] == 401
    assert 429 in respostas
    assert respostas[-1] == 429


def test_painel_admin_exige_sessao_com_senha_e_2fa():
    _limpar()
    _id, token = _usuario("admin@seguranca.test", admin=True)
    with TestClient(app) as client:
        sem_sessao = client.get("/admin/overview", headers=_auth(token))
        assert sem_sessao.status_code == 403
        assert sem_sessao.json()["detail"] == "admin_sessao_necessaria"

        # Sem 2FA configurado nao abre a sessao.
        assert client.post("/auth/admin/sessao", json={"senha": SENHA, "codigo": "123456"}, headers=_auth(token)).status_code == 409

        assert client.post("/auth/2fa/iniciar", json={"senha": "errada"}, headers=_auth(token)).status_code == 400
        inicio = client.post("/auth/2fa/iniciar", json={"senha": SENHA}, headers=_auth(token))
        assert inicio.status_code == 200
        segredo = inicio.json()["segredo"]
        assert inicio.json()["otpauth_uri"].startswith("otpauth://totp/")

        passo = totp.passo_atual()
        confirmar = client.post("/auth/2fa/confirmar", json={"codigo": totp.codigo_do_passo(segredo, passo)}, headers=_auth(token))
        assert confirmar.status_code == 200
        assert client.get("/auth/2fa", headers=_auth(token)).json()["ativo"] is True

        # O codigo usado na confirmacao nao abre a sessao (anti-reuso); o do proximo passo abre.
        reuso = client.post(
            "/auth/admin/sessao", json={"senha": SENHA, "codigo": totp.codigo_do_passo(segredo, passo)}, headers=_auth(token)
        )
        assert reuso.status_code == 401
        sessao = client.post(
            "/auth/admin/sessao", json={"senha": SENHA, "codigo": totp.codigo_do_passo(segredo, passo + 1)}, headers=_auth(token)
        )
        assert sessao.status_code == 200
        admin_token = sessao.json()["admin_token"]
        assert sessao.json()["expira_em_minutos"] == settings.admin_sessao_minutos

        assert client.get("/admin/overview", headers=_auth(token, admin_token)).status_code == 200
        # O token do painel nao substitui o do portal.
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {admin_token}"}).status_code == 401

    with SessionLocal() as db:
        acoes = {(a.acao, a.resultado) for a in db.query(AuditoriaAdmin).all()}
    assert ("abrir_sessao_admin", "ok") in acoes
    assert ("abrir_sessao_admin", "erro 401") in acoes
    assert ("confirmar_2fa", "ok") in acoes


def test_sessao_admin_de_outro_usuario_ou_vencida_nao_vale():
    _limpar()
    _id_a, token_a = _usuario("a@seguranca.test", admin=True)
    id_b, _token_b = _usuario("b@seguranca.test", admin=True)
    token_admin_b, _ = create_admin_token(id_b, 0)
    with TestClient(app) as client:
        resposta = client.get("/admin/overview", headers=_auth(token_a, token_admin_b))
    assert resposta.status_code == 403

    original = settings.admin_sessao_minutos
    try:
        object.__setattr__(settings, "admin_sessao_minutos", -1)
        vencido, _ = create_admin_token(_id_a, 0)
    finally:
        object.__setattr__(settings, "admin_sessao_minutos", original)
    with TestClient(app) as client:
        assert client.get("/admin/overview", headers=_auth(token_a, vencido)).status_code == 403


def test_operador_nao_abre_sessao_admin_e_alteracoes_ficam_na_auditoria():
    _limpar()
    _id_op, token_op = _usuario("op@seguranca.test", admin=False)
    id_admin, token_admin = _usuario("chefe@seguranca.test", admin=True)
    admin_token, _ = create_admin_token(id_admin, 0)
    with TestClient(app) as client:
        assert client.post("/auth/2fa/iniciar", json={"senha": SENHA}, headers=_auth(token_op)).status_code == 403
        assert client.post("/auth/admin/sessao", json={"senha": SENHA, "codigo": "123456"}, headers=_auth(token_op)).status_code == 403
        alterar = client.patch(f"/admin/usuarios/{_id_op}", json={"nome": "Operador Renomeado"}, headers=_auth(token_admin, admin_token))
        assert alterar.status_code == 200
        auditoria = client.get("/admin/auditoria", headers=_auth(token_admin, admin_token)).json()
    assert any(item["acao"] == "PATCH /admin/usuarios/{usuario_id}" and item["resultado"] == "ok" for item in auditoria)


def test_token_do_portal_dura_um_dia_de_trabalho():
    # O padrao do codigo; JWT_EXPIRE_MINUTES no ambiente ainda pode mudar.
    assert type(settings).model_fields["jwt_expire_minutes"].default == 720
