"""Erros ja vistos no painel admin (botao "Limpar" sem apagar o historico).

Revision ID: 0005_erros_vistos
Revises: 0004_seguranca_admin
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from backend.app.db.migrations.util import tabela_existe

revision = "0005_erros_vistos"
down_revision = "0004_seguranca_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if tabela_existe("erros_vistos"):
        return
    op.create_table(
        "erros_vistos",
        sa.Column("grupo", sa.String(40), primary_key=True),
        sa.Column("visto_ate", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    pass
