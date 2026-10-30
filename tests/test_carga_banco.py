"""Regressoes de carga: DTO sem N+1 e indices correspondentes ao cursor."""
from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex

from backend.app.db.base import Base
from backend.app.db.models import Certificado, Empresa, Job, Nota
from backend.app.repositories.certificados_repo import list_certificados


def test_certificados_serializam_empresa_sem_select_adicional_e_sem_vazar_grupo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for i, grupo in enumerate(("planning_hub", "planning_hub", "planning_ma"), start=1):
            empresa = Empresa(nome=f"Empresa {i}", cnpj=str(i).zfill(14), grupo=grupo)
            db.add(empresa)
            db.flush()
            db.add(Certificado(empresa_id=empresa.id, nome=f"Cert {i}", storage_key=f"cert/{i}"))
        db.commit()
    consultas = []
    def contar(_conn, _cursor, statement, _params, _context, _many):
        consultas.append(statement)
    event.listen(engine, "before_cursor_execute", contar)
    with Session(engine) as db:
        certificados = list_certificados(db, grupo="planning_hub", ativo=True)
        assert [(c.empresa_nome, c.empresa_cnpj) for c in certificados] == [
            ("Empresa 1", "00000000000001"), ("Empresa 2", "00000000000002")
        ]
        assert len(consultas) == 1
    engine.dispose()


def test_indices_cursor_compilam_com_coalesce_e_fuso_explicito():
    indices = {idx.name: idx for idx in Nota.__table__.indexes}
    for nome in ("recentes", "emissao"):
        sql = str(CreateIndex(indices[f"ix_notas_cursor_{nome}"]).compile(dialect=postgresql.dialect()))
        assert "coalesce(importado_em, TIMESTAMPTZ '1900-01-01 00:00:00+00')" in sql
        assert "coalesce(updated_at, TIMESTAMPTZ '1900-01-01 00:00:00+00')" in sql
        if nome == "emissao":
            assert "coalesce(data_emissao, DATE '1900-01-01')" in sql
    assert "ix_processos_jobs_status_updated_at" in {idx.name for idx in Job.__table__.indexes}
    from sqlalchemy import select
    from backend.app.repositories.notas_repo import chaves_ordem
    compilado = select(Nota.id).order_by(*chaves_ordem("emissao")).compile(dialect=postgresql.dialect())
    assert not compilado.params  # a sentinela do COALESCE e literal, nao um bind


def test_migracao_indices_e_idempotente_no_sqlite(tmp_path):
    db_path = tmp_path / "migracao.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    # Conexao explicita impede env.py de usar o .env de producao.
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP INDEX ix_processos_jobs_status_updated_at")
        conn.exec_driver_sql("DROP INDEX ix_tentativas_acesso_chave_criado_em")
        config.attributes["connection"] = conn
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert "ix_processos_jobs_status_updated_at" in {
            idx["name"] for idx in inspect(conn).get_indexes("processos_jobs")
        }
    engine.dispose()


def test_ciclo_automatico_distribui_jobs_mas_manual_e_forcado_nao(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from backend.app.db.models import MonitoramentoConfig
    from backend.app.schemas.consultas import ConsultaIniciarRequest
    from backend.app.services import consultas_service

    agora = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(consultas_service, "_now", lambda: agora)
    for manual, forcar in ((False, False), (True, False), (False, True)):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            empresa = Empresa(nome="Empresa", cnpj="12345678000190", grupo="planning_hub")
            db.add(empresa)
            db.flush()
            certificados = [Certificado(empresa_id=empresa.id, nome=str(i), storage_key=str(i)) for i in range(3)]
            db.add_all(certificados)
            db.add(MonitoramentoConfig(grupo="planning_hub", automatico_ativo=True, intervalo_minutos=15))
            db.commit()
            monkeypatch.setattr(consultas_service, "list_certificados_elegiveis", lambda *a, **k: certificados)
            resultado = consultas_service.enqueue_consultas_pendentes(
                db, ConsultaIniciarRequest(forcar=forcar), respeitar_ciclo=not manual,
            )
            assert resultado["certificados_enfileirados"] == 3
            jobs = db.query(Job).order_by(Job.id).all()
            esperados = [0, 0, 0] if manual or forcar else [0, 300, 600]
            assert [j.available_at.replace(tzinfo=timezone.utc) for j in jobs] == [
                agora + timedelta(seconds=i) for i in esperados
            ]
        engine.dispose()


def test_limitador_conta_janela_sem_apagar_por_tentativa_e_mantem_reserva(monkeypatch):
    import hashlib
    import random
    from datetime import datetime, timedelta, timezone
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.pool import StaticPool
    from backend.app.core import rate_limit
    from backend.app.db.models import TentativaAcesso

    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(rate_limit, "_sessao_limitador", lambda: Session(engine))
    monkeypatch.setattr(random, "random", lambda: 1)
    with Session(engine) as db:
        db.add(TentativaAcesso(chave=hashlib.sha256(b"alvo").hexdigest(),
                              criado_em=datetime.now(timezone.utc)-timedelta(hours=1)))
        db.commit()
    consultas = []
    event.listen(engine, "before_cursor_execute", lambda _c, _cu, sql, *_: consultas.append(sql))
    limite = rate_limit.RateLimiterBanco(2, 60)
    assert limite.allow("alvo")
    assert limite.allow("alvo")
    assert not limite.allow("alvo")
    assert not any(sql.lstrip().upper().startswith("DELETE") for sql in consultas)
    # Outro processo continua vendo o limite persistido, mesmo com reserva nova.
    assert not rate_limit.RateLimiterBanco(2, 60).allow("alvo")
    def indisponivel():
        raise OperationalError("SELECT", {}, Exception("banco indisponivel"))
    monkeypatch.setattr(rate_limit, "_sessao_limitador", indisponivel)
    assert not limite.allow("alvo")  # a queda nao concede duas tentativas extras
    assert limite.allow("outro")
    engine.dispose()
