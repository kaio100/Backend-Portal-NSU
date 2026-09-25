"""Historico da analise fiscal (notas_conferencia_historico).

Revision ID: 0002_historico_conferencia
Revises: 0001_baseline
Create Date: 2026-09-25

Pelo migrate_db o create_all ja cria a tabela; esta revisao garante o mesmo
esquema quando o Alembic roda sozinho (linha de comando).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from backend.app.db.migrations.util import tabela_existe

revision = "0002_historico_conferencia"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if tabela_existe("notas_conferencia_historico"):
        return
    op.create_table(
        "notas_conferencia_historico",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nota_id", sa.Integer(), sa.ForeignKey("notas.id"), nullable=True),
        sa.Column("empresa_id", sa.Integer(), sa.ForeignKey("empresas.id"), nullable=False),
        sa.Column("chave", sa.String(80), nullable=False),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("usuario_nome", sa.String(255), nullable=True),
        sa.Column("usuario_email", sa.String(255), nullable=True),
        sa.Column("acao", sa.String(20), nullable=False),
        sa.Column("alteracoes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for coluna in ("id", "nota_id", "empresa_id", "chave", "usuario_id", "created_at"):
        op.create_index(f"ix_notas_conferencia_historico_{coluna}", "notas_conferencia_historico", [coluna])


def downgrade() -> None:
    if tabela_existe("notas_conferencia_historico"):
        op.drop_table("notas_conferencia_historico")
