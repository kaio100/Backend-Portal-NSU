# Mapa de dependências

## Cadeias principais

```text
backend/app/main.py
  ├─ api/routers/*
  │   ├─ api/deps.py ── db/session.py ── db/models.py
  │   └─ services/* ── repositories/* ── models.py
  ├─ worker/jobs.py ── worker/worker.py ── worker/scheduler.py
  └─ core/observability.py / core/config.py / storage_service.py

consultas_service.py
  -> processos_service.py -> models.Processo/Job
  -> certificados_service.py + secrets_service.py
  -> nsu_control_service.py + locks_service.py

worker/jobs.py
  -> legacy_processing_service.py
    -> adn_nfse_downloader.py
    -> legacy_ingestion_service.py
      -> nfse_xml_parser.py
      -> operational_fields_service.py
      -> retencoes_regras_service.py + retencoes_calculo_service.py
      -> storage_naming_service.py + storage_service.py
      -> models Nota/Evento/Arquivo

frontend/src/lib/api.ts
  -> FastAPI routers
  -> React hooks
  -> pages/components
```

## Dependência reversa (quem é afetado)

| Módulo central | Utilizado por | Efeito de alteração |
|---|---|---|
| `backend/app/core/config.py` | main, session, storage, worker, integrations, tests | muda defaults, startup, limites e segurança |
| `db/models.py` | session, todos repositories/services, schemas/testes | quebra queries, serialização e migração |
| `db/session.py` | main, routers via Depends, scripts | indisponibilidade impede toda API |
| `api/deps.py` | quase todos routers | muda autenticação e tenant globalmente |
| `storage_service.py` | ingestão, arquivos, certificados, downloads, DANFSe/exports | altera path, R2 e disponibilidade de documentos |
| `storage_naming_service.py` | ingestão, download, certificados, scripts | muda localização lógica de todos os arquivos |
| `legacy_ingestion_service.py` | worker, scripts de reprocessamento/importação | muda identidade/status/valores persistidos |
| `legacy_processing_service.py` | worker real | muda protocolo ADN e ciclo de NSU |
| `notas_service.py` | routers notas/compat, portal, download, relatórios | afeta tela, exportação e conferência |
| `operational_fields_service.py` | ingestão, notas, portal, relatórios | afeta status, prioridade, SLA e alertas |
| `retencoes_*` | ingestão/backfill/relatório | afeta valores e divergências fiscais |
| `notas_download_service.py` | `notas.py`, frontend downloads | afeta ZIP, limites e nomes |
| `portal_support_service.py` | notas/eventos/processos/relatório/empresas | grande raio: DTOs e XLSX |
| `schemas/notas.py` | notas router, relatórios e frontend | alteração quebra payloads GET/POST/PATCH |
| `src/lib/api.ts` | todos hooks/pages frontend | contrato central com backend |

## Contextos que devem ser lidos juntos

### Autenticação

`backend/app/core/config.py`, `backend/app/core/security.py`, `backend/app/core/rate_limit.py`, `backend/app/api/deps.py`, `backend/app/api/routers/auth.py`, `backend/app/services/auth_service.py`, `backend/app/db/models.py::Usuario`, `src/lib/api.ts`, `hooks/useAuth.ts`, `pages/Login.tsx`.

### Certificado/segredo

`routers/certificados.py`, `certificados_service.py`, `certificado_metadata_service.py`, `secrets_service.py`, `storage_service.py`, `storage_naming_service.py`, `models.Certificado/Secret`, `src/lib/api.ts`, componentes de Certificados.

### Processamento ADN

`consultas_service.py`, `processos_service.py`, `worker/jobs.py`, `worker/worker.py`, `worker/scheduler.py`, `legacy_processing_service.py`, `adn_nfse_downloader.py`, `legacy_ingestion_service.py`, `nsu_control_service.py`, `locks_service.py`.

### Nota/conferência

`schemas/notas.py`, `routers/notas.py`, `notas_service.py`, `notas_repo.py`, `operational_fields_service.py`, `retencoes_calculo_service.py`, `portal_support_service.py`, hooks e componentes de Conferência/Notas.

### Documento/storage

`storage_service.py`, `storage_naming_service.py`, `arquivos_service.py`, `routers/arquivos.py`, `notas_download_service.py`, `danfse_service.py`, `backend/danfse/*`, testes de storage/DANFSe.

### Banco/migração

`db/base.py`, `db/models.py`, `db/session.py`, `scripts/db_migration_common.py`, `scripts/migrar_banco.py`, repositories correspondentes, `docker-compose.yml`, `Dockerfile`, testes de migração.

## Matriz arquivo → importados → dependentes → banco/endpoint

| Arquivo | Importa/usa | É usado por | DB | Endpoints |
|---|---|---|---|---|
| `routers/notas.py` | notas service, portal, download, deps | FastAPI/main | notas/eventos/arquivos | `/notas*` |
| `notas_service.py` | notas repo, models, operational | routers/download/portal | lê/escreve notas | `/notas*`, compat |
| `legacy_ingestion_service.py` | XML/parser/storage/fiscal | legacy processing/scripts | notas/eventos/arquivos/nsu | indireto via processos |
| `worker/jobs.py` | locks, repos, legacy processing | worker/main | jobs/processos/logs | indireto |
| `portal_support_service.py` | models/storage/openpyxl/CNPJ | routers notas/processos/relatórios/empresas | lê notas/eventos/arquivos/processos/cache | `/relatorios`, documentos |
| `src/lib/api.ts` | fetch/types | hooks/pages | nenhum local | chama todas as rotas |
