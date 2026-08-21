from __future__ import annotations

import argparse
import csv
import io
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence


EMPRESA_COLUMNS = (
    "cnpj_basico", "razao_social", "natureza_juridica", "qualificacao_responsavel",
    "capital_social", "porte_empresa", "ente_federativo_responsavel",
)
ESTABELECIMENTO_COLUMNS = (
    "cnpj_basico", "cnpj_ordem", "cnpj_dv", "identificador_matriz_filial",
    "nome_fantasia", "situacao_cadastral", "data_situacao_cadastral",
    "motivo_situacao_cadastral", "nome_cidade_exterior", "pais",
    "data_inicio_atividade", "cnae_fiscal_principal", "cnae_fiscal_secundaria",
    "tipo_logradouro", "logradouro", "numero", "complemento", "bairro", "cep",
    "uf", "codigo_municipio", "ddd1", "telefone1", "ddd2", "telefone2",
    "ddd_fax", "fax", "email", "situacao_especial", "data_situacao_especial",
)
SIMPLES_COLUMNS = (
    "cnpj_basico", "opcao_simples", "data_opcao_simples", "data_exclusao_simples",
    "opcao_mei", "data_opcao_mei", "data_exclusao_mei",
)


def _digits(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


def _targets(values: Sequence[str]) -> tuple[set[str], set[str]]:
    full = {_digits(value) for value in values}
    invalid = sorted(value for value in full if len(value) != 14)
    if invalid:
        raise ValueError(f"CNPJ invalido: {', '.join(invalid)}")
    return full, {value[:8] for value in full}


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        PRAGMA temp_store=MEMORY;
        CREATE TABLE IF NOT EXISTS metadados (
            chave TEXT PRIMARY KEY, valor TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS empresas (
            cnpj_basico TEXT PRIMARY KEY, razao_social TEXT, natureza_juridica TEXT,
            qualificacao_responsavel TEXT, capital_social TEXT, porte_empresa TEXT,
            ente_federativo_responsavel TEXT
        );
        CREATE TABLE IF NOT EXISTS estabelecimentos (
            cnpj TEXT PRIMARY KEY, cnpj_basico TEXT NOT NULL, cnpj_ordem TEXT,
            cnpj_dv TEXT, identificador_matriz_filial TEXT, nome_fantasia TEXT,
            situacao_cadastral TEXT, data_situacao_cadastral TEXT,
            motivo_situacao_cadastral TEXT, nome_cidade_exterior TEXT, pais TEXT,
            data_inicio_atividade TEXT, cnae_fiscal_principal TEXT,
            cnae_fiscal_secundaria TEXT, tipo_logradouro TEXT, logradouro TEXT,
            numero TEXT, complemento TEXT, bairro TEXT, cep TEXT, uf TEXT,
            codigo_municipio TEXT, ddd1 TEXT, telefone1 TEXT, ddd2 TEXT,
            telefone2 TEXT, ddd_fax TEXT, fax TEXT, email TEXT,
            situacao_especial TEXT, data_situacao_especial TEXT
        );
        CREATE TABLE IF NOT EXISTS simples (
            cnpj_basico TEXT PRIMARY KEY, opcao_simples TEXT, data_opcao_simples TEXT,
            data_exclusao_simples TEXT, opcao_mei TEXT, data_opcao_mei TEXT,
            data_exclusao_mei TEXT
        );
    """)


def _outer_members(archive: zipfile.ZipFile, prefix: str) -> list[str]:
    pattern = re.compile(rf"(?:^|/){re.escape(prefix)}\d*\.zip$", re.IGNORECASE)
    return sorted(name for name in archive.namelist() if pattern.search(name))


def _rows_from_nested_zip(outer: zipfile.ZipFile, member: str, temp_dir: Path) -> Iterator[list[str]]:
    nested_path = temp_dir / Path(member).name
    with outer.open(member) as source, nested_path.open("wb") as target:
        shutil.copyfileobj(source, target, length=8 * 1024 * 1024)
    try:
        with zipfile.ZipFile(nested_path) as nested:
            csv_members = [item for item in nested.infolist() if not item.is_dir()]
            if not csv_members:
                return
            for csv_member in csv_members:
                with nested.open(csv_member) as raw:
                    text = io.TextIOWrapper(raw, encoding="latin-1", newline="")
                    # Alguns pacotes mensais da Receita trazem bytes NUL de
                    # preenchimento no CSV. Eles nao pertencem aos campos e o
                    # modulo csv os rejeita, portanto sao removidos por linha.
                    clean_lines = (line.replace("\x00", "") for line in text)
                    yield from csv.reader(clean_lines, delimiter=";", quotechar='"')
    finally:
        nested_path.unlink(missing_ok=True)


def _chunks(rows: Iterable[tuple], size: int = 10_000) -> Iterator[list[tuple]]:
    chunk: list[tuple] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _selected_rows(rows: Iterable[list[str]], columns: Sequence[str], roots: set[str]) -> Iterator[tuple]:
    expected = len(columns)
    for row in rows:
        if len(row) < expected or (roots and row[0] not in roots):
            continue
        yield tuple(row[:expected])


def _import_group(
    connection: sqlite3.Connection,
    outer: zipfile.ZipFile,
    temp_dir: Path,
    prefix: str,
    table: str,
    columns: Sequence[str],
    roots: set[str],
) -> int:
    members = _outer_members(outer, prefix)
    placeholders = ",".join("?" for _ in columns)
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    count = 0
    for member in members:
        print(f"Processando {member}...", flush=True)
        rows = _selected_rows(_rows_from_nested_zip(outer, member, temp_dir), columns, roots)
        if table == "estabelecimentos":
            rows = ((row[0] + row[1] + row[2], *row) for row in rows)
            sql = f"INSERT OR REPLACE INTO {table} (cnpj,{','.join(columns)}) VALUES (? ,{placeholders})"
        for chunk in _chunks(rows):
            connection.executemany(sql, chunk)
            connection.commit()
            count += len(chunk)
            if count % 1_000_000 == 0:
                print(f"  {table}: {count:,} registros", flush=True)
    return count


def importar(source: Path, destination: Path, cnpjs: Sequence[str]) -> dict[str, int]:
    full_targets, roots = _targets(cnpjs)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(destination) as connection:
        _schema(connection)
        with zipfile.ZipFile(source) as outer, tempfile.TemporaryDirectory(
            prefix="cnpj_receita_", dir=destination.parent
        ) as temp_name:
            temp_dir = Path(temp_name)
            counts = {
                "estabelecimentos": _import_group(
                    connection, outer, temp_dir, "Estabelecimentos", "estabelecimentos",
                    ESTABELECIMENTO_COLUMNS, roots,
                ),
                "empresas": _import_group(
                    connection, outer, temp_dir, "Empresas", "empresas", EMPRESA_COLUMNS, roots,
                ),
                "simples": _import_group(
                    connection, outer, temp_dir, "Simples", "simples", SIMPLES_COLUMNS, roots,
                ),
            }
        competence = source.stem
        now = datetime.now(timezone.utc).isoformat()
        connection.executemany(
            "INSERT OR REPLACE INTO metadados(chave, valor) VALUES (?, ?)",
            [("competencia", competence), ("importado_em", now), ("origem", str(source.resolve()))],
        )
        print("Criando indice de consulta por raiz do CNPJ...", flush=True)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS ix_estabelecimentos_basico "
            "ON estabelecimentos(cnpj_basico)"
        )
        connection.execute("PRAGMA optimize")
        connection.commit()
        if full_targets:
            found = {
                row[0]
                for row in connection.execute(
                    f"SELECT cnpj FROM estabelecimentos WHERE cnpj IN ({','.join('?' for _ in full_targets)})",
                    tuple(full_targets),
                )
            }
            missing = sorted(full_targets - found)
            if missing:
                print(f"Aviso: CNPJs nao encontrados: {', '.join(missing)}", file=sys.stderr)
        return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Importa dados abertos de CNPJ da Receita para SQLite.")
    parser.add_argument("arquivo", type=Path, help="ZIP mensal baixado da Receita")
    parser.add_argument("--destino", type=Path, default=Path("data/cnpj_receita.sqlite3"))
    parser.add_argument("--cnpj", action="append", default=[], help="Importa apenas este CNPJ (repetivel)")
    args = parser.parse_args()
    if not args.arquivo.is_file():
        parser.error(f"Arquivo nao encontrado: {args.arquivo}")
    counts = importar(args.arquivo, args.destino, args.cnpj)
    print(f"Importacao concluida: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
