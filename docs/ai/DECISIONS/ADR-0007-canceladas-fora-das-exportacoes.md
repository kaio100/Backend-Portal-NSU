# ADR-0007 — Canceladas e substituídas fora do ZIP e da planilha

- **Status:** aceito
- **Data:** 2026-09-25 (primeira versão `c43cb834`, revertida em `ebbb4a86`; reaplicada em `6c9a2d6c` depois do ADR-0004)

## Contexto
O analista exporta o lote para lançar ou conferir. Nota cancelada ou substituída no lote gera retrabalho e erro de lançamento.

## Decisão
Notas com `status_documento` cancelada ou substituída nunca entram no ZIP nem na planilha de conferência (por filtro ou por `nota_ids`, GET e POST). O filtro é SQL, antes do limite; status `NULL` entra. A listagem do portal continua mostrando essas notas (REG-036). Só foi para produção depois de corrigir a classificação de status (ADR-0004), com `corrigir_status_fiscal --aplicar` no deploy.

## Consequências
- (+) Exportação limpa.
- (−) Exportar de propósito só as canceladas responde 404 / planilha vazia.
