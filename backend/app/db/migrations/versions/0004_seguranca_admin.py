"""Seguranca: limite de tentativas no banco, 2FA de administrador e auditoria do admin.

Revision ID: 0004_seguranca_admin
Revises: 0003_contas_convite
Create Date: 2026-10-15

Pelo migrate_db o create_all ja cria as tabelas novas; esta revisao garante o
mesmo esquema quando o Alembic roda sozinho e acrescenta as colunas de 2FA.
A auditoria fica em auditoria_painel_admin: auditoria_admin ja existe em producao
(sobra de set/2026, outras colunas, vazia) e nao e tocada.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from backend.app.db.migrations.util import coluna_existe, indice_existe, tabela_existe

revision = "0004_seguranca_admin"
down_revision = "0003_contas_convite"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not coluna_existe("usuarios", "totp_segredo_cifrado"):
        op.add_column("usuarios", sa.Column("totp_segredo_cifrado", sa.Text(), nullable=True))
    if not coluna_existe("usuarios", "totp_ativo"):
        op.add_column("usuarios", sa.Column("totp_ativo", sa.Boolean(), nullable=False, server_default=sa.false()))
    if not coluna_existe("usuarios", "totp_ultimo_passo"):
        op.add_column("usuarios", sa.Column("totp_ultimo_passo", sa.BigInteger(), nullable=True))

    if not tabela_existe("tentativas_acesso"):
        op.create_table(
            "tentativas_acesso",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("chave", sa.String(64), nullable=False),
            sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False),
        )
    if not indice_existe("tentativas_acesso", "ix_tentativas_acesso_chave"):
        op.create_index("ix_tentativas_acesso_chave", "tentativas_acesso", ["chave"])
    if not indice_existe("tentativas_acesso", "ix_tentativas_acesso_criado_em"):
        op.create_index("ix_tentativas_acesso_criado_em", "tentativas_acesso", ["criado_em"])

    if not tabela_existe("auditoria_painel_admin"):
        op.create_table(
            "auditoria_painel_admin",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("usuario_id", sa.Integer(), nullable=True),
            sa.Column("email", sa.String(255), nullable=True),
            sa.Column("grupo", sa.String(40), nullable=True),
            sa.Column("acao", sa.String(160), nullable=False),
            sa.Column("resultado", sa.String(40), nullable=False),
            sa.Column("detalhes", sa.Text(), nullable=True),
            sa.Column("ip", sa.String(80), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    for coluna in ("usuario_id", "grupo", "created_at"):
        nome = f"ix_auditoria_painel_admin_{coluna}"
        if not indice_existe("auditoria_painel_admin", nome):
            op.create_index(nome, "auditoria_painel_admin", [coluna])


def downgrade() -> None:
    pass
