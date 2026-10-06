"""Fase 5: nada de corte silencioso em 5.000 notas (painel, listas, ZIP, planilha)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.app.core.security import create_access_token, hash_password
from backend.app.db.models import (
    AcessoUsuario,
    Arquivo,
    Certificado,
    ConferenciaHistorico,
    ConviteCadastro,
    Empresa,
    Evento,
    Job,
    LockProcessamento,
    LogProcesso,
    Nota,
    NsuControle,
    Processo,
    RedefinicaoSenhaToken,
    Usuario,
    VerificacaoEmailToken,
)
from backend.app.db.session import SessionLocal, init_db
from backend.app.main import app
from backend.app.schemas.notas import NotasDownloadFiltros, NotasDownloadLoteRequest
from backend.app.services import notas_download_service, notas_service, portal_support_service
from backend.app.services.notas_download_service import NotasDownloadLoteError

MODELOS = (
    ConferenciaHistorico, VerificacaoEmailToken, RedefinicaoSenhaToken, ConviteCadastro, AcessoUsuario,
    Evento, Arquivo, Nota, LogProcesso, Job, LockProcessamento, NsuControle, Processo, Certificado, Usuario, Empresa,
)
CNPJ_EMPRESA = "22333444000155"
CNPJ_OUTRO = "55666777000188"
EMITIDAS = 5100
RECEBIDAS = 100
CANCELADAS = 3  # entre as emitidas


def _limpar():
    with SessionLocal() as db:
        for modelo in MODELOS:
            db.query(modelo).delete()
        db.commit()


@pytest.fixture(scope="module")
def acervo():
    init_db()
    _limpar()
    with SessionLocal() as db:
        empresa = Empresa(nome="Empresa Hub", cnpj=CNPJ_EMPRESA, ambiente="producao", ativo=True, grupo="planning_hub")
        db.add(empresa)
        db.flush()
        certificado = Certificado(empresa_id=empresa.id, nome="cert-renovado", storage_key="certificados/x.pfx")
        db.add(certificado)
        usuario = Usuario(
            empresa_id=empresa.id, email="op@example.com", senha_hash=hash_password("senha-forte-123"), nome="Op",
            ativo=True, grupo="planning_hub", papel="operador", is_admin=False, email_verificado=True, token_version=0,
        )
        db.add(usuario)
        db.flush()
        base = datetime(2026, 9, 1, tzinfo=timezone.utc)
        linhas = []
        for i in range(EMITIDAS + RECEBIDAS):
            emitida = i < EMITIDAS
            linhas.append({
                "empresa_id": empresa.id,
                "chave": f"{i:050d}",
                "numero_nfse": str(i + 1),
                # Sem processo: como as notas criadas pelo script de correcao.
                "processo_id": None,
                "prestador_cnpj": CNPJ_EMPRESA if emitida else CNPJ_OUTRO,
                "tomador_cnpj": CNPJ_OUTRO if emitida else CNPJ_EMPRESA,
                "status_documento": "cancelada" if i < CANCELADAS else "autorizada",
                "valor_servico": Decimal("1000.00") if i % 2 else Decimal("10.00"),
                "importado_em": base + timedelta(seconds=i),
                "arquivada": False,
            })
        db.bulk_insert_mappings(Nota, linhas)
        db.commit()
        dados = {"empresa_id": int(empresa.id), "certificado_id": int(certificado.id), "usuario_id": int(usuario.id)}
    yield dados
    _limpar()


def test_resumo_do_painel_conta_o_acervo_inteiro(acervo):
    with SessionLocal() as db:
        resumo = notas_service.resumo_notas_operacional(db, grupo="planning_hub")
    assert resumo["total"] == EMITIDAS + RECEBIDAS
    assert resumo["canceladas"] == CANCELADAS


def test_pagina_alem_de_5000_com_filtro_de_direcao_nao_vem_vazia(acervo):
    with SessionLocal() as db:
        pagina = notas_service.listar_notas(db, grupo="planning_hub", direcao_nota="emitida", limit=100, offset=5000)
    assert len(pagina) == EMITIDAS - 5000
    assert all(nota.direcao_nota == "emitida" for nota in pagina)


def test_zip_leva_todas_as_notas_exportaveis_e_ignora_canceladas(acervo):
    payload = NotasDownloadLoteRequest(filtros=NotasDownloadFiltros(empresa_id=acervo["empresa_id"]))
    with SessionLocal() as db:
        notas = notas_download_service._buscar_notas(db, payload, max_notas=10000, grupo="planning_hub")
    assert len(notas) == EMITIDAS + RECEBIDAS - CANCELADAS
    assert not any(nota.status_documento == "cancelada" for nota in notas)
    # Mesma ordem da tela: mais recente primeiro.
    assert notas[0].importado_em > notas[-1].importado_em


def test_zip_acima_do_limite_avisa_em_vez_de_cortar(acervo):
    payload = NotasDownloadLoteRequest(filtros=NotasDownloadFiltros(empresa_id=acervo["empresa_id"]))
    with SessionLocal() as db, pytest.raises(NotasDownloadLoteError, match="Limite de 5000 notas por ZIP"):
        notas_download_service._buscar_notas(db, payload, max_notas=5000, grupo="planning_hub")


def test_planilha_acima_do_limite_avisa_em_vez_de_cortar(acervo, monkeypatch):
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "relatorio_max_notas", 5000)
    with SessionLocal() as db, pytest.raises(portal_support_service.PortalSupportError, match="planilha excedido"):
        portal_support_service._buscar_notas_relatorio(db, NotasDownloadFiltros(), grupo="planning_hub")


def test_exportacao_aplica_os_filtros_da_tela(acervo):
    filtros = NotasDownloadFiltros(direcao_nota="recebida", valor_min=Decimal("500"))
    with SessionLocal() as db:
        notas = notas_service.buscar_notas_exportacao(db, filtros, "planning_hub", 10000)
    assert len(notas) == RECEBIDAS // 2
    assert all(nota.direcao_nota == "recebida" and nota.valor_servico >= 500 for nota in notas)


def test_filtro_por_certificado_acha_notas_sem_processo(acervo):
    with SessionLocal() as db:
        total = notas_service.listar_todas_notas(
            db, grupo="planning_hub", certificado_id=acervo["certificado_id"], somente_total=True
        )["total"]
        outro = notas_service.listar_todas_notas(db, grupo="planning_hub", certificado_id=999999, somente_total=True)["total"]
    assert total == EMITIDAS + RECEBIDAS
    assert outro == 0


def test_notas_todas_paginada_devolve_total_do_filtro(acervo):
    token = create_access_token(acervo["usuario_id"], acervo["empresa_id"], versao=0)
    with TestClient(app) as client:
        resposta = client.get(
            "/notas/todas", params={"limit": 50, "offset": 5100}, headers={"Authorization": f"Bearer {token}"}
        )
        com_calculado = client.get(
            "/notas/todas",
            params={"limit": 10, "offset": 0, "direcao_nota": "recebida"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["total"] == EMITIDAS + RECEBIDAS
    assert len(corpo["items"]) == 50
    assert com_calculado.json()["total"] == RECEBIDAS
    assert len(com_calculado.json()["items"]) == 10


def test_get_do_zip_aceita_os_mesmos_filtros_do_post(acervo, monkeypatch):
    recebido = {}

    def falso_gerar(db, storage, payload, grupo=None):
        recebido["filtros"] = payload.filtros
        raise NotasDownloadLoteError("Nenhuma nota encontrada para os filtros informados.")

    monkeypatch.setattr(notas_download_service, "gerar_zip_notas", falso_gerar)
    token = create_access_token(acervo["usuario_id"], acervo["empresa_id"], versao=0)
    with TestClient(app) as client:
        client.get(
            "/notas/download-lote",
            params={"somente_divergentes": "true", "valor_min": "500", "conferencia": "ok", "sla": "atrasado"},
            headers={"Authorization": f"Bearer {token}"},
        )
    filtros = recebido["filtros"]
    assert filtros.somente_divergentes is True
    assert filtros.valor_min == Decimal("500")
    assert filtros.conferencia_status == "ok"
    assert filtros.sla_status == "atrasado"
