# ADR-0002 — Esquema por `create_all` + Alembic idempotente; ajustes antigos congelados

- **Status:** aceito
- **Data:** 2026-09-25 (F2, `541f8018`)

## Contexto
O esquema era mantido por `create_all` + `ALTER TABLE` em runtime (`_ensure_runtime_columns`), sem histórico. Produção tem sobras de uma linha de commits abandonada (set/2026): tabelas e colunas fora dos modelos. Réplicas subindo juntas disputavam o DDL.

## Decisão
`migrate_db()` roda numa transação com `pg_advisory_xact_lock`: `create_all` → `_ensure_runtime_columns` (congelado) → `alembic upgrade head`. Toda mudança nova é uma revisão Alembic **idempotente** (`tabela_existe`/`coluna_existe`), porque o banco novo já nasce completo pelo `create_all` e o de produção tem sobras. A migração é o primeiro passo do `CMD` do Dockerfile, não do startup da API.

## Alternativas
- **Alembic "puro" a partir de um baseline gerado:** exigiria reconciliar as sobras de produção antes; risco maior naquele momento.

## Consequências
- (+) Histórico versionado; deploy não sobe com esquema velho.
- (−) Revisões precisam ser escritas defensivamente; `downgrade` não é útil (aditivas).
- (−) `_ensure_runtime_columns` ainda roda `UPDATE`s a cada deploy.

## Validação
`tests/test_db_migration_scripts.py`, `test_migracoes_alembic_ficam_no_head`. Falta CI com Postgres (ARCH-016).
