"""Linha de base do versionamento de esquema.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-25

Tudo o que existia antes desta revisao e criado por Base.metadata.create_all
e pelos ajustes congelados de session._ensure_runtime_columns. O banco de
producao (Supabase) tambem tem sobras da linha de set/2026 que nao estao nos
modelos: feedbacks, convites_cadastro, auditoria_admin, configuracoes_sistema,
redefinicoes_senha_tokens, verificacoes_email_tokens e colunas extras em
usuarios, certificados e processos. Esta revisao nao altera nada: so marca o
ponto de partida no alembic_version.
"""

from __future__ import annotations

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
