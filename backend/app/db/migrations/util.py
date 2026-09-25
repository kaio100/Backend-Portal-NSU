"""Verificacoes para revisoes idempotentes do Alembic."""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect


def _inspector():
    return inspect(op.get_bind())


def tabela_existe(tabela: str) -> bool:
    return tabela in _inspector().get_table_names()


def coluna_existe(tabela: str, coluna: str) -> bool:
    return tabela_existe(tabela) and coluna in {c["name"] for c in _inspector().get_columns(tabela)}


def indice_existe(tabela: str, indice: str) -> bool:
    return tabela_existe(tabela) and indice in {i["name"] for i in _inspector().get_indexes(tabela)}
