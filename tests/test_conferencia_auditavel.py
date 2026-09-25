"""Analise fiscal auditavel: trava de retificacao, autor do login e historico."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.core.security import hash_password
from backend.app.db.models import AcessoUsuario, Arquivo, ConferenciaHistorico, Empresa, Evento, Nota, Usuario
from backend.app.db.session import SessionLocal, engine, init_db
from backend.app.main import app


@pytest.fixture(autouse=True)
def _banco_limpo():
    init_db()

    def limpar():
        with SessionLocal() as db:
            for modelo in (ConferenciaHistorico, AcessoUsuario, Evento, Arquivo, Nota, Usuario, Empresa):
                db.query(modelo).delete()
            db.commit()

    limpar()
    yield
    limpar()


def _nota() -> int:
    with SessionLocal() as db:
        empresa = Empresa(nome="Auditoria LTDA", cnpj="22333444000155", ambiente="producao", ativo=True, grupo="planning_hub")
        db.add(empresa)
        db.flush()
        nota = Nota(
            empresa_id=empresa.id,
            chave="1" * 50,
            numero_nfse="1",
            prestador_cnpj="11222333000181",
            tomador_cnpj="22333444000155",
            valor_servico=Decimal("100.00"),
            valor_liquido=Decimal("100.00"),
            status_documento="autorizada",
        )
        db.add(nota)
        db.commit()
        return int(nota.id)


def test_analise_e_retificacao_ficam_no_historico_com_autor_do_login():
    nota_id = _nota()
    with TestClient(app) as client:
        primeira = client.patch(
            f"/notas/{nota_id}/conferencia",
            headers={"X-Responsavel": "Outra Pessoa"},
            json={"conferencia_status": "ok", "responsavel": "Outra Pessoa", "atualizado_em": "2020-01-01T00:00:00Z"},
        )
        bloqueada = client.patch(f"/notas/{nota_id}/conferencia", json={"conferencia_status": "corrigir"})
        retificada = client.patch(
            f"/notas/{nota_id}/conferencia",
            json={"conferencia_status": "corrigir", "observacao": "IRRF errado", "retificar": True},
        )
        historico = client.get(f"/notas/{nota_id}/historico")

    assert primeira.status_code == 200
    assert primeira.json()["responsavel"] == "Portal Test"
    assert not primeira.json()["conferencia_atualizado_em"].startswith("2020")
    assert bloqueada.status_code == 409
    assert retificada.status_code == 200

    itens = historico.json()["items"]
    assert [item["acao"] for item in itens] == ["retificacao", "analise"]
    assert all(item["usuario_email"] == "portal-test@example.com" for item in itens)
    assert itens[1]["alteracoes"]["conferencia_status"] == {"de": None, "para": "ok"}
    assert itens[0]["alteracoes"]["conferencia_status"] == {"de": "ok", "para": "corrigir"}
    assert itens[0]["alteracoes"]["conferencia_observacao"] == {"de": None, "para": "IRRF errado"}


def test_put_nfse_nao_contorna_a_trava_de_retificacao():
    nota_id = _nota()
    with TestClient(app) as client:
        client.patch(f"/notas/{nota_id}/conferencia", json={"conferencia_status": "ok"})
        atalho = client.put(f"/nfse/{nota_id}", json={"status": "divergente", "responsavel": "Outra Pessoa"})
        retificado = client.put(f"/nfse/{nota_id}", json={"status": "divergente", "retificar": True})
        invalido = client.put(f"/nfse/{nota_id}", json={"status": "qualquer coisa", "retificar": True})

    assert atalho.status_code == 409
    assert retificado.status_code == 200
    assert retificado.json()["responsavel"] == "Portal Test"
    assert invalido.status_code == 422
    with SessionLocal() as db:
        assert db.query(ConferenciaHistorico).count() == 2


@pytest.mark.parametrize(
    "corpo",
    [
        {"conferencia_status": "ok", "prioridade": "urgentissima"},
        {"conferencia_status": "ok", "status_fila_manual": "correto demais"},
        {"conferencia_status": "ok", "divergencia": "x" * 121},
        {"conferencia_status": "ok", "valor_liquido_correto": -1},
        {"conferencia_status": "ok", "observacao": "x" * 4001},
    ],
)
def test_conferencia_rejeita_valores_fora_da_lista_ou_do_tamanho(corpo):
    nota_id = _nota()
    with TestClient(app) as client:
        resposta = client.patch(f"/notas/{nota_id}/conferencia", json=corpo)
    assert resposta.status_code == 422


def test_conferencia_aceita_sinonimos_e_normaliza():
    nota_id = _nota()
    with TestClient(app) as client:
        resposta = client.patch(
            f"/notas/{nota_id}/conferencia",
            json={"conferencia_status": "ok", "prioridade_manual": "High", "status_fila_manual": "OK"},
        )
    assert resposta.status_code == 200
    with SessionLocal() as db:
        nota = db.get(Nota, nota_id)
        assert (nota.prioridade_manual, nota.status_fila_manual) == ("alta", "correta")


def test_excluir_usuario_mantem_o_historico():
    nota_id = _nota()
    with SessionLocal() as db:
        nota = db.get(Nota, nota_id)
        # O admin simulado dos testes tem id 1; o autor precisa ser outro usuario.
        db.add(Usuario(
            empresa_id=nota.empresa_id, email="admin-real@example.com", senha_hash=hash_password("senha-segura"),
            nome="Admin", ativo=True, grupo="planning_hub", papel="admin", is_admin=True,
        ))
        db.flush()
        autor = Usuario(
            empresa_id=nota.empresa_id, email="autor@example.com", senha_hash=hash_password("senha-segura"),
            nome="Autor", ativo=True, grupo="planning_hub", papel="operador",
        )
        db.add(autor)
        db.flush()
        db.add(ConferenciaHistorico(
            nota_id=nota_id, empresa_id=nota.empresa_id, chave=nota.chave, usuario_id=autor.id,
            usuario_nome="Autor", usuario_email="autor@example.com", acao="analise",
            alteracoes={"conferencia_status": {"de": None, "para": "ok"}},
        ))
        db.commit()
        autor_id = int(autor.id)

    with TestClient(app) as client:
        resposta = client.delete(f"/admin/usuarios/{autor_id}")

    assert resposta.status_code == 200
    with SessionLocal() as db:
        registro = db.query(ConferenciaHistorico).one()
        assert registro.usuario_id is None
        assert registro.usuario_email == "autor@example.com"


def test_migracoes_alembic_ficam_no_head():
    with engine.connect() as conexao:
        versao = conexao.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert versao == "0002_historico_conferencia"
