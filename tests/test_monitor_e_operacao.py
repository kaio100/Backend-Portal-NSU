"""Monitor automatico de consultas e vigia de empresas sem consulta.

Regressao do incidente de 01/10/2026: o monitor de producao tinha so
certificado_ids; o autocadastro de uma empresa nova criou empresa_ids=[nova] e,
como os filtros se combinam, so ela continuou sendo consultada. 78 de 84
empresas ficaram 5 dias sem consulta e nenhum alerta disparou.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.models import Certificado, Processo
from backend.app.db.session import SessionLocal, init_db
from backend.app.main import app
from backend.app.services import certificado_metadata_service, consultas_service, operacao_service
from backend.app.services.certificado_metadata_service import CertificadoMetadata

GRUPO = "planning_hub"


def _metadata(cnpj: str, thumbprint: str) -> CertificadoMetadata:
    return CertificadoMetadata(
        cnpj=cnpj,
        nome=f"Empresa {cnpj} LTDA",
        subject_cn=f"Empresa {cnpj} LTDA:{cnpj}",
        thumbprint=thumbprint,
        valido_de=None,
        valido_ate=None,
    )


def _autocadastrar(client: TestClient, monkeypatch, cnpj: str, thumbprint: str) -> dict:
    monkeypatch.setattr(
        certificado_metadata_service,
        "extrair_metadata_pfx",
        lambda pfx_bytes, senha: _metadata(cnpj, thumbprint),
    )
    resposta = client.post(
        "/certificados/autocadastrar",
        data={"senha": "senha-ok", "ambiente": "producao", "auto_iniciar": "true"},
        files={"arquivo": ("certificado.pfx", b"fake-pfx", "application/x-pkcs12")},
    )
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _definir_monitor(ativo: bool, filtros: dict | None) -> None:
    with SessionLocal() as db:
        config = consultas_service.get_monitoramento_config(db, GRUPO)
        config.automatico_ativo = ativo
        config.filtros_json = filtros
        db.commit()


def _ler_monitor() -> tuple[bool, dict | None]:
    with SessionLocal() as db:
        config = consultas_service.get_monitoramento_config(db, GRUPO)
        return bool(config.automatico_ativo), config.filtros_json


@pytest.fixture(autouse=True)
def _preserva_monitor(monkeypatch):
    # Com o monitor global ligado, o agendador embutido do TestClient
    # enfileiraria consultas para as empresas que os outros testes deixam no
    # banco compartilhado.
    monkeypatch.setattr(settings, "embedded_scheduler_enabled", False)
    init_db()
    ativo, filtros = _ler_monitor()
    yield
    _definir_monitor(ativo, filtros)


def test_autocadastro_nao_restringe_monitor_filtrado_so_por_certificado(monkeypatch):
    _definir_monitor(True, {"automatico": True, "empresa_ids": None, "certificado_ids": [999101]})

    with TestClient(app) as client:
        novo = _autocadastrar(client, monkeypatch, "41222333000101", "THUMB-MON-101")

    _, filtros = _ler_monitor()
    assert filtros["empresa_ids"] is None, "empresa_ids vazio significa todas as empresas e deve continuar assim"
    assert set(filtros["certificado_ids"]) == {999101, novo["certificado"]["id"]}


def test_autocadastro_mantem_monitor_global(monkeypatch):
    _definir_monitor(True, None)

    with TestClient(app) as client:
        _autocadastrar(client, monkeypatch, "41222333000102", "THUMB-MON-102")

    ativo, filtros = _ler_monitor()
    assert ativo is True
    assert filtros["empresa_ids"] is None
    assert filtros["certificado_ids"] is None


def test_autocadastro_com_monitor_parado_so_enfileira_o_certificado(monkeypatch):
    _definir_monitor(False, None)

    with TestClient(app) as client:
        novo = _autocadastrar(client, monkeypatch, "41222333000103", "THUMB-MON-103")

    ativo, filtros = _ler_monitor()
    assert ativo is False, "o autocadastro nao liga o monitor que alguem desligou"
    assert filtros is None
    assert novo["processo"] is not None
    assert novo["processo"]["certificado_id"] == novo["certificado"]["id"]


def test_status_informa_escopo_do_monitor(monkeypatch):
    with TestClient(app) as client:
        novo = _autocadastrar(client, monkeypatch, "41222333000104", "THUMB-MON-104")

        _definir_monitor(True, None)
        global_ = client.get("/consultas/status").json()["monitor"]
        assert global_["escopo"] == "global"
        assert global_["empresas_fora_do_monitor"] == 0
        assert global_["empresas_monitoradas"] >= 1

        _definir_monitor(True, {"automatico": True, "empresa_ids": [novo["empresa"]["id"]]})
        restrito = client.get("/consultas/status").json()["monitor"]

    assert restrito["escopo"] == "restrito"
    assert [empresa["id"] for empresa in restrito["empresas"]] == [novo["empresa"]["id"]]
    assert restrito["empresas_monitoradas"] == 1
    assert restrito["empresas_fora_do_monitor"] == global_["empresas_monitoradas"] - 1


def _envelhecer_certificado(certificado_id: int, horas: int, valido_ate: datetime | None = None) -> None:
    with SessionLocal() as db:
        certificado = db.get(Certificado, certificado_id)
        certificado.created_at = datetime.now(timezone.utc) - timedelta(hours=horas)
        certificado.valido_ate = valido_ate
        db.commit()


def _ids_sem_consulta(horas: int = 6) -> set[int]:
    with SessionLocal() as db:
        return {empresa["id"] for empresa in operacao_service.empresas_sem_consulta(db, horas)}


def test_vigia_aponta_empresa_sem_consulta_finalizada(monkeypatch):
    _definir_monitor(True, None)
    with TestClient(app) as client:
        novo = _autocadastrar(client, monkeypatch, "41222333000105", "THUMB-MON-105")
    empresa_id = novo["empresa"]["id"]
    certificado_id = novo["certificado"]["id"]

    # Recem-cadastrada ainda nao teve tempo de ser consultada.
    assert empresa_id not in _ids_sem_consulta()

    _envelhecer_certificado(certificado_id, horas=48)
    assert empresa_id in _ids_sem_consulta()

    with SessionLocal() as db:
        estado = operacao_service.estado_operacao(db)
    assert estado["empresas_sem_consulta"] >= 1
    assert "empresas_sem_consulta" in operacao_service.problemas(estado)

    # Uma consulta finalizada dentro da janela tira a empresa do aviso.
    with SessionLocal() as db:
        db.add(
            Processo(
                empresa_id=empresa_id,
                certificado_id=certificado_id,
                tipo="consulta_nfse",
                status="finalizado",
                finished_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        db.commit()
    assert empresa_id not in _ids_sem_consulta()


def test_vigia_ignora_certificado_vencido_e_monitor_desligado(monkeypatch):
    _definir_monitor(True, None)
    with TestClient(app) as client:
        novo = _autocadastrar(client, monkeypatch, "41222333000106", "THUMB-MON-106")
    empresa_id = novo["empresa"]["id"]

    _envelhecer_certificado(novo["certificado"]["id"], horas=48, valido_ate=datetime.now(timezone.utc) - timedelta(days=1))
    assert empresa_id not in _ids_sem_consulta(), "certificado vencido ja tem aviso proprio e sai da fila"

    _envelhecer_certificado(novo["certificado"]["id"], horas=48)
    _definir_monitor(False, None)
    assert _ids_sem_consulta() == set(), "com o monitor desligado ninguem espera consulta automatica"

    with SessionLocal() as db:
        assert operacao_service.empresas_sem_consulta(db, 0) == []
