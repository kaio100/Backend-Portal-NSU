from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects.postgresql import insert

from backend.app.db.models import CnpjCache
from backend.app.services.cnpj_cache_service import RECEITA_FONTE
from backend.app.services.cnpj_receita_service import status_simples


def _digits(value: str | None) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _chunks(values: Sequence[str], size: int) -> Iterator[list[str]]:
    for index in range(0, len(values), size):
        yield list(values[index:index + size])


def coletar_cnpjs_online(connection) -> list[str]:
    rows = connection.execute(text("""
        SELECT cnpj FROM empresas WHERE cnpj IS NOT NULL
        UNION
        SELECT prestador_cnpj FROM notas WHERE prestador_cnpj IS NOT NULL
        UNION
        SELECT tomador_cnpj FROM notas WHERE tomador_cnpj IS NOT NULL
    """))
    return sorted({digits for (value,) in rows for digits in [_digits(value)] if len(digits) == 14})


def consultar_base_local(database_path: Path, cnpjs: Sequence[str]) -> tuple[list[dict], list[str]]:
    encontrados: list[dict] = []
    encontrados_cnpj: set[str] = set()
    query_template = """
        SELECT
            e.cnpj, e.cnpj_basico, e.cnpj_ordem, e.cnpj_dv,
            e.identificador_matriz_filial, e.nome_fantasia,
            e.situacao_cadastral, e.data_situacao_cadastral,
            e.data_inicio_atividade, e.cnae_fiscal_principal,
            e.cnae_fiscal_secundaria, e.tipo_logradouro, e.logradouro,
            e.numero, e.complemento, e.bairro, e.cep, e.uf,
            e.codigo_municipio, e.ddd1, e.telefone1, e.email,
            p.razao_social, p.natureza_juridica, p.capital_social,
            p.porte_empresa, s.opcao_simples, s.data_opcao_simples,
            s.data_exclusao_simples, s.opcao_mei, s.data_opcao_mei,
            s.data_exclusao_mei
        FROM estabelecimentos e
        LEFT JOIN empresas p ON p.cnpj_basico = e.cnpj_basico
        LEFT JOIN simples s ON s.cnpj_basico = e.cnpj_basico
        WHERE e.cnpj IN ({placeholders})
    """
    connection = sqlite3.connect(f"file:{database_path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        for group in _chunks(list(cnpjs), 800):
            query = query_template.format(placeholders=",".join("?" for _ in group))
            for row in connection.execute(query, group):
                item = dict(row)
                encontrados.append(item)
                encontrados_cnpj.add(item["cnpj"])
    finally:
        connection.close()
    return encontrados, sorted(set(cnpjs) - encontrados_cnpj)


def _status_simples(item: dict) -> str:
    return status_simples(item)


def montar_cache(item: dict, competencia: str, cache_days: int) -> dict:
    hoje = date.today()
    payload = dict(item)
    payload["fonte"] = RECEITA_FONTE
    payload["competencia_base"] = competencia
    consulta = _status_simples(item)
    return {
        "cnpj": item["cnpj"],
        "fonte": RECEITA_FONTE,
        "consulta_simples_api": consulta,
        "codigo_cnae": item.get("cnae_fiscal_principal") or "",
        "descricao_cnae": "",
        "status_consulta": "Encontrado",
        "json_resposta": payload,
        "erro": None,
        "data_consulta": hoje,
        "data_expiracao": hoje + timedelta(days=max(1, cache_days)),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "status": "Encontrado",
        "simples_status": consulta,
        "json_completo": payload,
    }


def sincronizar(database_url: str, local_db: Path, *, dry_run: bool, batch_size: int, cache_days: int) -> dict:
    if not local_db.is_file():
        raise RuntimeError(f"Base local nao encontrada: {local_db}")
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            cnpjs = coletar_cnpjs_online(connection)
        encontrados, ausentes = consultar_base_local(local_db, cnpjs)
        with sqlite3.connect(f"file:{local_db.resolve().as_posix()}?mode=ro", uri=True) as local:
            row = local.execute("SELECT valor FROM metadados WHERE chave='competencia'").fetchone()
            competencia = row[0] if row else "desconhecida"
        registros = [montar_cache(item, competencia, cache_days) for item in encontrados]
        gravados = 0
        if not dry_run:
            table = CnpjCache.__table__
            pk_columns = inspect(engine).get_pk_constraint("cnpj_cache").get("constrained_columns") or []
            conflict_columns = [table.c[name] for name in pk_columns]
            if not conflict_columns or "cnpj" not in pk_columns:
                raise RuntimeError(f"Chave primaria inesperada em cnpj_cache: {pk_columns}")
            with engine.begin() as connection:
                for group in _chunks(registros, batch_size):
                    statement = insert(table).values(group)
                    excluded = statement.excluded
                    statement = statement.on_conflict_do_update(
                        index_elements=conflict_columns,
                        set_={
                            "consulta_simples_api": excluded.consulta_simples_api,
                            "codigo_cnae": excluded.codigo_cnae,
                            "descricao_cnae": excluded.descricao_cnae,
                            "status_consulta": excluded.status_consulta,
                            "json_resposta": excluded.json_resposta,
                            "erro": excluded.erro,
                            "data_consulta": excluded.data_consulta,
                            "data_expiracao": excluded.data_expiracao,
                            "updated_at": excluded.updated_at,
                            "status": excluded.status,
                            "simples_status": excluded.simples_status,
                            "json_completo": excluded.json_completo,
                        },
                    )
                    connection.execute(statement)
                    gravados += len(group)
                    print(f"Sincronizados: {gravados}/{len(registros)}", flush=True)
        return {
            "cnpjs_online": len(cnpjs),
            "encontrados_receita": len(encontrados),
            "ausentes_receita": len(ausentes),
            "gravados": gravados,
            "dry_run": dry_run,
            "competencia": competencia,
        }
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Sincroniza CNPJs usados no portal com a base local da Receita.")
    parser.add_argument("--database-url", default=os.getenv("ONLINE_DATABASE_URL"))
    parser.add_argument("--base-local", type=Path, default=Path("data/cnpj_receita.sqlite3"))
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--cache-days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("Informe --database-url ou configure ONLINE_DATABASE_URL.")
    if not args.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        parser.error("O destino deve ser PostgreSQL.")
    try:
        result = sincronizar(
            args.database_url,
            args.base_local,
            dry_run=args.dry_run,
            batch_size=max(1, min(args.batch_size, 2000)),
            cache_days=args.cache_days,
        )
    except Exception as exc:
        print(f"Falha na sincronizacao: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
