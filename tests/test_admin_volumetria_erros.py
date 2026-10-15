"""Painel admin: "Limpar" erros sem apagar historico e numeros da Volumetria."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.db.models import (
    Arquivo,
    Certificado,
    Empresa,
    ErroVisto,
    Evento,
    Job,
    LogProcesso,
    Nota,
    NsuControle,
    Processo,
)
from backend.app.db.session import SessionLocal, init_db
from backend.app.main import app


def _preparar() -> int:
    init_db()
    with SessionLocal() as db:
        for modelo in (ErroVisto, LogProcesso, Job, Evento, Arquivo, Nota, NsuControle, Processo, Certificado, Empresa):
            db.query(modelo).delete()
        db.commit()
        empresa = Empresa(nome="Empresa Vol", cnpj="11222333000181", ambiente="producao", ativo=True, grupo="planning_hub")
        outra = Empresa(nome="Outro Grupo", cnpj="99888777000166", ambiente="producao", ativo=True, grupo="planning_ma")
        db.add_all([empresa, outra])
        db.commit()
        hoje = date.today()
        notas = [
            # tomada (empresa e tomadora), prestada, cancelada
            Nota(empresa_id=empresa.id, chave="V1", data_emissao=hoje, tomador_cnpj=empresa.cnpj, prestador_cnpj="1",
                 valor_servico=100, status_documento="normal"),
            Nota(empresa_id=empresa.id, chave="V2", data_emissao=hoje - timedelta(days=1), prestador_cnpj=empresa.cnpj,
                 tomador_cnpj="2", valor_servico=50, status_documento="cancelada", responsavel="Ana"),
            Nota(empresa_id=empresa.id, chave="V3", data_emissao=hoje - timedelta(days=40), tomador_cnpj=empresa.cnpj,
                 valor_servico=10, status_documento="normal"),
            # outro grupo: nunca entra nos numeros do admin do planning_hub
            Nota(empresa_id=outra.id, chave="X1", data_emissao=hoje, valor_servico=999, status_documento="normal"),
        ]
        db.add_all(notas)
        agora = datetime.now(timezone.utc)
        db.add(Processo(empresa_id=empresa.id, tipo="consulta_nfse", status="erro", erro_resumo="Falha no ADN",
                        started_at=agora - timedelta(minutes=2), finished_at=agora))
        db.add(Processo(empresa_id=empresa.id, tipo="consulta_nfse", status="finalizado",
                        started_at=agora - timedelta(seconds=90), finished_at=agora))
        db.commit()
        return int(empresa.id)


def test_limpar_erros_esconde_os_vistos_sem_apagar_e_mostra_os_novos():
    empresa_id = _preparar()
    with TestClient(app) as client:
        assert len(client.get("/admin/erros").json()) == 1
        assert client.get("/admin/overview").json()["erros"] == 1

        resposta = client.post("/admin/erros/limpar")
        assert resposta.status_code == 200
        assert resposta.json()["grupos"] == ["planning_hub"]
        assert client.get("/admin/erros").json() == []
        assert client.get("/admin/overview").json()["erros"] == 0

        with SessionLocal() as db:
            assert db.query(Processo).filter(Processo.status == "erro").count() == 1  # historico preservado
            db.add(Processo(empresa_id=empresa_id, tipo="consulta_nfse", status="erro", erro_resumo="Novo erro",
                            created_at=datetime.now(timezone.utc) + timedelta(seconds=5),
                            updated_at=datetime.now(timezone.utc) + timedelta(seconds=5)))
            db.commit()
        assert [e["mensagem"] for e in client.get("/admin/erros").json()] == ["Novo erro"]



def test_limpar_do_admin_geral_inclui_empresa_de_grupo_sem_cadastro():
    from backend.app.core.config import settings

    _preparar()
    with SessionLocal() as db:
        # Grupo so no texto da empresa, sem linha em `grupos` (dados antigos/importados).
        orfa = Empresa(nome="Grupo sem cadastro", cnpj="55444333000122", ambiente="producao", ativo=True,
                       grupo="grupo_sem_cadastro")
        db.add(orfa)
        db.commit()
        processo = Processo(empresa_id=orfa.id, tipo="consulta_nfse", status="finalizado")
        db.add(processo)
        db.commit()
        db.add(LogProcesso(processo_id=processo.id, empresa_id=orfa.id, level="ERROR", mensagem="Falha sem empresa",
                           created_at=datetime.now(timezone.utc)))
        db.commit()
    original = settings.super_admin_emails
    object.__setattr__(settings, "super_admin_emails", "portal-test@example.com")
    try:
        with TestClient(app) as client:
            mensagens = [e["mensagem"] for e in client.get("/admin/erros").json()]
            assert "Falha sem empresa" in mensagens
            assert client.post("/admin/erros/limpar").status_code == 200
            assert client.get("/admin/erros").json() == []
    finally:
        object.__setattr__(settings, "super_admin_emails", original)

def test_volumetria_agrega_no_banco_e_respeita_o_grupo():
    _preparar()
    with TestClient(app) as client:
        resposta = client.get("/admin/volumetria", params={"dias": 30})
    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["totais"]["notas"] == 2  # V3 fora do periodo; X1 de outro grupo
    assert dados["totais"]["valor"] == 150
    assert len(dados["notas_por_dia"]) == 30
    assert dados["tipos"] == {"tomadas": 1, "prestadas": 1, "outras": 0}
    assert dados["status"]["cancelada"] == 1
    assert dados["top_empresas"][0]["empresa"] == "Empresa Vol"
    assert dados["por_grupo"] == []  # so o admin geral ve a comparacao entre grupos
    assert {"responsavel": "Ana", "notas": 1} in dados["pendentes_por_responsavel"]
    assert dados["totais"]["consultas"] == 2
    assert dados["totais"]["consultas_com_erro"] == 1
    assert 80 <= dados["totais"]["duracao_media_consulta_s"] <= 100
    assert sum(m["notas"] for m in dados["notas_por_mes"]) == 3
