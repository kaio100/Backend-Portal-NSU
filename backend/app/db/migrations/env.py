"""Ambiente do Alembic.

Normalmente chamado por session.migrate_db(), que passa a conexao (e a
transacao com o advisory lock) em config.attributes["connection"]. Pela
linha de comando (alembic -c alembic.ini ...), abre a conexao do DATABASE_URL.
"""

from __future__ import annotations

from alembic import context

from backend.app.db import models  # noqa: F401
from backend.app.db.base import Base

conexao = context.config.attributes.get("connection")


def _rodar(connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if conexao is not None:
    _rodar(conexao)
else:
    from backend.app.db.session import engine

    with engine.begin() as connection:
        _rodar(connection)
