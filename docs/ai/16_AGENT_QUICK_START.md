# Quick start para um novo agente

## Arquitetura em 30 segundos

React/Vite chama FastAPI. JWT/API key e grupo são aplicados em `api/deps.py`. Routers chamam services/repositories e persistem SQLAlchemy. Consulta ADN é assíncrona: `Processo` + `Job` → worker → motor legado → ingestão XML/eventos/PDF → `Nota`/`Arquivo`/storage. O frontend compatível é o commit `0fd4b07`; backend é `f50da548`.

## Primeira leitura

`docs/ai/01_PROJECT_OVERVIEW.md` → `02_ARCHITECTURE.md` → `13_CRITICAL_FILES.md` → documento do domínio. Código mínimo: `backend/app/core/config.py`, `backend/app/main.py`, `backend/app/db/models.py`, `backend/app/db/session.py`, `backend/app/api/deps.py`.

## Top 20 arquivos

1. `backend/app/main.py`
2. `backend/app/core/config.py`
3. `backend/app/db/models.py`
4. `backend/app/db/session.py`
5. `backend/app/api/deps.py`
6. `backend/app/api/routers/notas.py`
7. `backend/app/schemas/notas.py`
8. `backend/app/services/notas_service.py`
9. `backend/app/repositories/notas_repo.py`
10. `backend/app/services/legacy_ingestion_service.py`
11. `backend/app/services/legacy_processing_service.py`
12. `adn_nfse_downloader.py`
13. `backend/app/worker/jobs.py`
14. `backend/app/services/consultas_service.py`
15. `backend/app/services/operational_fields_service.py`
16. `backend/app/services/retencoes_calculo_service.py`
17. `backend/app/services/portal_support_service.py`
18. `backend/app/services/storage_service.py`
19. `backend/app/services/notas_download_service.py`
20. `frontend/src/lib/api.ts`

## Fluxos principais

- **Login:** `Login.tsx` → `api.login` → `/auth/login` → PBKDF2/JWT → `useAuth`.
- **Consulta:** `/consultas/iniciar` → `consultas_service` → Processo/Job → worker/legado/ADN → ingestão.
- **Nota:** XML → parser/status/retenções → upsert por `(empresa,chave)` → storage/Arquivo → `/notas`.
- **Conferência:** Conferencia component → PATCH `/notas/{id}/conferencia`; nota com responsável exige `retificar=true`.
- **Download:** filtros → repository (teto 5.000) → Arquivo/storage → ZIP.
- **DANFSe:** XML → `/api/danfse/gerar` → PHP → PDF.

## Top regras

1. Tenant por `Empresa.grupo`.
2. CNPJ de empresa tem 14 dígitos e é único.
3. Certificado elegível precisa ativo, válido, armazenado e com senha.
4. Nota é idempotente por empresa + chave.
5. Status fiscal não é status de fila.
6. Manual de fila vence cálculo automático; cancelada/substituída vêm do documento.
7. Decimal/ROUND_HALF_UP para retenções.
8. Alertas fiscais e observação interna são read-only para usuário.
9. Retificação é explícita e sobrescreve análise atual.
10. Storage key deve passar pelo naming/path safety.

## Principais tabelas

`empresas`, `certificados`, `processos`, `processos_jobs`, `monitoramento_config`, `nsu_controle`, `notas`, `eventos`, `arquivos`, `logs_processos`, `locks_processamento`, `cnpj_cache`, `secrets`, `usuarios`, `acessos_usuarios`.

## Principais endpoints

`POST /auth/login`, `GET /auth/me`; `GET/POST /empresas`; `/certificados*`; `GET/POST /consultas/*`; `/processos*`; `GET /notas*`; `PATCH /notas/{id}/conferencia`; `POST/GET /notas/download-lote`; `GET /eventos`; `/arquivos/*`; `POST /relatorios/conferencia`; `POST /api/danfse/gerar`; `/health`.

## Principais riscos

Migração sem Alembic, DB/storage não atômicos, concorrência de jobs/locks, cancelamento não cooperativo, limites de exportação, filtros GET incompletos, auth frontend desalinhada, função XLSX duplicada e retificação sem histórico. Consulte `10_RISK_REGISTER.md`.

## Onde mexer

| Tarefa | Comece em | Leia junto |
|---|---|---|
| Auth/tenant | `backend/app/api/deps.py`, `backend/app/core/security.py` | auth router/service, `api.ts`, useAuth |
| Consulta ADN | `consultas_service.py` | processos, jobs, legacy processing, NSU/locks |
| Parsing/status | `legacy_ingestion_service.py` | models.Nota, XML parser, operational/fiscal |
| Conferência | `schemas/notas.py`, `routers/notas.py` | notas_service, componentes de Conferência |
| Filtros | `notas_repo.py`, `notas_service.py` | schemas, download, portal, `api.ts` |
| ZIP | `notas_download_service.py` | storage/naming, arquivos router |
| XLSX | `portal_support_service.py` | relatorios router, retenções/CNPJ |
| Banco | `models.py`, `session.py` | migration scripts, repositories, Docker |
| PDF | `danfse_service.py` | `backend/danfse`, composer, teste PHP |

## Antes de commit

Verifique tenant/roles, testes de erro e duplicidade, contrato frontend, migration, storage keys, segredos e `git diff/status`. Não execute limpeza/arquivamento sem backup e confirmação.
