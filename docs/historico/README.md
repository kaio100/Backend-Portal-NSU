# Histórico (somente leitura)

Documentos congelados. Valem para a data e o commit em que foram escritos e **não descrevem o estado atual**. O estado atual fica em `docs/ai/`.

| Arquivo | Data | O que é |
|---|---|---|
| `ai-snapshot-2026-09-15/` (01–16) | 15/09/2026, base `f50da548`, remendos até F5 | Mapa antigo do sistema. Substituído pela estrutura atual de `docs/ai/` em 08/10/2026 |
| `REVISAO_TECNICA_MAPA.md` | 16–17/09/2026 | Revisão técnica e correções das duas primeiras rodadas |
| `DEPLOY_PRODUCAO.md` | 03/09/2026 | Guia de deploy antigo, antes do Alembic. Atual: `docs/ai/OPERATIONS.md` |
| `PENDENCIAS_BACKEND_PORTAL.md` | set/2026 | Regras de atribuição da fila do backend antigo, ainda não implementadas (FIND-L01 em `docs/ai/FINDINGS.md`) |
| `ANALISE_CANOPUS_CONSULTAS_2026-10-06.md` | 06/10/2026 | Incidente do monitor restrito (01–06/10) |
| `ANALISE_DOCUMENTACAO_2026-10-06.md` | 06/10/2026 | Diagnóstico da documentação antiga que motivou a reestruturação |
| `MONITORAMENTO_RAILWAY_2026-10-06.md` | 06/10/2026 | Verificação de produção após o deploy da F6 |
| `POS_DEPLOY_2026-10-06.md` | 06/10/2026 | Correções e pós-deploy de `a0cfbaf4` |
| `SEGURANCA_CERTIFICADOS_2026-10-06.md` | 06/10/2026 | Análise de segurança dos certificados (segredos no histórico do Git) |
| `AUDITORIA_BACKEND_2026-10-08.md` | 08/10/2026, `a0cfbaf4` | Auditoria completa do backend (ARCH-001..017) no modo `/analyze` |

Regra: não corrija esses arquivos. Se um fato mudou, atualize o documento de `docs/ai/` correspondente.
