from __future__ import annotations

from sqlalchemy import text

from backend.app.core.config import settings
from backend.app.scripts.db_migration_common import (
    build_engine,
    count_tables,
    database_kind,
    existing_table_names,
    mask_database_url,
)


def diagnosticar(database_url: str | None = None) -> dict:
    url = database_url or settings.database_url
    engine = build_engine(url)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1")).scalar_one()
    tables = existing_table_names(engine)
    counts = count_tables(engine, tables)
    return {
        "database_url": mask_database_url(url),
        "tipo": database_kind(url),
        "tables": tables,
        "counts": counts,
    }


def main() -> None:
    report = diagnosticar()
    print(f"DATABASE_URL={report['database_url']}")
    print(f"TIPO={report['tipo']}")
    print("TABELAS:")
    for table in report["tables"]:
        print(f"- {table}: {report['counts'].get(table, 0)}")
    print("DB_OK")


if __name__ == "__main__":
    main()
