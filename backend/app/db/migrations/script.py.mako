"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Regra do projeto: a revisao precisa ser idempotente (use tabela_existe /
coluna_existe de backend.app.db.migrations.util). O banco novo ja nasce com
tudo pelo create_all e o de producao tem sobras de versoes antigas.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from backend.app.db.migrations.util import coluna_existe, indice_existe, tabela_existe  # noqa: F401

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
