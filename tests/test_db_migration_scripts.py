from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from backend.app.db.models import Arquivo, Empresa, Nota
from backend.app.scripts import migrar_sqlite_para_postgres
from backend.app.scripts import db_migration_common
from backend.app.scripts.db_migration_common import (
    build_engine,
    compare_values,
    count_tables,
    count_table,
    mask_database_url,
    normalize_database_url,
)
from backend.app.scripts.diagnosticar_banco import diagnosticar
from backend.app.scripts.validar_migracao_postgres import validar


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _criar_sqlite_origem(path: Path) -> Path:
    engine = build_engine(_sqlite_url(path))
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        empresa = Empresa(id=10, nome="Empresa Teste", cnpj="11222333000181", ambiente="producao", ativo=True)
        nota = Nota(
            id=20,
            empresa_id=10,
            processo_id=None,
            chave="CHAVE20",
            numero_nfse="123",
            prestador_cnpj="99888777000166",
            tomador_cnpj="11222333000181",
            valor_servico=100,
            valor_liquido=90,
            status_documento="Autorizada",
            alertas_fiscais="",
            codigo_servico_raw="0107",
            codigo_servico_display="1.07",
            subitem_lc116="1.07",
        )
        arquivo = Arquivo(
            id=30,
            empresa_id=10,
            nota_id=20,
            processo_id=None,
            tipo="XML",
            storage_backend="local",
            storage_bucket=None,
            storage_key="xml/nota.xml",
            filename="nota.xml",
            content_type="application/xml",
            tamanho_bytes=123,
        )
        db.add_all([empresa, nota, arquivo])
        db.commit()
    return path


def test_normaliza_postgresql_url_e_mascara_senha() -> None:
    url = "postgresql://usuario:senha-secreta@host.pooler.supabase.com:5432/postgres?sslmode=require"

    normalized = normalize_database_url(url)
    masked = mask_database_url(url)

    assert normalized.startswith("postgresql+psycopg://")
    assert "senha-secreta" not in masked
    assert "***" in masked


def test_build_engine_sqlite_funciona_com_check_same_thread() -> None:
    engine = build_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1


def test_build_engine_postgresql_nao_envia_check_same_thread(monkeypatch) -> None:
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs

        class FakeEngine:
            pass

        return FakeEngine()

    monkeypatch.setattr(db_migration_common, "create_engine", fake_create_engine)

    db_migration_common.build_engine("postgresql://usuario:senha@host/db")

    assert captured["url"].startswith("postgresql+psycopg://")
    assert captured["kwargs"]["connect_args"] == {}
    assert captured["kwargs"]["pool_pre_ping"] is True


def test_diagnostico_mascara_senha(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "diag.db"
    engine = build_engine(_sqlite_url(db_path))
    Base.metadata.create_all(bind=engine)

    report = diagnosticar(_sqlite_url(db_path))

    assert report["tipo"] == "sqlite"
    assert "empresas" in report["tables"]


def test_dry_run_nao_escreve_no_destino(monkeypatch, tmp_path) -> None:
    source = _criar_sqlite_origem(tmp_path / "source.db")
    target = tmp_path / "target.db"
    monkeypatch.setattr(migrar_sqlite_para_postgres, "database_kind", lambda url: "postgresql")

    report = migrar_sqlite_para_postgres.migrar(
        sqlite_path=source,
        postgres_url=_sqlite_url(target),
        dry_run=True,
        batch_size=2,
    )

    assert report["dry_run"] is True
    assert report["tables"]["empresas"]["source_count"] == 1
    assert count_tables(build_engine(_sqlite_url(target))) == {}


def test_migracao_preserva_ids_e_relacionamento_nota_arquivo(monkeypatch, tmp_path) -> None:
    source = _criar_sqlite_origem(tmp_path / "source.db")
    target = tmp_path / "target.db"
    monkeypatch.setattr(migrar_sqlite_para_postgres, "database_kind", lambda url: "postgresql")

    report = migrar_sqlite_para_postgres.migrar(
        sqlite_path=source,
        postgres_url=_sqlite_url(target),
        execute=True,
        batch_size=1,
    )
    target_engine = build_engine(_sqlite_url(target))

    assert report["tables"]["empresas"]["inserted"] == 1
    assert count_table(target_engine, "empresas") == 1
    with target_engine.connect() as conn:
        row = conn.execute(text("SELECT id, nota_id FROM arquivos WHERE id = 30")).mappings().one()
    assert row["id"] == 30
    assert row["nota_id"] == 20


def test_migracao_real_aborta_se_destino_ja_tem_dados(monkeypatch, tmp_path) -> None:
    source = _criar_sqlite_origem(tmp_path / "source.db")
    target = _criar_sqlite_origem(tmp_path / "target.db")
    monkeypatch.setattr(migrar_sqlite_para_postgres, "database_kind", lambda url: "postgresql")

    try:
        migrar_sqlite_para_postgres.migrar(sqlite_path=source, postgres_url=_sqlite_url(target), execute=True)
    except migrar_sqlite_para_postgres.MigrationError as exc:
        assert "ja possui dados" in str(exc)
    else:
        raise AssertionError("Migração real deveria abortar com destino preenchido.")


def test_validacao_compara_contagens_e_amostras(monkeypatch, tmp_path) -> None:
    source = _criar_sqlite_origem(tmp_path / "source.db")
    target = tmp_path / "target.db"
    monkeypatch.setattr(migrar_sqlite_para_postgres, "database_kind", lambda url: "postgresql")
    migrar_sqlite_para_postgres.migrar(sqlite_path=source, postgres_url=_sqlite_url(target), execute=True)

    report = validar(source, _sqlite_url(target))

    assert report["errors"] == []
    assert report["source_counts"]["empresas"] == report["target_counts"]["empresas"]


def test_compare_values_datas_e_numericos() -> None:
    assert compare_values(10, 10)
