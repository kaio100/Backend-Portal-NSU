from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import Engine, make_url

from backend.app.db import models  # noqa: F401
from backend.app.db.base import Base


IMPORTANT_TABLES = [
    "empresas",
    "certificados",
    "secrets",
    "processos",
    "processos_jobs",
    "notas",
    "arquivos",
    "eventos",
    "logs_processos",
    "nsu_controle",
    "monitoramento_config",
]


def normalize_database_url(database_url: str) -> str:
    url = str(database_url or "").strip()
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def mask_database_url(database_url: str) -> str:
    try:
        return make_url(normalize_database_url(database_url)).render_as_string(hide_password=True)
    except Exception:
        return "<DATABASE_URL invalida>"


def database_kind(database_url: str) -> str:
    drivername = make_url(normalize_database_url(database_url)).drivername
    if drivername.startswith("sqlite"):
        return "sqlite"
    if drivername.startswith("postgresql"):
        return "postgresql"
    return drivername


def build_engine(database_url: str) -> Engine:
    normalized = normalize_database_url(database_url)
    connect_args = {"check_same_thread": False} if normalized.startswith("sqlite") else {}
    return create_engine(normalized, connect_args=connect_args, pool_pre_ping=True)


def sqlite_url_from_path(sqlite_path: str | Path) -> str:
    path = Path(sqlite_path).expanduser()
    return f"sqlite:///{path.as_posix()}"


def sorted_model_tables() -> list[Table]:
    return list(Base.metadata.sorted_tables)


def table_names_for_models() -> list[str]:
    return [table.name for table in sorted_model_tables()]


def existing_table_names(engine: Engine) -> list[str]:
    return inspect(engine).get_table_names()


def count_table(engine: Engine, table_name: str) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one())


def count_tables(engine: Engine, table_names: Iterable[str] | None = None) -> dict[str, int]:
    existing = set(existing_table_names(engine))
    names = list(table_names or sorted(existing))
    return {name: count_table(engine, name) for name in names if name in existing}


def has_any_data(engine: Engine, table_names: Iterable[str] | None = None) -> tuple[bool, dict[str, int]]:
    counts = count_tables(engine, table_names)
    return any(count > 0 for count in counts.values()), counts


def normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped[0] in "[{":
            try:
                return json.loads(stripped)
            except Exception:
                return value
        return value
    return value


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: normalize_value(value) for key, value in row.items()}


def load_source_table(sqlite_engine: Engine, table_name: str) -> Table:
    metadata = MetaData()
    return Table(table_name, metadata, autoload_with=sqlite_engine)


def read_rows(engine: Engine, table: Table, offset: int, limit: int) -> list[dict[str, Any]]:
    stmt = select(table).offset(offset).limit(limit)
    with engine.connect() as conn:
        return [normalize_row(dict(row._mapping)) for row in conn.execute(stmt)]


def create_postgres_schema(postgres_engine: Engine) -> None:
    Base.metadata.create_all(bind=postgres_engine)


def reset_postgres_sequences(postgres_engine: Engine) -> None:
    if database_kind(str(postgres_engine.url)) != "postgresql":
        return
    with postgres_engine.begin() as conn:
        for table in sorted_model_tables():
            integer_pk = [
                column.name
                for column in table.primary_key.columns
                if len(table.primary_key.columns) == 1 and column.autoincrement is not False
            ]
            if not integer_pk:
                continue
            pk_name = integer_pk[0]
            conn.execute(
                text(
                    "SELECT setval("
                    "pg_get_serial_sequence(:table_name, :pk_name), "
                    f"COALESCE((SELECT MAX(\"{pk_name}\") FROM \"{table.name}\"), 1), "
                    f"(SELECT COUNT(*) > 0 FROM \"{table.name}\"))"
                ),
                {"table_name": table.name, "pk_name": pk_name},
            )


def compare_values(left: Any, right: Any) -> bool:
    if isinstance(left, Decimal):
        left = float(left)
    if isinstance(right, Decimal):
        right = float(right)
    if isinstance(left, (datetime, date)) and isinstance(right, (datetime, date)):
        return left.isoformat() == right.isoformat()
    return left == right


def sample_rows_by_id(engine: Engine, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
    if table_name not in set(existing_table_names(engine)):
        return []
    table = load_source_table(engine, table_name)
    columns = list(table.c)
    order_column = table.c.id if "id" in table.c else columns[0]
    stmt = select(table).order_by(order_column).limit(limit)
    with engine.connect() as conn:
        return [normalize_row(dict(row._mapping)) for row in conn.execute(stmt)]
