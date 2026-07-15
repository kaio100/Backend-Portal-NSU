from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from backend.app.scripts.db_migration_common import (
    build_engine,
    compare_values,
    count_tables,
    existing_table_names,
    load_source_table,
    mask_database_url,
    sample_rows_by_id,
    sqlite_url_from_path,
)


CRITICAL_NOTA_FIELDS = [
    "id",
    "empresa_id",
    "processo_id",
    "chave",
    "numero_nfse",
    "prestador_cnpj",
    "tomador_cnpj",
    "valor_servico",
    "valor_liquido",
    "status_documento",
    "alertas_fiscais",
    "codigo_servico_raw",
    "codigo_servico_display",
    "subitem_lc116",
]

SAMPLE_TABLES = ["empresas", "notas", "arquivos", "processos", "eventos"]


class ValidationError(RuntimeError):
    pass


def _compare_samples(sqlite_engine, postgres_engine, table_name: str, fields: list[str] | None = None) -> list[str]:
    errors: list[str] = []
    source_rows = sample_rows_by_id(sqlite_engine, table_name)
    target_rows = sample_rows_by_id(postgres_engine, table_name)
    if len(source_rows) != len(target_rows):
        return [f"{table_name}: quantidade de amostras diferente sqlite={len(source_rows)} postgres={len(target_rows)}"]

    for index, (source, target) in enumerate(zip(source_rows, target_rows), start=1):
        keys = fields or sorted(set(source) & set(target))
        for key in keys:
            if key not in source or key not in target:
                continue
            if not compare_values(source.get(key), target.get(key)):
                errors.append(
                    f"{table_name} amostra {index} campo {key}: sqlite={source.get(key)!r} postgres={target.get(key)!r}"
                )
    return errors


def validar(sqlite_path: str | Path, postgres_url: str) -> dict[str, Any]:
    sqlite_path = Path(sqlite_path)
    if not sqlite_path.exists():
        raise ValidationError(f"SQLite nao encontrado: {sqlite_path}")
    sqlite_engine = build_engine(sqlite_url_from_path(sqlite_path))
    postgres_engine = build_engine(postgres_url)

    source_tables = set(existing_table_names(sqlite_engine))
    target_tables = set(existing_table_names(postgres_engine))
    common_tables = sorted(source_tables & target_tables)
    source_counts = count_tables(sqlite_engine, common_tables)
    target_counts = count_tables(postgres_engine, common_tables)

    errors: list[str] = []
    for table_name in common_tables:
        if source_counts.get(table_name) != target_counts.get(table_name):
            errors.append(
                f"{table_name}: contagem diferente sqlite={source_counts.get(table_name)} postgres={target_counts.get(table_name)}"
            )

    for table_name in SAMPLE_TABLES:
        if table_name in common_tables:
            fields = CRITICAL_NOTA_FIELDS if table_name == "notas" else None
            errors.extend(_compare_samples(sqlite_engine, postgres_engine, table_name, fields))

    if "arquivos" in common_tables and "notas" in common_tables:
        source_arquivos = load_source_table(sqlite_engine, "arquivos")
        target_arquivos = load_source_table(postgres_engine, "arquivos")
        source_samples = sample_rows_by_id(sqlite_engine, "arquivos", limit=10)
        target_samples = sample_rows_by_id(postgres_engine, "arquivos", limit=10)
        for source, target in zip(source_samples, target_samples):
            if not compare_values(source.get("nota_id"), target.get("nota_id")):
                errors.append(
                    f"arquivos id={source.get('id')}: nota_id diferente sqlite={source.get('nota_id')} postgres={target.get('nota_id')}"
                )

    return {
        "sqlite_path": str(sqlite_path),
        "postgres_url": mask_database_url(postgres_url),
        "source_counts": source_counts,
        "target_counts": target_counts,
        "errors": errors,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Valida a migração SQLite -> PostgreSQL.")
    parser.add_argument("--sqlite-path", required=True)
    parser.add_argument("--postgres-url", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    report = validar(args.sqlite_path, args.postgres_url)
    print(f"SQLITE={report['sqlite_path']}")
    print(f"POSTGRES={report['postgres_url']}")
    for table_name, count in report["source_counts"].items():
        print(f"- {table_name}: sqlite={count} postgres={report['target_counts'].get(table_name)}")
    if report["errors"]:
        print("ERROS:")
        for error in report["errors"]:
            print(f"- {error}")
        raise SystemExit("MIGRACAO_INVALIDA")
    print("MIGRACAO_OK")


if __name__ == "__main__":
    main()
