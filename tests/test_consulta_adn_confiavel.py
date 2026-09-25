"""Fase 3: consulta ao ADN sem perder documentos e sem travar a fila."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import adn_nfse_downloader as motor
from backend.app.core.config import Settings
from backend.app.db.models import (
    Certificado,
    Empresa,
    Job,
    LockProcessamento,
    LogProcesso,
    MonitoramentoConfig,
    Nota,
    NsuControle,
    Processo,
    Secret,
)
from backend.app.db.session import SessionLocal, init_db
from backend.app.repositories import jobs_repo, locks_repo
from backend.app.schemas.consultas import ConsultaIniciarRequest
from backend.app.services import consultas_service, legacy_processing_service, secrets_service

MODELOS = (LogProcesso, Job, LockProcessamento, NsuControle, Nota, Processo, Secret, Certificado, MonitoramentoConfig, Empresa)


@pytest.fixture(autouse=True)
def _banco_limpo():
    init_db()

    def limpar():
        with SessionLocal() as db:
            for modelo in MODELOS:
                db.query(modelo).delete()
            db.commit()

    limpar()
    yield
    limpar()


def _certificado(db, empresa: Empresa, validade: datetime | None) -> Certificado:
    certificado = Certificado(
        empresa_id=empresa.id, nome=f"Cert {validade}", storage_key="certificados/x.pfx", ativo=True, valido_ate=validade
    )
    db.add(certificado)
    db.flush()
    ref = secrets_service.build_certificado_senha_ref(certificado.id)
    secrets_service.save_secret(db, ref, "pfx_password", "senha")
    certificado.senha_secret_ref = ref
    db.flush()
    return certificado


def _empresa(db, cnpj="22333444000155") -> Empresa:
    empresa = Empresa(nome="Consulta LTDA", cnpj=cnpj, ambiente="producao", ativo=True, grupo="planning_hub")
    db.add(empresa)
    db.flush()
    return empresa


def test_certificado_vencido_fica_fora_da_fila():
    agora = datetime.now(timezone.utc)
    with SessionLocal() as db:
        empresa = _empresa(db)
        valido = _certificado(db, empresa, agora + timedelta(days=90))
        _certificado(db, empresa, agora - timedelta(days=1))
        sem_data = _certificado(db, empresa, None)
        db.commit()
        elegiveis = {c.id for c in consultas_service.list_certificados_elegiveis(db, grupo="planning_hub")}
    assert elegiveis == {valido.id, sem_data.id}


def test_erro_permanente_do_certificado_nao_e_repetido(monkeypatch):
    chamadas = {"n": 0}

    def certificado_vencido(*args, **kwargs):
        chamadas["n"] += 1
        raise ValueError("Client certificate expired: Not After: 2026-09-16 18:37:00Z")

    monkeypatch.setattr(motor, "mtls_get", certificado_vencido)
    monkeypatch.setattr(motor.time, "sleep", lambda s: pytest.fail("nao pode esperar para repetir"))
    with pytest.raises(ValueError):
        motor.requisicao_json_com_retry(SimpleNamespace(), "https://adn.example/dfe")
    assert chamadas["n"] == 1


def test_lock_ocupado_nao_e_tomado_e_lock_vencido_e():
    with SessionLocal() as db:
        empresa = _empresa(db)
        certificado = _certificado(db, empresa, None)
        db.commit()
        assert locks_repo.acquire_lock(db, empresa.id, certificado.id, "worker-a")
        db.commit()
        assert not locks_repo.acquire_lock(db, empresa.id, certificado.id, "worker-b")

        lock = locks_repo.get_lock(db, empresa.id, certificado.id)
        lock.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        assert locks_repo.acquire_lock(db, empresa.id, certificado.id, "worker-b")
        db.commit()
        assert locks_repo.get_lock(db, empresa.id, certificado.id).locked_by == "worker-b"


def test_job_sem_heartbeat_volta_para_a_fila_de_qualquer_worker():
    antigo = datetime.now(timezone.utc) - timedelta(minutes=30)
    with SessionLocal() as db:
        empresa = _empresa(db)
        certificado = _certificado(db, empresa, None)
        processos = []
        for worker, quando in (("worker-separado-1", antigo), ("api-planning_hub-1-x", datetime.now(timezone.utc))):
            processo = Processo(empresa_id=empresa.id, certificado_id=certificado.id, tipo="consulta_nfse", status="rodando")
            db.add(processo)
            db.flush()
            db.add(Job(processo_id=processo.id, empresa_id=empresa.id, certificado_id=certificado.id, tipo="consulta_nfse",
                       status="rodando", attempts=0, locked_by=worker, updated_at=quando))
            processos.append(processo.id)
        db.add(LockProcessamento(empresa_id=empresa.id, certificado_id=certificado.id, locked_by="worker-separado-1",
                                 locked_at=antigo, expires_at=antigo + timedelta(hours=1)))
        db.commit()

        assert jobs_repo.recuperar_jobs_travados(db, minutos=15) == 1
        status = {j.locked_by or "livre": j.status for j in db.query(Job).all()}
        assert status == {"livre": "pendente", "api-planning_hub-1-x": "rodando"}
        assert db.get(Processo, processos[0]).status == "pendente"
        assert db.query(LockProcessamento).count() == 0


def test_consulta_avulsa_nao_mexe_no_monitor_do_grupo():
    with SessionLocal() as db:
        empresa = _empresa(db)
        outra = _empresa(db, cnpj="11222333000181")
        certificado = _certificado(db, empresa, None)
        _certificado(db, outra, None)
        proximo = datetime.now(timezone.utc) + timedelta(minutes=10)
        db.add(MonitoramentoConfig(grupo="planning_hub", automatico_ativo=True, intervalo_minutos=15,
                                   filtros_json=None, proximo_ciclo_em=proximo))
        db.commit()

        certificado_id = certificado.id
        resultado = consultas_service.iniciar_consultas_automaticas(
            db, options=ConsultaIniciarRequest(automatico=False, empresa_ids=[empresa.id]), grupo="planning_hub"
        )
        enfileirados = [p.certificado_id for p in resultado["processos_criados"]]
        config = consultas_service.get_monitoramento_config(db, "planning_hub")
        estado = (config.automatico_ativo, config.filtros_json, config.intervalo_minutos)

    assert resultado["certificados_enfileirados"] == 1
    assert enfileirados == [certificado_id]
    assert estado == (True, None, 15)


def test_nsu_central_nao_avanca_durante_o_download(monkeypatch):
    gravacoes: list[tuple] = []
    monkeypatch.setattr(legacy_processing_service, "_gravar_nsu_em_sessao_curta", lambda *a: gravacoes.append(a))
    respostas = iter([{"LoteDFe": [{"NSU": "11"}, {"NSU": "12"}]}, {"StatusProcessamento": "NENHUM_DOCUMENTO_LOCALIZADO"}])
    legado = SimpleNamespace(
        carregar_estado=lambda cnpj: {"ultimo_nsu": 10},
        salvar_estado=lambda cnpj, nsu: None,
        consultar_dfe=lambda config, nsu, lote: next(respostas),
        salvar_json=lambda path, data: None,
        processar_documento=lambda doc: (int(doc["NSU"]), True),
        DIR_RAW=Path("."),
        ROOT_OUT=Path("."),
    )
    resultado = legacy_processing_service._executar_baixa_empresa_compat(
        legado, SimpleNamespace(cnpj="22333444000155"), limite=10, pausa=0, inicio=10,
        consulta_lote_tamanho=10, empresa_id=1, certificado_id=1, processo_id=None,
    )
    assert resultado["ultimo_nsu"] == 12
    assert gravacoes == []


def test_documento_com_erro_de_ingestao_segura_o_nsu_central():
    ingestao = {"erros": 2, "erros_detalhes": [
        {"etapa": "ingestao", "nsu": "15"}, {"etapa": "ingestao", "nsu": "18"}, {"etapa": "pdf_espelho", "nsu": "12"}]}
    nsu, aviso = legacy_processing_service._limitar_nsu_por_falhas(20, ingestao)
    assert nsu == 14
    assert "2 documento(s)" in aviso
    assert legacy_processing_service._limitar_nsu_por_falhas(20, {"erros": 0}) == (20, None)


def test_limpeza_apaga_respostas_brutas_antigas_e_mantem_xml(tmp_path):
    antigo = time.time() - 40 * 86400
    for pasta in ("raw", "json", "xml"):
        (tmp_path / pasta).mkdir()
        for nome, quando in (("velho", antigo), ("novo", time.time())):
            arquivo = tmp_path / pasta / f"{nome}.json"
            arquivo.write_text("{}")
            os.utime(arquivo, (quando, quando))

    assert legacy_processing_service._limpar_respostas_antigas(tmp_path) == 2
    assert sorted(p.name for p in (tmp_path / "raw").iterdir()) == ["novo.json"]
    assert sorted(p.name for p in (tmp_path / "xml").iterdir()) == ["novo.json", "velho.json"]


def test_data_de_corte_invalida_falha_no_startup():
    with pytest.raises(Exception):
        Settings(notas_data_corte="2026-13-40")
