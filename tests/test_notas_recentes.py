from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "sqlite:///./data/test_consultas_api.db"
os.environ["API_WORKER_ENABLED"] = "false"
os.environ["WORKER_DRY_RUN"] = "true"
os.environ["SECRETS_KEY"] = Fernet.generate_key().decode("utf-8")

from fastapi.testclient import TestClient

from backend.app.db.models import Arquivo, Empresa, Evento, Job, LogProcesso, Nota, NsuControle, Processo
from backend.app.db.session import SessionLocal, init_db
from backend.app.main import app
from backend.app.repositories import arquivos_repo, notas_repo
from backend.app.services import nsu_control_service


def _reset_db() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(LogProcesso).delete()
        db.query(Job).delete()
        db.query(Evento).delete()
        db.query(Arquivo).delete()
        db.query(Nota).delete()
        db.query(NsuControle).delete()
        db.query(Processo).delete()
        db.query(Empresa).delete()
        db.commit()


def _empresa() -> int:
    with SessionLocal() as db:
        empresa = Empresa(nome="Empresa Teste", cnpj="11222333000181", ambiente="producao", ativo=True)
        db.add(empresa)
        db.commit()
        db.refresh(empresa)
        return int(empresa.id)


def test_get_notas_retorna_importadas_recentemente_primeiro():
    _reset_db()
    empresa_id = _empresa()
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "ANTIGA_IMPORTACAO",
                "numero_nfse": "1",
                "data_emissao": date.today(),
                "competencia": date.today(),
                "importado_em": now - timedelta(days=4),
                "updated_at": now - timedelta(days=4),
                "created_at": now - timedelta(days=4),
            },
        )
        notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "NOVA_IMPORTACAO",
                "numero_nfse": "2",
                "data_emissao": date.today() - timedelta(days=30),
                "competencia": date.today() - timedelta(days=30),
                "importado_em": now,
                "updated_at": now,
                "created_at": now,
            },
        )
        db.commit()

    with TestClient(app) as client:
        response = client.get("/notas")
        assert response.status_code == 200
        payload = response.json()
        assert [item["chave"] for item in payload[:2]] == ["NOVA_IMPORTACAO", "ANTIGA_IMPORTACAO"]
        assert payload[0]["importado_em"] is not None


