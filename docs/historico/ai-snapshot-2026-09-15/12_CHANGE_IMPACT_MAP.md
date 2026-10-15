# Mapa de impacto: se eu alterar X, o que pode quebrar?

## Autenticação/autorização

**Arquivos:** `backend/app/core/config.py`, `backend/app/core/security.py`, `backend/app/core/rate_limit.py`, `backend/app/api/deps.py`, `backend/app/api/routers/auth.py`, `backend/app/services/auth_service.py`, `backend/app/db/models.py::Usuario/AcessoUsuario`, frontend `src/lib/api.ts`, `hooks/useAuth`, `pages/Login.tsx`.

**Afeta:** todas as rotas JWT, `/auth/me`, Admin, guards do router React, headers de CORS e auditoria de acessos. Verificar expiração, papéis, grupo, usuário inativo, armazenamento do token e testes de 401/403. Nunca alterar algoritmo/hash ou claims sem migração e compatibilidade.

## Empresas/grupos

**Arquivos:** `routers/empresas.py`, `empresas_service.py`, `repositories/empresas_repo.py`, `models.Empresa/Grupo`, `api/deps.py`, `consultas_service.py`, páginas/hooks Empresas e Admin.

**Afeta:** todas as FKs, elegibilidade de certificados, tenant, filtros de notas/processos e scheduler por grupo. Antes de mudar `grupo` ou CNPJ, confira índices, unique, dados existentes e rotas administrativas.

## Certificados e segredos

**Arquivos:** routers/serviços de certificados, `certificado_metadata_service.py`, `secrets_service.py`, `storage_service.py`, `storage_naming_service.py`, `models.Certificado/Secret`, worker/legado, componentes Certificados.

**Afeta:** autenticação ADN, storage de PFX, testes de conexão, consultas automáticas. Verificar tamanho/upload, path, expiração, `SECRETS_KEY`, não logar senha e compatibilidade com jobs já enfileirados.

## Consulta NSU/worker

**Arquivos:** `consultas_service.py`, `nsu_control_service.py`, `processos_service.py`, `locks_service.py`, `worker/jobs.py`, `worker/worker.py`, `worker/scheduler.py`, `legacy_processing_service.py`, `adn_nfse_downloader.py`, `legacy_ingestion_service.py`.

**Afeta:** Processo/Job/Lock/NsuControle, chamadas ADN, notas/eventos/arquivos e consumo de storage. Testar dry-run e real, retry, restart, duas instâncias, NSU retroativo, pausa, PDF, cancelamento e falha parcial.

## Parsing/status de nota

**Arquivos:** `legacy_ingestion_service.py`, `nfse_xml_parser.py`, `models.Nota/Evento`, `operational_fields_service.py`, `retencoes_*`, `pdf_status_service.py`, `notas_service.py`.

**Afeta:** identidade `(empresa,chave)`, status fiscal, emitida/recebida, prioridade, SLA, retenções, comparativo e relatórios. Use fixtures XML de emissão, cancelamento, substituição, sem retenção e namespaces diferentes; não misture status fiscal com fila manual.

## Conferência/retificação

**Arquivos:** `schemas/notas.py`, `routers/notas.py`, `notas_service.py`, `models.Nota`, `operational_fields_service.py`, componentes/hooks de Conferência.

**Afeta:** PATCH `/notas/{id}/conferencia`, 409 de análise existente, precedência manual, alertas read-only, usuário/responsável e dashboards. Qualquer mudança precisa de teste de retificação verdadeira/falsa e de concorrência.

## Filtros/listagem

**Arquivos:** `schemas/notas.py`, `repositories/notas_repo.py`, `notas_service.py`, `portal_support_service.py`, `routers/notas.py`, `src/lib/api.ts`, hooks/pages Notas/Conferência.

**Afeta:** GET `/notas*`, resumo, emitidas/recebidas, GET/POST download e relatório. Conferir aliases, paginação, limite 5.000, ordenação, filtros em SQL versus memória e tenant.

## Download XML/PDF

**Arquivos:** `notas_download_service.py`, `routers/notas.py`, `arquivos.py`, `arquivos_service.py`, `storage_service.py`, `storage_naming_service.py`, `src/lib/api.ts`.

**Afeta:** bytes, nomes ZIP, preferir PDF oficial/espelho, max notas, temporários e recuperação de arquivos ausentes. Testar lote vazio, nome duplicado, chave malformada, arquivo grande e limpeza de temp.

## Retenções/relatório

**Arquivos:** `retencoes_regras_service.py`, `RETENCOES_REGRAS.xlsx`, `retencoes_calculo_service.py`, `portal_support_service.py`, `routers/relatorios.py`.

**Afeta:** valores Decimal, status/alertas, XLSX e CNPJ enriquecido. Fixar versão/checksum da planilha no teste; verificar arredondamento, tolerância e provider externo indisponível.

## Banco/migração

**Arquivos:** `db/models.py`, `db/session.py`, `db/base.py`, `scripts/db_migration_common.py`, `migrar_banco.py`, repositories, Docker e testes.

**Afeta:** criação/startup, produção PostgreSQL, índices, FKs e todas as queries. Faça backup, migration dry-run, compatibilidade retroativa e teste com SQLite e Postgres; não editar apenas `models.py` esperando alteração automática.

## Storage/DANFSe

**Arquivos:** `storage_service.py`, naming, routers/arquivos, `danfse_service.py`, `backend/danfse/*`, componentes de documentos.

**Afeta:** documentos existentes e geração PDF. Preserve chaves antigas, path traversal checks, limites, assets Composer e teste PHP; planeje migração de objetos antes de alterar naming.

## Regra prática antes de qualquer mudança

1. Identificar o contrato HTTP e o consumidor em `src/lib/api.ts`.
2. Ler schema, router, service, repository/model e testes do fluxo.
3. Mapear efeitos DB/storage/worker no documento específico.
4. Escrever teste de regressão e de tenant/erro antes de refatorar.
5. Só então alterar, migrar e validar o conjunto inteiro.
