from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import settings


def _connect_args() -> dict:
    if settings.database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _ensure_sqlite_parent() -> None:
    if not settings.database_url.startswith("sqlite:///"):
        return
    db_path = settings.database_url.removeprefix("sqlite:///")
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent()

_is_sqlite = settings.database_url.startswith("sqlite")

_engine_options = {
    "connect_args": _connect_args(),
    # SQLite local nao perde conexoes de rede. O pre-ping apenas acrescenta
    # um SELECT a cada checkout da sessao, que pesa bastante no polling.
    "pool_pre_ping": not _is_sqlite,
}
if not _is_sqlite:
    # Mantem conexoes suficientes para o portal e o worker coexistirem sem
    # abrir uma conexao nova a cada polling. O recycle evita conexoes mortas
    # em poolers como Supabase/Railway.
    _engine_options.update({
        "pool_size": max(1, int(settings.database_pool_size)),
        "max_overflow": max(0, int(settings.database_max_overflow)),
        "pool_timeout": max(1, int(settings.database_pool_timeout)),
        "pool_recycle": max(30, int(settings.database_pool_recycle)),
    })

engine = create_engine(settings.database_url, **_engine_options)


if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA temp_store=MEMORY")
        finally:
            cursor.close()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Inicializa somente o banco SQLite usado localmente e nos testes.

    Em PostgreSQL o esquema deve ser aplicado explicitamente por migrate_db().
    Isso impede que cada processo web/worker dispute locks de DDL no startup.
    """
    from backend.app.db import models  # noqa: F401

    if _is_sqlite:
        migrate_db()


def migrate_db() -> None:
    """Cria e atualiza o esquema em uma etapa administrativa explícita."""
    from backend.app.db import models  # noqa: F401
    from backend.app.db.base import Base

    Base.metadata.create_all(bind=engine)
    _ensure_runtime_columns()


def _ensure_runtime_columns() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    statements: list[str] = []
    is_sqlite = settings.database_url.startswith("sqlite")

    if "grupos" in table_names:
        statements.extend([
            "INSERT INTO grupos (codigo, nome, ativo) SELECT 'planning_hub', 'Planning/Hub', TRUE WHERE NOT EXISTS (SELECT 1 FROM grupos WHERE codigo = 'planning_hub')",
            "INSERT INTO grupos (codigo, nome, ativo) SELECT 'planning_ma', 'Planning/MA', TRUE WHERE NOT EXISTS (SELECT 1 FROM grupos WHERE codigo = 'planning_ma')",
        ])

    if "notas" in table_names:
        nota_columns = {column["name"] for column in inspector.get_columns("notas")}
        if "importado_em" not in nota_columns:
            column_type = "DATETIME" if is_sqlite else "TIMESTAMP WITH TIME ZONE"
            statements.append(f"ALTER TABLE notas ADD COLUMN importado_em {column_type}")
        nota_runtime_columns = {
            "prioridade": "VARCHAR(40)",
            "responsavel": "VARCHAR(120)",
            "conferencia_status": "VARCHAR(40)",
            "conferencia_observacao": "TEXT",
            "conferencia_atualizado_em": "DATETIME" if is_sqlite else "TIMESTAMP WITH TIME ZONE",
            "conferencia_por": "VARCHAR(120)",
            "operator_name": "VARCHAR(120)",
            "operator_id": "VARCHAR(80)",
            "device_id": "VARCHAR(80)",
            "status_nota_pdf": "VARCHAR(80)",
            "simples_xml": "VARCHAR(80)",
            "simples_nacional_xml": "VARCHAR(80)",
            "consulta_simples_api": "VARCHAR(80)",
            "status_simples_nacional": "VARCHAR(80)",
            "incidencia_iss": "VARCHAR(120)",
            "divergencia": "VARCHAR(120)",
            "status_fila_manual": "VARCHAR(40)",
            "prioridade_manual": "VARCHAR(40)",
            "alertas_fiscais": "TEXT",
            "valor_base": "NUMERIC(15, 2)",
            "iss": "NUMERIC(15, 2)",
            "irrf": "NUMERIC(15, 2)",
            "inss": "NUMERIC(15, 2)",
            "csrf": "NUMERIC(15, 2)",
            "valor_liquido_correto": "NUMERIC(15, 2)",
            "status_valor_liquido": "VARCHAR(80)",
            "status_csrf": "VARCHAR(80)",
            "status_irrf": "VARCHAR(80)",
            "status_inss": "VARCHAR(80)",
            "status_base_calculo": "VARCHAR(80)",
            "irrf_calculado": "NUMERIC(15, 2)",
            "inss_calculado": "NUMERIC(15, 2)",
            "pis_calculado": "NUMERIC(15, 2)",
            "cofins_calculado": "NUMERIC(15, 2)",
            "csll_calculado": "NUMERIC(15, 2)",
            "csrf_calculado": "NUMERIC(15, 2)",
            "iss_calculado": "NUMERIC(15, 2)",
            "status_iss": "VARCHAR(80)",
            "municipio": "VARCHAR(120)",
            "codigo_servico": "VARCHAR(80)",
            "codigo_servico_raw": "VARCHAR(80)",
            "codigo_servico_display": "VARCHAR(20)",
            "subitem_lc116": "VARCHAR(20)",
            "codigo_servico_nacional": "VARCHAR(80)",
            "descricao_servico_nacional": "TEXT",
            "descricao_servico_detalhada": "TEXT",
            "origem_base_calculo": "VARCHAR(40)",
            "aliquota_iss": "NUMERIC(8, 4)",
            "iss_retido": "BOOLEAN",
            "valor_iss_retido": "NUMERIC(15, 2)",
            "valor_pis": "NUMERIC(15, 2)",
            "valor_cofins": "NUMERIC(15, 2)",
            "valor_csll": "NUMERIC(15, 2)",
            "valor_csrf": "NUMERIC(15, 2)",
            "valor_outras_retencoes": "NUMERIC(15, 2)",
            "valor_deducoes": "NUMERIC(15, 2)",
            "valor_desconto_incondicionado": "NUMERIC(15, 2)",
            "valor_desconto_condicionado": "NUMERIC(15, 2)",
            "valor_liquido_calculado": "NUMERIC(15, 2)",
            "regra_irrf": "VARCHAR(20)",
            "regra_irrf_aliquota": "NUMERIC(8, 4)",
            "regra_pcc": "VARCHAR(20)",
            "regra_inss": "VARCHAR(20)",
            "regra_observacao": "TEXT",
            "cnae": "VARCHAR(30)",
            "sla": "VARCHAR(80)",
            "sla_status": "VARCHAR(80)",
            "entrada": "DATETIME" if is_sqlite else "TIMESTAMP WITH TIME ZONE",
            "arquivada": "BOOLEAN NOT NULL DEFAULT FALSE",
            "arquivada_em": "DATETIME" if is_sqlite else "TIMESTAMP WITH TIME ZONE",
            "arquivo_backup_storage_key": "VARCHAR(512)",
        }
        for name, column_type in nota_runtime_columns.items():
            if name not in nota_columns:
                statements.append(f"ALTER TABLE notas ADD COLUMN {name} {column_type}")
        statements.append("UPDATE notas SET importado_em = COALESCE(updated_at, created_at) WHERE importado_em IS NULL")
        # Indices compostos acompanham exatamente os filtros e ordenacoes das
        # telas de notas emitidas/recebidas. IF NOT EXISTS torna a migracao
        # barata nas inicializacoes seguintes.
        statements.extend([
            "CREATE INDEX IF NOT EXISTS ix_notas_empresa_importado_id ON notas (empresa_id, importado_em DESC, id DESC)",
            "CREATE INDEX IF NOT EXISTS ix_notas_empresa_emissao_id ON notas (empresa_id, data_emissao DESC, id DESC)",
            "CREATE INDEX IF NOT EXISTS ix_notas_empresa_prestador_emissao ON notas (empresa_id, prestador_cnpj, data_emissao DESC)",
            "CREATE INDEX IF NOT EXISTS ix_notas_empresa_tomador_emissao ON notas (empresa_id, tomador_cnpj, data_emissao DESC)",
            "CREATE INDEX IF NOT EXISTS ix_notas_arquivada_empresa_emissao ON notas (arquivada, empresa_id, data_emissao DESC, id DESC)",
        ])

    for table_name in ("empresas", "usuarios"):
        if table_name in table_names:
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            if "grupo" not in columns:
                statements.append(f"ALTER TABLE {table_name} ADD COLUMN grupo VARCHAR(40)")
            statements.append(f"UPDATE {table_name} SET grupo = 'planning_hub' WHERE grupo IS NULL OR TRIM(grupo) = ''")
            if table_name == "usuarios" and "is_admin" not in columns:
                statements.append("ALTER TABLE usuarios ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE")
            if table_name == "usuarios" and "papel" not in columns:
                statements.append("ALTER TABLE usuarios ADD COLUMN papel VARCHAR(20) NOT NULL DEFAULT 'operador'")
            if table_name == "usuarios":
                statements.append("UPDATE usuarios SET papel = 'admin' WHERE is_admin = TRUE AND papel <> 'admin'")
                statements.append("UPDATE usuarios SET papel = 'operador' WHERE papel IS NULL OR papel NOT IN ('admin', 'operador', 'leitura')")

    if "monitoramento_config" in table_names:
        columns = {column["name"] for column in inspector.get_columns("monitoramento_config")}
        if "grupo" not in columns:
            statements.append("ALTER TABLE monitoramento_config ADD COLUMN grupo VARCHAR(40)")
        statements.append("UPDATE monitoramento_config SET grupo = 'planning_hub' WHERE grupo IS NULL OR TRIM(grupo) = ''")

    if "arquivos" in table_names:
        arquivo_columns = {column["name"] for column in inspector.get_columns("arquivos")}
        if "updated_at" not in arquivo_columns:
            column_type = "DATETIME" if is_sqlite else "TIMESTAMP WITH TIME ZONE"
            statements.append(f"ALTER TABLE arquivos ADD COLUMN updated_at {column_type}")
        if "filename" not in arquivo_columns:
            statements.append("ALTER TABLE arquivos ADD COLUMN filename VARCHAR(255)")
        statements.append("UPDATE arquivos SET updated_at = created_at WHERE updated_at IS NULL")
        statements.extend([
            "CREATE INDEX IF NOT EXISTS ix_arquivos_nota_tipo_id ON arquivos (nota_id, tipo, id)",
            "CREATE INDEX IF NOT EXISTS ix_arquivos_empresa_tipo_id ON arquivos (empresa_id, tipo, id DESC)",
        ])

    if "cnpj_cache" in table_names:
        cache_columns = {column["name"] for column in inspector.get_columns("cnpj_cache")}
        cache_runtime_columns = {
            "consulta_simples_api": "VARCHAR(80)",
            "status_consulta": "VARCHAR(80)",
            "json_resposta": "JSON" if is_sqlite else "JSONB",
            "erro": "TEXT",
            "created_at": "DATETIME" if is_sqlite else "TIMESTAMP WITH TIME ZONE",
        }
        for name, column_type in cache_runtime_columns.items():
            if name not in cache_columns:
                statements.append(f"ALTER TABLE cnpj_cache ADD COLUMN {name} {column_type}")
        statements.append("UPDATE cnpj_cache SET consulta_simples_api = simples_status WHERE consulta_simples_api IS NULL AND simples_status IS NOT NULL")
        statements.append("UPDATE cnpj_cache SET status_consulta = status WHERE status_consulta IS NULL AND status IS NOT NULL")
        statements.append("UPDATE cnpj_cache SET json_resposta = json_completo WHERE json_resposta IS NULL AND json_completo IS NOT NULL")
        statements.append("UPDATE cnpj_cache SET created_at = updated_at WHERE created_at IS NULL AND updated_at IS NOT NULL")

    if "nsu_controle" in table_names:
        nsu_columns = {column["name"] for column in inspector.get_columns("nsu_controle")}
        if "ultima_reconciliacao_em" not in nsu_columns:
            statements.append("ALTER TABLE nsu_controle ADD COLUMN ultima_reconciliacao_em DATE")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
