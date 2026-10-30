# ADR-0008 — PDF entregue é o espelho gerado pelo PHP; PDFs antigos não são regerados

- **Status:** aceito
- **Data:** 2026-09-17 (PDF oficial removido, `44c6e726`); 2026-10-06 (não regerar após mudança de layout, `e71fc73c`)

## Contexto
O endpoint de PDF oficial do ADN deixou de existir. O portal precisa entregar um PDF de cada nota, inclusive com carimbo de cancelada ou substituída.

## Decisão
O PDF é sempre o espelho DANFSe gerado a partir do XML pela biblioteca PHP em `backend/danfse` (dompdf), chamada por `DanfseService` em subprocesso. Não há gerador alternativo em Python. Evento de cancelamento ou substituição regenera o espelho com carimbo. Mudança de layout vale só para PDFs novos; os já armazenados só mudam quando o script `regenerar_espelhos_desde` é executado (notas emitidas desde 09/2026, 30/10/2026). O ZIP em lote lê o espelho do storage e não gera PDF na hora. O código que lia e preferia o PDF oficial foi removido em 30/10/2026.

## Consequências
- (+) Uma implementação só; fiel ao leiaute nacional.
- (−) PHP 8.1+, extensões e Composer são dependências de produção (Dockerfile e CI).
- (−) Cada PDF custa 1–2 s de subprocesso na ingestão (por isso a ingestão reaproveita o espelho existente quando não precisa de carimbo).
- (−) PDFs antigos podem ter layout diferente dos novos.
