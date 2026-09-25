"""Contas por convite: versao de token, verificacao de e-mail e fim do papel leitura.

Revision ID: 0003_contas_convite
Revises: 0002_historico_conferencia
Create Date: 2026-09-25

As tabelas convites_cadastro, verificacoes_email_tokens e
redefinicoes_senha_tokens ja existem em producao (linha de set/2026) com o
mesmo formato dos modelos; no banco novo o create_all as cria. Aqui entram so
as colunas que faltam e a conversao do papel "leitura" em "operador".
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from backend.app.db.migrations.util import coluna_existe, tabela_existe

revision = "0003_contas_convite"
down_revision = "0002_historico_conferencia"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not coluna_existe("usuarios", "email_verificado"):
        op.add_column("usuarios", sa.Column("email_verificado", sa.Boolean(), nullable=False, server_default=sa.true()))
    if not coluna_existe("usuarios", "token_version"):
        op.add_column("usuarios", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    if tabela_existe("redefinicoes_senha_tokens") and not coluna_existe("redefinicoes_senha_tokens", "tentativas"):
        op.add_column(
            "redefinicoes_senha_tokens", sa.Column("tentativas", sa.Integer(), nullable=False, server_default="0")
        )
    # Decisao de 2026-09-25: so existem os papeis operador e admin.
    op.execute("UPDATE usuarios SET papel = 'operador' WHERE papel = 'leitura'")


def downgrade() -> None:
    pass
