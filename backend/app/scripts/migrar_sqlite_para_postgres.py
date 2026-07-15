from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from backend.app.scripts.db_migration_common import (
    build_engine,
    count_table,
    create_postgres_schema,
    database_kind,
    existing_table_names,
    has_any_data,
    load_source_table,
    mask_database_url,
    read_rows,
    reset_postgres_sequences,
    sorted_model_tables,
    sqlite_url_from_path,
)


class MigrationError(RuntimeError):
    pass


def migrar(
    sqlite_path: str | Path,
    postgres_url: str,
    *,
    dry_run: bool = False,
    execute: bool = False,
    batch_size: int = 500,
) -> dict[str, Any]:
    if not dry_run and not execute:
        raise MigrationError("Informe --dry-run ou --all.")
    if dry_run and execute:
        raise MigrationError("Use apenas um modo: --dry-run ou --all.")

    sqlite_path = Path(sqlite_path)
    if not sqlite_path.exists():
        raise MigrationError(f"SQLite nao encontrado: {sqlite_path}")

    sqlite_engine = build_engine(sqlite_url_from_path(sqlite_path))
    postgres_engine = build_engine(postgres_url)
    if database_kind(str(postgres_engine.url)) != "postgresql":
        raise MigrationError("postgres-url precisa ser PostgreSQL.")

    source_tables = set(existing_table_names(sqlite_engine))
    model_tables = [table for table in sorted_model_tables() if table.name in source_tables]
    table_names = [table.name for table in model_tables]

    target_has_data, target_counts = has_any_data(postgres_engine)
    if target_has_data and execute:
        raise MigrationError(f"Postgres ja possui dados. Migração abortada. Contagens: {target_counts}")

    report: dict[str, Any] = {
        "sqlite_path": str(sqlite_path),
        "postgres_url": mask_database_url(postgres_url),
        "dry_run": dry_run,
        "target_has_data": target_has_data,
        "target_counts": target_counts,
        "tables": {},
    }

    for table in model_tables:
        report["tables"][table.name] = {"source_count": count_table(sqlite_engine, table.name), "inserted": 0}

    if dry_run:
        return report

    create_postgres_schema(postgres_engine)

    for target_table in model_tables:
        source_table = load_source_table(sqlite_engine, target_table.name)
        source_columns = set(source_table.c.keys())
        target_columns = set(target_table.c.keys())
        common_columns = [column for column in target_table.c.keys() if column in source_columns and column in target_columns]

        inserted = 0
        offset = 0
        while True:
            rows = read_rows(sqlite_engine, source_table, offset, batch_size)
            if not rows:
                break
            payload = [{key: row.get(key) for key in common_columns} for row in rows]
            if payload:
                with postgres_engine.begin() as conn:
                    conn.execute(target_table.insert(), payload)
                inserted += len(payload)
            offset += batch_size
        report["tables"][target_table.name]["inserted"] = inserted

    reset_postgres_sequences(postgres_engine)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migra metadados do SQLite para PostgreSQL/Supabase.")
    parser.add_argument("--sqlite-path", required=True, help="Caminho do arquivo .db SQLite de origem.")
    parser.add_argument("--postgres-url", required=True, help="URL PostgreSQL/Supabase de destino.")
    parser.add_argument("--dry-run", action="store_true", help="Apenas simula, sem criar tabelas nem inserir dados.")
    parser.add_argument("--all", action="store_true", help="Executa a migração real.")
    parser.add_argument("--batch-size", type=int, default=500, help="Quantidade de linhas por lote.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        report = migrar(
            sqlite_path=args.sqlite_path,
            postgres_url=args.postgres_url,
            dry_run=args.dry_run,
            execute=args.all,
            batch_size=args.batch_size,
        )
    except (MigrationError, SQLAlchemyError) as exc:
        raise SystemExit(f"MIGRACAO_ERRO: {exc}") from exc

    print(f"SQLITE={report['sqlite_path']}")
    print(f"POSTGRES={report['postgres_url']}")
    print(f"MODO={'dry-run' if report['dry_run'] else 'real'}")
    for table_name, table_report in report["tables"].items():
        print(f"- {table_name}: origem={table_report['source_count']} inseridos={table_report['inserted']}")
    print("DRY_RUN_OK" if report["dry_run"] else "MIGRACAO_FINALIZADA")


if __name__ == "__main__":
    main()
