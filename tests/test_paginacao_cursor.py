"""Paginacao por cursor em /notas (X-Next-Cursor): continua de onde a pagina
anterior parou, na mesma ordem do OFFSET, sem repetir nem pular notas."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.db.models import (
    Arquivo,
    Empresa,
    Evento,
    Job,
    LogProcesso,
    Nota,
    NsuControle,
    Processo,
)
from backend.app.db.session import SessionLocal, init_db
from backend.app.main import app
from backend.app.repositories import notas_repo
from backend.app.services import notas_service


def _preparar(qtd: int = 11) -> int:
    init_db()
    agora = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for modelo in (LogProcesso, Job, Evento, Arquivo, Nota, NsuControle, Processo, Empresa):
            db.query(modelo).delete()
        empresa = Empresa(nome="Empresa Cursor", cnpj="11222333000181", ambiente="producao", ativo=True, grupo="planning_hub")
        db.add(empresa)
        db.commit()
        for i in range(qtd):
            notas_repo.create_nota(
                db,
                {
                    "empresa_id": empresa.id,
                    "chave": f"CURSOR{i:03d}",
                    "numero_nfse": str(i),
                    # Algumas sem data, outras empatadas: os casos que quebram paginacao ingenua.
                    "data_emissao": None if i % 4 == 0 else date(2026, 10, 1) + timedelta(days=i % 3),
                    "importado_em": None if i % 5 == 0 else agora - timedelta(minutes=i // 2),
                    "prestador_cnpj": "99888777000166",
                    "tomador_cnpj": "11222333000181",
                },
            )
        db.commit()
        return int(empresa.id)


def _paginar(client: TestClient, sort: str, limit: int) -> list[str]:
    chaves: list[str] = []
    cursor = None
    for _ in range(20):
        params = {"sort": sort, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        resposta = client.get("/notas", params=params)
        assert resposta.status_code == 200
        chaves += [n["chave"] for n in resposta.json()]
        cursor = resposta.headers.get("X-Next-Cursor")
        if not cursor:
            break
    return chaves


def test_cursor_percorre_tudo_na_mesma_ordem_do_offset():
    _preparar()
    with TestClient(app) as client:
        for sort in ("recentes", "emissao"):
            de_uma_vez = [n["chave"] for n in client.get("/notas", params={"sort": sort, "limit": 500}).json()]
            por_cursor = _paginar(client, sort, limit=3)
            assert len(de_uma_vez) == 11
            assert por_cursor == de_uma_vez, sort


def test_ultima_pagina_nao_devolve_cursor_e_cursor_invalido_da_422():
    _preparar(qtd=4)
    with TestClient(app) as client:
        unica = client.get("/notas", params={"limit": 10})
        assert "X-Next-Cursor" not in unica.headers
        assert client.get("/notas", params={"cursor": "lixo"}).status_code == 422
        # Cursor de uma ordem nao vale em outra.
        cheia = client.get("/notas", params={"limit": 2, "sort": "recentes"})
        assert client.get("/notas", params={"cursor": cheia.headers["X-Next-Cursor"], "sort": "emissao"}).status_code == 422


def test_percorrer_repo_le_tudo_sem_offset():
    empresa_id = _preparar()
    with SessionLocal() as db:
        lotes = list(notas_service._percorrer_repo(db, sort="emissao", lote=4, empresa_id=empresa_id))
    assert [len(lote) for lote in lotes] == [4, 4, 3]
    chaves = [n.chave for lote in lotes for n in lote]
    assert len(set(chaves)) == 11
