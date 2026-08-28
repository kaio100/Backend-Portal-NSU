from __future__ import annotations

import argparse
import csv
import os
import re
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, text


def _database_url() -> str:
    configured = os.getenv("SUPABASE_DATABASE_URL") or os.getenv("ONLINE_DATABASE_URL")
    url = configured or dotenv_values(".env").get("DATABASE_URL")
    if not url:
        raise RuntimeError("Conexao do portal online nao configurada.")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return str(url)


SQL = text(r"""
WITH partes AS (
    SELECT
        n.id AS nota_id,
        regexp_replace(
            CASE
                WHEN regexp_replace(coalesce(n.tomador_cnpj, ''), '\D', '', 'g')
                     = regexp_replace(coalesce(emp.cnpj, ''), '\D', '', 'g')
                    THEN coalesce(n.prestador_cnpj, '')
                WHEN regexp_replace(coalesce(n.prestador_cnpj, ''), '\D', '', 'g')
                     = regexp_replace(coalesce(emp.cnpj, ''), '\D', '', 'g')
                    THEN coalesce(n.tomador_cnpj, '')
                ELSE coalesce(n.prestador_cnpj, n.tomador_cnpj, '')
            END,
            '\D', '', 'g'
        ) AS documento
    FROM notas n
    JOIN empresas emp ON emp.id = n.empresa_id
), escolhidos AS (
    SELECT
        p.nota_id,
        p.documento,
        c.consulta_simples_api,
        c.status_consulta,
        c.erro,
        c.fonte,
        c.data_expiracao,
        row_number() OVER (
            PARTITION BY p.nota_id
            ORDER BY
                CASE c.fonte
                    WHEN 'Receita Federal - Dados Abertos' THEN 0
                    WHEN 'Invertexto' THEN 1
                    ELSE 2
                END,
                c.data_expiracao DESC NULLS LAST
        ) AS rn
    FROM partes p
    LEFT JOIN cnpj_cache c
      ON c.cnpj = p.documento
     AND c.data_expiracao >= current_date
)
SELECT
    documento,
    coalesce(consulta_simples_api, 'Pendente') AS consulta,
    coalesce(status_consulta, 'Sem cache') AS status,
    coalesce(fonte, 'Sem cache') AS fonte,
    count(*) AS notas,
    max(left(coalesce(erro, ''), 160)) AS erro
FROM escolhidos
WHERE rn = 1
  AND documento <> ''
  AND (
      consulta_simples_api IS NULL
      OR consulta_simples_api IN ('Não consultado', 'Não disponível', 'Erro na consulta')
  )
GROUP BY documento, consulta_simples_api, status_consulta, fonte
ORDER BY consulta, notas DESC, documento
""")


def listar() -> list[dict]:
    engine = create_engine(_database_url(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return [dict(row) for row in connection.execute(SQL).mappings()]
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    rows = listar()
    print(f"TOTAL_CNPJS={len(rows)}")
    print(f"TOTAL_NOTAS={sum(int(row['notas']) for row in rows)}")
    print("CNPJ|CONSULTA|STATUS|FONTE|NOTAS|ERRO")
    sanitized = []
    for row in rows:
        item = dict(row)
        item["erro"] = re.sub(r"([?&]token=)[^&\s]+", r"\1[REDACTED]", str(item.get("erro") or ""))
        sanitized.append(item)
        if not args.quiet:
            print("|".join(str(item[key] or "") for key in ("documento", "consulta", "status", "fonte", "notas", "erro")))
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8-sig") as output:
            writer = csv.DictWriter(output, fieldnames=("documento", "consulta", "status", "fonte", "notas", "erro"))
            writer.writeheader()
            writer.writerows(sanitized)
        print(f"CSV={args.csv.resolve()}")


if __name__ == "__main__":
    main()
