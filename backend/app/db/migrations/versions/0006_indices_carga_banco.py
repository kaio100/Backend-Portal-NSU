"""Indices de carga criados em producao no deploy manual de 15/10.

O banco de producao ficou marcado com esta revisao depois de um deploy feito
fora do Git (railway up, 15/10 20h14). O arquivo nao estava no repositorio, e
sem ele qualquer deploy da main parava no startup com "Can't locate revision
'0006_indices_carga_banco'" (queda do login em 16/10 09h48).

Recriado a partir do que existe no Postgres de producao (pg_indexes), so com
IF NOT EXISTS: em producao nao faz nada (a revisao ja esta aplicada) e num
banco novo deixa os mesmos indices.

Revision ID: 0006_indices_carga_banco
Revises: 0005_erros_vistos
Create Date: 2026-10-15
"""

from __future__ import annotations

from alembic import op

from backend.app.db.migrations.util import tabela_existe

revision = "0006_indices_carga_banco"
down_revision = "0005_erros_vistos"
branch_labels = None
depends_on = None


_INDICES_COMUNS = (
    ("processos_jobs", "CREATE INDEX IF NOT EXISTS ix_processos_jobs_status_updated_at ON processos_jobs (status, updated_at)"),
    ("tentativas_acesso", "CREATE INDEX IF NOT EXISTS ix_tentativas_acesso_chave_criado_em ON tentativas_acesso (chave, criado_em)"),
)

# Indices de expressao da paginacao por cursor; a sintaxe de cast e do Postgres.
_INDICES_POSTGRES = (
    (
        "notas",
        "CREATE INDEX IF NOT EXISTS ix_notas_cursor_emissao ON notas ("
        "COALESCE(data_emissao, '1900-01-01'::date), "
        "COALESCE(importado_em, '1900-01-01 00:00:00+00'::timestamptz), "
        "COALESCE(updated_at, '1900-01-01 00:00:00+00'::timestamptz), id)",
    ),
    (
        "notas",
        "CREATE INDEX IF NOT EXISTS ix_notas_cursor_recentes ON notas ("
        "COALESCE(importado_em, '1900-01-01 00:00:00+00'::timestamptz), "
        "COALESCE(updated_at, '1900-01-01 00:00:00+00'::timestamptz), id)",
    ),
)


def upgrade() -> None:
    dialeto = op.get_bind().dialect.name
    indices = list(_INDICES_COMUNS)
    if dialeto == "postgresql":
        indices.extend(_INDICES_POSTGRES)
    for tabela, sql in indices:
        if tabela_existe(tabela):
            op.execute(sql)


def downgrade() -> None:
    pass
