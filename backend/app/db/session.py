from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
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

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args(),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from backend.app.db import models  # noqa: F401
    from backend.app.db.base import Base

    Base.metadata.create_all(bind=engine)
    _ensure_runtime_columns()


def _ensure_runtime_columns() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    statements: list[str] = []
    is_sqlite = settings.database_url.startswith("sqlite")

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
        }
        for name, column_type in nota_runtime_columns.items():
            if name not in nota_columns:
                statements.append(f"ALTER TABLE notas ADD COLUMN {name} {column_type}")
        statements.append("UPDATE notas SET importado_em = COALESCE(updated_at, created_at) WHERE importado_em IS NULL")

    if "arquivos" in table_names:
        arquivo_columns = {column["name"] for column in inspector.get_columns("arquivos")}
        if "updated_at" not in arquivo_columns:
            column_type = "DATETIME" if is_sqlite else "TIMESTAMP WITH TIME ZONE"
            statements.append(f"ALTER TABLE arquivos ADD COLUMN updated_at {column_type}")
        if "filename" not in arquivo_columns:
            statements.append("ALTER TABLE arquivos ADD COLUMN filename VARCHAR(255)")
        statements.append("UPDATE arquivos SET updated_at = created_at WHERE updated_at IS NULL")

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
        statements.append("UPDATE cnpj_cache SET consulta_simples_api = COALESCE(consulta_simples_api, simples_status)")
        statements.append("UPDATE cnpj_cache SET status_consulta = COALESCE(status_consulta, status)")
        statements.append("UPDATE cnpj_cache SET json_resposta = COALESCE(json_resposta, json_completo)")
        statements.append("UPDATE cnpj_cache SET created_at = COALESCE(created_at, updated_at)")

    if "nsu_controle" in table_names:
        nsu_columns = {column["name"] for column in inspector.get_columns("nsu_controle")}
        if "ultima_reconciliacao_em" not in nsu_columns:
            statements.append("ALTER TABLE nsu_controle ADD COLUMN ultima_reconciliacao_em DATE")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
