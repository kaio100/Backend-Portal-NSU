"""Fase 4: contas por convite com codigo por e-mail e grupos separados."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app.api import deps
from backend.app.core.config import settings
from backend.app.core.rede import ip_cliente
from backend.app.core.security import create_access_token, hash_password
from backend.app.db.models import (
    AcessoUsuario,
    Arquivo,
    Certificado,
    ConferenciaHistorico,
    ConviteCadastro,
    Empresa,
    Evento,
    Grupo,
    Nota,
    Processo,
    RedefinicaoSenhaToken,
    Usuario,
    VerificacaoEmailToken,
)
from backend.app.db.session import SessionLocal, init_db
from backend.app.main import app
from backend.app.services import email_service

MODELOS = (
    ConferenciaHistorico, VerificacaoEmailToken, RedefinicaoSenhaToken, ConviteCadastro, AcessoUsuario,
    Evento, Arquivo, Nota, Processo, Certificado, Usuario, Empresa,
)


@pytest.fixture(autouse=True)
def _banco_limpo():
    init_db()

    def limpar():
        with SessionLocal() as db:
            for modelo in MODELOS:
                db.query(modelo).delete()
            db.query(Grupo).filter(Grupo.codigo.notin_(["planning_hub", "planning_ma"])).delete()
            db.query(Grupo).update({Grupo.ativo: True})
            db.commit()

    limpar()
    yield
    limpar()


@pytest.fixture()
def emails(monkeypatch):
    enviados: dict[str, list[str]] = {"cadastro": [], "senha": []}
    monkeypatch.setattr(email_service, "enviar_codigo_cadastro", lambda para, codigo: enviados["cadastro"].append(codigo))
    monkeypatch.setattr(email_service, "enviar_codigo_senha", lambda para, codigo: enviados["senha"].append(codigo))
    return enviados


def _empresa(grupo: str = "planning_hub", cnpj: str = "22333444000155") -> int:
    with SessionLocal() as db:
        empresa = Empresa(nome=f"Empresa {grupo}", cnpj=cnpj, ambiente="producao", ativo=True, grupo=grupo)
        db.add(empresa)
        db.commit()
        return int(empresa.id)


def _usuario(email: str, grupo: str = "planning_hub", papel: str = "operador", senha: str = "senha-forte-123") -> int:
    with SessionLocal() as db:
        empresa = db.query(Empresa).filter(Empresa.grupo == grupo).first()
        usuario = Usuario(
            empresa_id=empresa.id, email=email, senha_hash=hash_password(senha), nome=email.split("@")[0],
            ativo=True, grupo=grupo, papel=papel, is_admin=papel == "admin", email_verificado=True, token_version=0,
        )
        db.add(usuario)
        db.commit()
        return int(usuario.id)


# ----------------------------------------------------------------- convite


def test_convite_cria_conta_de_operador_no_grupo_so_depois_do_codigo(emails):
    _empresa()
    with TestClient(app) as client:
        convite = client.post("/auth/convites", json={"nome": "Nova analista"}).json()
        info = client.get(f"/auth/convite/{convite['token']}")
        cadastro = client.post(
            "/auth/criar-conta",
            json={"convite": convite["token"], "nome": "Nova", "email": "nova@example.com", "senha": "senha-forte-123"},
        )
        antes = client.post("/auth/login", json={"email": "nova@example.com", "senha": "senha-forte-123"})
        errado = client.post("/auth/verificar-email", json={"email": "nova@example.com", "codigo": "000000" if emails["cadastro"][0] != "000000" else "111111"})
        certo = client.post("/auth/verificar-email", json={"email": "nova@example.com", "codigo": emails["cadastro"][0]})
        depois = client.post("/auth/login", json={"email": "nova@example.com", "senha": "senha-forte-123"})
        reuso = client.post(
            "/auth/criar-conta",
            json={"convite": convite["token"], "nome": "Outra", "email": "outra@example.com", "senha": "senha-forte-123"},
        )

    assert info.status_code == 200 and info.json()["grupo"] == "planning_hub"
    assert cadastro.status_code == 202
    assert antes.status_code == 401  # conta pendente ate confirmar o e-mail
    assert errado.status_code == 400
    assert certo.status_code == 200 and certo.json()["access_token"]
    assert certo.json()["usuario"]["papel"] == "operador"
    assert certo.json()["usuario"]["grupo"] == "planning_hub"
    assert depois.status_code == 200
    assert reuso.status_code == 410  # convite de uso unico
    with SessionLocal() as db:
        assert db.query(ConviteCadastro).one().usos_atuais == 1


def test_codigo_bloqueia_depois_de_cinco_erros(emails):
    _empresa()
    with TestClient(app) as client:
        token = client.post("/auth/convites", json={}).json()["token"]
        client.post("/auth/criar-conta", json={"convite": token, "nome": "X", "email": "x5@example.com", "senha": "senha-forte-123"})
        codigo = emails["cadastro"][0]
        errado = "999999" if codigo != "999999" else "888888"
        for _ in range(5):
            client.post("/auth/verificar-email", json={"email": "x5@example.com", "codigo": errado})
        certo = client.post("/auth/verificar-email", json={"email": "x5@example.com", "codigo": codigo})
    assert certo.status_code == 400


def test_convite_expirado_ou_revogado_nao_serve(emails):
    _empresa()
    with TestClient(app) as client:
        expirado = client.post("/auth/convites", json={}).json()
        revogado = client.post("/auth/convites", json={}).json()
        with SessionLocal() as db:
            convite = db.get(ConviteCadastro, expirado["id"])
            convite.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            db.commit()
        assert client.delete(f"/auth/convites/{revogado['id']}").status_code == 200
        r_expirado = client.get(f"/auth/convite/{expirado['token']}")
        r_revogado = client.get(f"/auth/convite/{revogado['token']}")
    assert r_expirado.status_code == 410
    assert r_revogado.status_code == 404


def test_convite_de_grupo_sem_empresa_avisa(emails):
    _empresa()  # so planning_hub tem empresa
    with SessionLocal() as db:
        db.add(ConviteCadastro(token_hash=__import__("hashlib").sha256(b"token-grupo-ma-123").hexdigest(),
                               grupo="planning_ma", ativo=True, max_usos=1, usos_atuais=0,
                               expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
        db.commit()
    with TestClient(app) as client:
        resposta = client.post(
            "/auth/criar-conta",
            json={"convite": "token-grupo-ma-123", "nome": "MA", "email": "ma@example.com", "senha": "senha-forte-123"},
        )
    assert resposta.status_code == 409
    assert "empresas" in resposta.json()["detail"]


# ----------------------------------------------------------------- senha


def test_esqueci_minha_senha_com_codigo_derruba_as_sessoes(emails):
    _empresa()
    usuario_id = _usuario("senha@example.com", senha="senha-antiga-123")
    token_antigo = create_access_token(usuario_id, 1, 0)
    with TestClient(app) as client:
        inexistente = client.post("/auth/recuperar-senha", json={"email": "ninguem@example.com"})
        pedido = client.post("/auth/recuperar-senha", json={"email": "senha@example.com"})
        codigo = emails["senha"][0]
        errado = client.post("/auth/redefinir-senha", json={"email": "senha@example.com", "codigo": "000000" if codigo != "000000" else "111111", "nova_senha": "senha-nova-456"})
        certo = client.post("/auth/redefinir-senha", json={"email": "senha@example.com", "codigo": codigo, "nova_senha": "senha-nova-456"})
        login_antigo = client.post("/auth/login", json={"email": "senha@example.com", "senha": "senha-antiga-123"})
        login_novo = client.post("/auth/login", json={"email": "senha@example.com", "senha": "senha-nova-456"})

    assert inexistente.status_code == 200 and pedido.status_code == 200
    assert inexistente.json()["mensagem"] == pedido.json()["mensagem"]  # nao revela quem tem conta
    assert len(emails["senha"]) == 1
    assert errado.status_code == 400 and certo.status_code == 200
    assert login_antigo.status_code == 401 and login_novo.status_code == 200
    with SessionLocal() as db, pytest.raises(HTTPException) as erro:
        deps.get_current_usuario(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_antigo), db)
    assert erro.value.status_code == 401


def test_grupo_desativado_perde_o_acesso():
    _empresa(grupo="planning_ma", cnpj="11222333000181")
    usuario_id = _usuario("ma@example.com", grupo="planning_ma")
    token = create_access_token(usuario_id, 1, 0)
    with SessionLocal() as db:
        db.query(Grupo).filter(Grupo.codigo == "planning_ma").update({Grupo.ativo: False})
        db.commit()
        with pytest.raises(HTTPException) as erro:
            deps.get_current_usuario(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), db)
    assert erro.value.status_code == 403


def test_ip_real_atras_do_proxy():
    def req(cliente: str, xff: str | None = None) -> Request:
        headers = [(b"x-forwarded-for", xff.encode())] if xff else []
        return Request({"type": "http", "client": (cliente, 1234), "headers": headers})

    # Pelo proxy interno do Railway: vale o endereco que o proxy acrescentou.
    assert ip_cliente(req("100.64.0.6", "1.2.3.4, 200.10.20.30")) == "200.10.20.30"
    # Direto da internet: o cabecalho e ignorado (poderia ser forjado).
    assert ip_cliente(req("200.10.20.30", "1.2.3.4")) == "200.10.20.30"
    assert ip_cliente(req("100.64.0.6")) == "100.64.0.6"


# ----------------------------------------------------------------- admin por grupo


def test_admin_so_enxerga_e_altera_o_proprio_grupo():
    _empresa()
    _empresa(grupo="planning_ma", cnpj="11222333000181")
    _usuario("hub@example.com")
    ma_id = _usuario("ma@example.com", grupo="planning_ma")
    hub_id = _usuario("hub2@example.com")
    with TestClient(app) as client:
        lista = client.get("/admin/usuarios").json()
        patch_outro = client.patch(f"/admin/usuarios/{ma_id}", json={"nome": "Invadido"})
        senha_outro = client.post(f"/admin/usuarios/{ma_id}/redefinir-senha", json={"senha": "senha-nova-123"})
        mover = client.patch(f"/admin/usuarios/{hub_id}", json={"grupo": "planning_ma"})
        criar_grupo = client.post("/admin/grupos", json={"nome": "Grupo Novo"})
        grupos = client.get("/admin/grupos").json()

    assert {u["email"] for u in lista} == {"hub@example.com", "hub2@example.com"}
    assert patch_outro.status_code == 404
    assert senha_outro.status_code == 404
    assert mover.status_code == 403
    assert criar_grupo.status_code == 403
    assert [g["codigo"] for g in grupos] == ["planning_hub"]


def test_admin_geral_enxerga_todos_os_grupos(monkeypatch):
    _empresa()
    _empresa(grupo="planning_ma", cnpj="11222333000181")
    _usuario("hub@example.com")
    ma_id = _usuario("ma@example.com", grupo="planning_ma")
    monkeypatch.setattr(settings, "super_admin_emails", "portal-test@example.com")
    with TestClient(app) as client:
        lista = client.get("/admin/usuarios").json()
        patch_outro = client.patch(f"/admin/usuarios/{ma_id}", json={"nome": "Ajustado"})
    assert {u["email"] for u in lista} == {"hub@example.com", "ma@example.com"}
    assert patch_outro.status_code == 200


def test_criacao_interna_de_usuario_usa_o_grupo_da_empresa(monkeypatch):
    empresa_ma = _empresa(grupo="planning_ma", cnpj="11222333000181")
    with TestClient(app) as client:
        resposta = client.post(
            "/auth/usuarios",
            headers={"X-API-Key": settings.api_key},
            json={"empresa_id": empresa_ma, "email": "interno@example.com", "senha": "senha-forte-123"},
        )
    assert resposta.status_code == 200
    assert resposta.json()["grupo"] == "planning_ma"


# ----------------------------------------------------------------- isolamento


def test_usuario_de_um_grupo_nao_ve_dados_do_outro():
    hub = _empresa()
    ma = _empresa(grupo="planning_ma", cnpj="11222333000181")
    chave = "7" * 50
    with SessionLocal() as db:
        # A mesma nota existe nas duas empresas (uma emitiu, a outra tomou).
        nota_hub = Nota(empresa_id=hub, chave=chave, status_documento="autorizada")
        nota_ma = Nota(empresa_id=ma, chave=chave, status_documento="autorizada")
        db.add_all([nota_hub, nota_ma])
        db.flush()
        db.add(Evento(empresa_id=ma, nota_id=nota_ma.id, chave_evento="EV-MA", chave_afetada=chave, tipo_evento="cancelada"))
        cert_ma = Certificado(empresa_id=ma, nome="Certificado MA", storage_key="certificados/ma.pfx", ativo=True)
        processo_ma = Processo(empresa_id=ma, tipo="consulta_nfse", status="finalizado")
        db.add_all([cert_ma, processo_ma])
        db.flush()
        arquivo_ma = Arquivo(empresa_id=ma, nota_id=nota_ma.id, tipo="XML", storage_backend="local", storage_key="xml/ma.xml")
        db.add(arquivo_ma)
        db.commit()
        ids = {"nota_hub": nota_hub.id, "nota_ma": nota_ma.id, "cert_ma": cert_ma.id, "processo_ma": processo_ma.id, "arquivo_ma": arquivo_ma.id}

    with TestClient(app) as client:
        respostas = {
            "nota": client.get(f"/notas/{ids['nota_ma']}").status_code,
            "eventos_nota": client.get("/eventos", params={"nota_id": ids["nota_ma"]}).status_code,
            "processo": client.get(f"/processos/{ids['processo_ma']}").status_code,
            "arquivo": client.get(f"/arquivos/{ids['arquivo_ma']}/download").status_code,
            "certificado": client.get(f"/certificados/{ids['cert_ma']}").status_code,
            "empresa": client.get(f"/empresas/{ma}").status_code,
            "historico": client.get(f"/notas/{ids['nota_ma']}/historico").status_code,
        }
        por_chave = client.get(f"/notas/chave/{chave}")
        eventos_hub = client.get(f"/notas/{ids['nota_hub']}/eventos").json()
        nsu = client.get(f"/empresas/{hub}/nsu", params={"certificado_id": ids["cert_ma"]}).json()
        lista = client.get("/notas").json()

    assert set(respostas.values()) == {404}, respostas
    assert por_chave.status_code == 200 and por_chave.json()["id"] == ids["nota_hub"]
    assert all(item.get("id") != "EV-MA" and item.get("status") != "cancelada" for item in eventos_hub["items"])
    assert nsu["certificado_nome"] is None
    assert [item["id"] for item in lista] == [ids["nota_hub"]]


def test_so_operador_e_admin_existem():
    assert deps.PAPEIS_VALIDOS == frozenset({"admin", "operador"})
    with pytest.raises(HTTPException):
        deps.require_operator(SimpleNamespace(papel="leitura", is_admin=False))
