"""Releitura desde o 1o dia do mes anterior: na volta de uma parada e a pedido.

A releitura profunda ja acontecia uma vez por noite. Uma empresa fora da fila
(monitor restrito de 01/10 a 06/10/2026) nao tinha nem essa releitura; ao voltar,
ela agora rele o mes anterior na hora, sem esperar a noite.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.models import Empresa, Job, Processo
from backend.app.db.session import SessionLocal, init_db
from backend.app.main import app
from backend.app.repositories import notas_repo
from backend.app.services import certificado_metadata_service, consultas_service, nsu_control_service
from backend.app.services.certificado_metadata_service import CertificadoMetadata

SP = ZoneInfo("America/Sao_Paulo")
MEIO_DIA = datetime(2026, 10, 6, 12, tzinfo=SP)  # fora da janela noturna (19h-05h)


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    monkeypatch.setattr(settings, "embedded_scheduler_enabled", False)
    monkeypatch.setattr(settings, "nsu_releitura_apos_horas_sem_consulta", 6)
    init_db()


def _empresa(cnpj: str, grupo: str = "planning_hub") -> int:
    with SessionLocal() as db:
        empresa = Empresa(nome=f"Releitura {cnpj}", cnpj=cnpj, ambiente="producao", ativo=True, grupo=grupo)
        db.add(empresa)
        db.flush()
        nsu_control_service.atualizar_ultimo_nsu(db, empresa.id, 1, cnpj, 10000, origem="teste")
        # Nota de agosto: o mes anterior (setembro) comeca depois do NSU 3000.
        notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa.id,
                "chave": f"AGOSTO-{cnpj}",
                "data_emissao": date(2026, 8, 31),
                "competencia": date(2026, 8, 1),
                "primeiro_nsu": 2999,
                "ultimo_nsu": 3000,
            },
        )
        db.commit()
        return int(empresa.id)


def _consulta_finalizada(empresa_id: int, quando: datetime) -> None:
    with SessionLocal() as db:
        db.add(Processo(empresa_id=empresa_id, tipo="consulta_nfse", status="finalizado", finished_at=quando))
        db.commit()


def _plano(empresa_id: int, **kwargs) -> dict:
    with SessionLocal() as db:
        return nsu_control_service.planejar_inicio_consulta(db, empresa_id, 1, now=MEIO_DIA, **kwargs)


def test_volta_de_parada_rele_desde_o_mes_anterior_fora_da_janela():
    empresa_id = _empresa("51000000000101")
    _consulta_finalizada(empresa_id, MEIO_DIA - timedelta(days=5))

    plano = _plano(empresa_id)

    assert plano["reconciliacao_profunda"] is True
    assert plano["motivo_releitura"] == "apos_parada"
    assert plano["nsu_mes_anterior"] == 3000
    assert plano["nsu_inicio"] == 2000  # 3000 menos a margem de 1000


def test_consulta_recente_segue_o_recuo_normal():
    empresa_id = _empresa("51000000000102")
    _consulta_finalizada(empresa_id, MEIO_DIA - timedelta(hours=1))

    plano = _plano(empresa_id)

    assert plano["reconciliacao_profunda"] is False
    assert plano["motivo_releitura"] is None
    assert plano["nsu_inicio"] == 9950


def test_empresa_nunca_consultada_nao_e_parada():
    empresa_id = _empresa("51000000000103")
    assert _plano(empresa_id)["reconciliacao_profunda"] is False


def test_pedido_do_operador_forca_a_releitura():
    empresa_id = _empresa("51000000000104")
    _consulta_finalizada(empresa_id, MEIO_DIA - timedelta(hours=1))

    plano = _plano(empresa_id, forcar_releitura=True)

    assert plano["reconciliacao_profunda"] is True
    assert plano["motivo_releitura"] == "pedido_operador"
    assert plano["nsu_inicio"] == 2000


def test_configuracao_zero_desliga_a_releitura_apos_parada(monkeypatch):
    monkeypatch.setattr(settings, "nsu_releitura_apos_horas_sem_consulta", 0)
    empresa_id = _empresa("51000000000105")
    _consulta_finalizada(empresa_id, MEIO_DIA - timedelta(days=5))
    assert _plano(empresa_id)["reconciliacao_profunda"] is False


def _metadata(cnpj: str, thumbprint: str) -> CertificadoMetadata:
    return CertificadoMetadata(
        cnpj=cnpj, nome=f"Empresa {cnpj} LTDA", subject_cn=f"Empresa {cnpj} LTDA:{cnpj}",
        thumbprint=thumbprint, valido_de=None, valido_ate=None,
    )


def test_rota_enfileira_releitura_so_das_empresas_pedidas_sem_mexer_no_monitor(monkeypatch):
    monkeypatch.setattr(
        certificado_metadata_service, "extrair_metadata_pfx",
        lambda pfx_bytes, senha: _metadata("51000000000106", "THUMB-RELEITURA-106"),
    )
    with TestClient(app) as client:
        cadastro = client.post(
            "/certificados/autocadastrar",
            data={"senha": "senha-ok", "ambiente": "producao", "auto_iniciar": "false"},
            files={"arquivo": ("certificado.pfx", b"fake-pfx", "application/x-pkcs12")},
        ).json()
        empresa_id = cadastro["empresa"]["id"]
        with SessionLocal() as db:
            filtros_antes = consultas_service.get_monitoramento_config(db, "planning_hub").filtros_json

        resposta = client.post("/consultas/releitura-mes-anterior", json={"empresa_ids": [empresa_id]})
        assert resposta.status_code == 200, resposta.text
        assert resposta.json() == {"processos_criados": 1, "certificados_ignorados": 0}

        # Com a consulta ja na fila, um segundo pedido nao duplica.
        repetido = client.post("/consultas/releitura-mes-anterior", json={"empresa_ids": [empresa_id]}).json()
        assert repetido == {"processos_criados": 0, "certificados_ignorados": 1}

        # Lista vazia nao pode virar "todas as empresas".
        assert client.post("/consultas/releitura-mes-anterior", json={"empresa_ids": []}).status_code == 422

    with SessionLocal() as db:
        job = db.query(Job).filter(Job.empresa_id == empresa_id).order_by(Job.id.desc()).first()
        assert job.payload_json["releitura_mes_anterior"] is True
        assert consultas_service.get_monitoramento_config(db, "planning_hub").filtros_json == filtros_antes


def test_rota_ignora_empresa_de_outro_grupo():
    empresa_id = _empresa("51000000000107", grupo="outro_grupo")
    with TestClient(app) as client:
        resposta = client.post("/consultas/releitura-mes-anterior", json={"empresa_ids": [empresa_id]})
    assert resposta.status_code == 200
    assert resposta.json()["processos_criados"] == 0