def test_get_notas_todas_retorna_lista_completa_filtrada():
    _reset_db()
    empresa_id = _empresa()
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        for index in range(505):
            notas_repo.create_nota(
                db,
                {
                    "empresa_id": empresa_id,
                    "chave": f"CHAVE_TOTAL_{index:03d}",
                    "numero_nfse": str(index),
                    "data_emissao": date.today(),
                    "competencia": date.today(),
                    "prestador_cnpj": "11111111000191",
                    "prestador_nome": "Prestador Total",
                    "tomador_cnpj": "22222222000182",
                    "tomador_nome": "Tomador Total",
                    "status_documento": "autorizada",
                    "importado_em": now - timedelta(minutes=index),
                    "updated_at": now - timedelta(minutes=index),
                    "created_at": now - timedelta(minutes=index),
                },
            )
        notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "CHAVE_TOTAL_CANCELADA",
                "numero_nfse": "999",
                "data_emissao": date.today(),
                "competencia": date.today(),
                "status_documento": "cancelada",
                "importado_em": now + timedelta(minutes=1),
                "updated_at": now + timedelta(minutes=1),
                "created_at": now + timedelta(minutes=1),
            },
        )
        db.commit()

    with TestClient(app) as client:
        response = client.get(
            "/notas/todas",
            params={"empresa_id": empresa_id, "status": "autorizada", "busca": "Prestador Total"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 505
        assert len(payload["items"]) == 505
        assert payload["items"][0]["chave"] == "CHAVE_TOTAL_000"
        assert payload["items"][-1]["chave"] == "CHAVE_TOTAL_504"
        assert {item["status_documento"] for item in payload["items"]} == {"autorizada"}


def test_upsert_nota_existente_atualiza_importado_em_e_updated_at():
    _reset_db()
    empresa_id = _empresa()
    old = datetime.now(timezone.utc) - timedelta(days=4)

    with SessionLocal() as db:
        nota, created = notas_repo.upsert_nota_by_chave(
            db,
            empresa_id,
            "CHAVE_UPSERT",
            {
                "empresa_id": empresa_id,
                "chave": "CHAVE_UPSERT",
                "numero_nfse": "10",
                "importado_em": old,
                "updated_at": old,
                "created_at": old,
            },
        )
        assert created is True
        original_importado = nota.importado_em
        db.commit()

        nota, created = notas_repo.upsert_nota_by_chave(
            db,
            empresa_id,
            "CHAVE_UPSERT",
            {
                "empresa_id": empresa_id,
                "chave": "CHAVE_UPSERT",
                "numero_nfse": "11",
            },
        )
        assert created is False
        assert nota.importado_em is not None
        assert nota.updated_at is not None
        assert nota.importado_em > original_importado
        db.commit()


def test_arquivo_existente_mantem_vinculo_com_nota_e_atualiza_timestamp():
    _reset_db()
    empresa_id = _empresa()

    with SessionLocal() as db:
        nota = notas_repo.create_nota(db, {"empresa_id": empresa_id, "chave": "CHAVE_ARQUIVO"})
        arquivo, created = arquivos_repo.create_arquivo_if_missing(
            db,
            {
                "empresa_id": empresa_id,
                "nota_id": nota.id,
                "processo_id": None,
                "tipo": "xml",
                "storage_backend": "local",
                "storage_bucket": "nfse",
                "storage_key": "xml/teste.xml",
                "content_type": "application/xml",
                "tamanho_bytes": 10,
                "checksum": "abc",
            },
        )
        assert created is True
        assert arquivo.nota_id == nota.id
        db.commit()

        updated_before = arquivo.updated_at
        arquivo, created = arquivos_repo.create_arquivo_if_missing(
            db,
            {
                "empresa_id": empresa_id,
                "nota_id": nota.id,
                "processo_id": None,
                "tipo": "xml",
                "storage_backend": "local",
                "storage_bucket": "nfse",
                "storage_key": "xml/teste.xml",
                "content_type": "application/xml",
                "tamanho_bytes": 10,
                "checksum": "abc",
            },
        )
        assert created is False
        assert arquivo.nota_id == nota.id
        assert arquivo.updated_at >= updated_before


def test_patch_conferencia_persiste_operador_e_filtra():
    _reset_db()
    empresa_id = _empresa()
    with SessionLocal() as db:
        nota = notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "CHAVE_CONF",
                "numero_nfse": "100",
                "prestador_cnpj": "00111222000133",
                "tomador_cnpj": "11222333000181",
            },
        )
        nota_id = int(nota.id)
        db.commit()

    with TestClient(app) as client:
        response = client.patch(
            f"/notas/{nota_id}/conferencia",
            json={
                "conferencia_status": "ok",
                "conferencia_observacao": "Validada",
                "operator_name": "Kaio",
                "operator_id": "op-1",
                "device_id": "dev-1",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["conferencia_status"] == "ok"
        assert payload["responsavel"] == "Kaio"
        assert payload["conferencia_atualizado_em"] is not None

        response = client.get("/notas", params={"conferencia_status": "ok"})
        assert response.status_code == 200
        assert [item["chave"] for item in response.json()] == ["CHAVE_CONF"]


def test_nsu_controle_nao_regride_e_considera_notas():
    _reset_db()
    empresa_id = _empresa()
    with SessionLocal() as db:
        nsu_control_service.atualizar_ultimo_nsu(
            db,
            empresa_id=empresa_id,
            certificado_id=1,
            cnpj="11222333000181",
            ultimo_nsu=200,
            origem="teste",
        )
        nsu_control_service.atualizar_ultimo_nsu(
            db,
            empresa_id=empresa_id,
            certificado_id=1,
            cnpj="11222333000181",
            ultimo_nsu=150,
            origem="teste",
        )
        notas_repo.create_nota(
            db,
            {"empresa_id": empresa_id, "chave": "CHAVE_NSU", "ultimo_nsu": 250},
        )
        db.commit()
        assert nsu_control_service.obter_ultimo_nsu(db, empresa_id, certificado_id=1) == 250


def test_notas_recebidas_usa_cnpj_empresa_e_competencia_operacional():
    _reset_db()
    empresa_id = _empresa()
    with SessionLocal() as db:
        notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "JUNHO",
                "numero_nfse": "1",
                "competencia": date(2026, 6, 15),
                "data_emissao": date(2026, 6, 15),
                "prestador_cnpj": "00111222000133",
                "tomador_cnpj": "11222333000181",
                "status_documento": "autorizada",
            },
        )
        notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "JULHO_OPERACIONAL",
                "numero_nfse": "2",
                "competencia": date(2026, 7, 1),
                "data_emissao": date(2026, 7, 1),
                "prestador_cnpj": "00444555000166",
                "tomador_cnpj": "11222333000181",
                "status_documento": "autorizada",
            },
        )
        notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "EMITIDA",
                "numero_nfse": "3",
                "competencia": date(2026, 6, 20),
                "prestador_cnpj": "11222333000181",
                "tomador_cnpj": "00444555000166",
                "status_documento": "autorizada",
            },
        )
        db.commit()

    with TestClient(app) as client:
        response = client.get(
            "/notas/recebidas",
            params={
                "empresa_id": empresa_id,
                "competencia_inicio": "2026-06-01",
                "competencia_fim": "2026-06-30",
                "somente_validas": "true",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert {item["chave"] for item in payload} == {"JUNHO", "JULHO_OPERACIONAL"}
        julho = next(item for item in payload if item["chave"] == "JULHO_OPERACIONAL")
        assert julho["nota_tipo"] == "recebida"
        assert julho["competencia_original"] == "2026-07-01"
        assert julho["competencia_operacional"] == "2026-06-01"
