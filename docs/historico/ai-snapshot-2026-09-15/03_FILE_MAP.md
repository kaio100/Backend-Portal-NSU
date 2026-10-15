# Mapa de arquivos

Este é o mapa funcional do snapshot auditado. Diretórios de dependência instalados, caches, `.git`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, builds e binários foram inventariados, mas não são fonte do comportamento e não foram descritos linha a linha.

## Raiz e operação

| Caminho | Responsabilidade / entradas | Saídas e dependentes | Risco |
|---|---|---|---|
| `adn_nfse_downloader.py` | Cliente ADN legado; CNPJ, certificado, NSU e configuração | CSV/XML/PDF; chamado por `legacy_processing_service` | Muito alto: protocolo externo e side effects em disco |
| `README.md` | Instalação, execução e variáveis | Operadores/devops | Médio: pode divergir do código |
| `.env.example`, `.env.docker.example` | Modelo de configuração sem segredos reais | `backend/app/core/config.py`, Docker | Alto se nomes/defaults ficarem desatualizados |
| `.env`, `.env.docker` | Configuração local/segredo; não usar como documentação | runtime | Crítico; nunca versionar ou expor |
| `Dockerfile`, `docker-compose.yml` | Imagem e separação API/worker/scheduler | deploy | Alto: ordem de migração e flags de concorrência |
| `requirements*.txt`, `package-lock.json` | Dependências Python/Node auxiliares | ambientes/CI | Alto por atualização não pinada ou incompatível |
| `RETENCOES_REGRAS.xlsx` | Matriz fiscal lida em runtime | `retencoes_regras_service` | Alto: alteração de planilha altera regra |
| `empresas.example.json` | Exemplo de empresas legadas | scripts/operador | Baixo |
| `data/` | SQLite local, caches e configurações como `consultas_auto.json` | runtime/scripts | Alto: mistura estado com código |
| `storage/`, `saida_adn_nfse/` | Arquivos locais de runtime/saída legada | storage service/ingestão | Crítico: volume e consistência DB-arquivo |

## API e aplicação Python

| Caminho | Responsabilidade principal | Usa / é usado por |
|---|---|---|
| `backend/app/main.py` | Lifespan, routers, CORS, headers, workers embutidos e limpeza de temporários | uvicorn; todos os routers/services |
| `backend/app/core/config.py` | Settings Pydantic, defaults e validações de produção | toda aplicação |
| `backend/app/api/deps.py` | DB/storage dependency, API key, JWT, papéis e tenant | todos os routers protegidos |
| `backend/app/api/routers/*.py` | HTTP. Módulos: `admin`, `arquivos`, `auth`, `certificados`, `cnpj`, `consultas`, `danfse`, `db_health`, `empresas`, `eventos`, `execucoes`, `health`, `logs`, `nfse_compat`, `notas`, `nsu`, `processos`, `relatorios`, `storage` | frontend, scripts, serviços |
| `backend/app/schemas/*.py` | Contratos Pydantic, filtros e respostas | routers/services/frontend |
| `backend/app/db/models.py` | Entidades, índices, FKs e relações | repositories/services/session |
| `backend/app/db/base.py` | Declarative Base/metadata | models/session |
| `backend/app/db/session.py` | Engine, sessões, criação e migração runtime | lifespan/scripts/tests |
| `backend/app/repositories/*.py` | Acesso reutilizável a empresas, certificados, notas, arquivos, jobs, locks, logs, processos, secrets e usuários | services/routers |
| `backend/app/core/security.py` | Hash PBKDF2, JWT e verificação | auth/deps |
| `backend/app/core/rate_limit.py` | Janela deslizante em memória para login | auth router |
| `backend/app/core/observability.py` | Logs JSON, contadores Prometheus e webhook opcional | main/services |
| `backend/app/integrations/*.py` | Cliente CNPJ/Receita/Invertexto e integrações externas | services/relatório |

## Serviços por domínio

| Grupo | Arquivos | Fluxo |
|---|---|---|
| Consulta/NSU | `consultas_service.py`, `nsu_control_service.py`, `processos_service.py`, `locks_service.py` | valida elegibilidade → processo/job → NSU/lock/status |
| Worker/legado | `worker/jobs.py`, `worker/worker.py`, `worker/scheduler.py`, `legacy_processing_service.py`, `legacy_ingestion_service.py` | claim → ADN → parse/upsert → finalização |
| Notas | `notas_service.py`, `notas_download_service.py`, `notas_archive_service.py`, `nfse_xml_parser.py`, `pdf_status_service.py` | classificação, conferência, download e arquivamento |
| Status fiscal | `nfse_status_service.py` | única fonte da decisão nota/evento e do `status_documento` (raiz, cStat, código do evento); ver REG-014 |
| Fiscal | `retencoes_regras_service.py`, `retencoes_calculo_service.py`, `operational_fields_service.py` | regra LC/flags → Decimal → status/alerta |
| Documentos | `storage_service.py`, `storage_naming_service.py`, `arquivos_service.py`, `danfse_service.py` | chave segura → storage → índice ou DANFSe PHP |
| Portal | `portal_support_service.py`, `empresas_service.py`, `certificados_service.py`, `certificado_metadata_service.py`, `secrets_service.py`, `auth_service.py` | suporte às telas, cadastro e relatório |

## Scripts

`backend/app/scripts/` contém scripts operacionais e de manutenção, todos devem ser tratados como comandos com efeito potencial no banco/storage: `migrar_banco.py`, `db_migration_common.py`, `backfill_*`, `recalcular_*`, `reindexar_*`, `verificar_*`, `diagnostico_*`, `limpar_*`, `exportar_*`, `importar_*`, `reprocessar_*`, `testar_*`, `auditar_*`, além dos scripts de limpeza/monitoramento. Antes de executar qualquer script, leia seu `main()` e confirme o `DATABASE_URL`/`STORAGE_ROOT`; não assuma que um nome “verificar” é somente leitura.

## DANFSe PHP

`backend/danfse/generate.php` é o entrypoint chamado pelo Python. `DanfseGenerator.php`, `src/` (DTOs, enums, formatadores, parser XML), `templates/`, `assets/`, `composer.json`, `composer.lock` e `tests/run.php` formam uma unidade: XML entra, DTO é validado/formatado e PDF é produzido. Não remover assets ou atualizar Composer sem executar o teste PHP.

## Testes e CI

`tests/` cobre autenticação, tenant, API, notas, download ZIP, storage, DANFSe, PDF, worker, migração e integrações. `.github/workflows/ci.yml` executa lint/testes Python e teste PHP do DANFSe. Um teste novo deve refletir a fronteira alterada (router/service, persistência, storage e integração frontend quando aplicável).

## Frontend compatível

Repositório irmão `C:/Users/kaio.paula/Downloads/01 - Projetos/frontend_integrado_pronto_rodar/frontend` no commit `0fd4b07`. A árvore `src/` possui `app/router.tsx`, query client/loaders, `components/` (auth, certificados, conferência, dashboard, layout, live, notas, operador, processos e ui), `hooks/`, `lib/api.ts` e `pages/` (Login, CriarConta, Dashboard, Conferencia, Certificados, NotasConsultadas, Fila, Processos, Configuracoes, MotorAdn, Admin). `src/lib/api.ts` é o consumidor central e deve ser lido junto do router backend correspondente.

## Artefatos deliberadamente fora da fonte

`docs/ai.zip` no diretório `docs/` é um arquivo não versionado existente antes desta auditoria. Ele pode conter uma auditoria histórica, mas não substitui os documentos desta pasta. Backups, recovery da limpeza Canopus e caches em `tmp/` são estado operacional e não devem ser importados como código.

## Inventário mecânico dos arquivos versionados

A lista abaixo é a segunda passagem do inventário. Cada caminho foi classificado por seu diretório e, quando há efeito, o mapa acima aponta entradas/saídas/dependentes. Arquivos de dependência externa, fonte binária e exemplo são identificados como tal e não têm análise de lógica Python.

### Raiz/configuração

```text
.dockerignore
.env.docker.example
.env.example
.gitignore
Dockerfile
README.md
RETENCOES_REGRAS.xlsx
adn_nfse_downloader.py
docker-compose.yml
empresas.example.json
package-lock.json
requirements-dev.txt
requirements.txt
```

### API/routers

```text
backend/app/api/routers/__init__.py
backend/app/api/routers/admin.py
backend/app/api/routers/arquivos.py
backend/app/api/routers/auth.py
backend/app/api/routers/certificados.py
backend/app/api/routers/cnpj.py
backend/app/api/routers/consultas.py
backend/app/api/routers/danfse.py
backend/app/api/routers/db_health.py
backend/app/api/routers/empresas.py
backend/app/api/routers/eventos.py
backend/app/api/routers/execucoes.py
backend/app/api/routers/health.py
backend/app/api/routers/logs.py
backend/app/api/routers/nfse_compat.py
backend/app/api/routers/notas.py
backend/app/api/routers/nsu.py
backend/app/api/routers/processos.py
backend/app/api/routers/relatorios.py
backend/app/api/routers/storage.py
```

### Core/DB

```text
backend/app/api/deps.py
backend/app/core/__init__.py
backend/app/core/config.py
backend/app/core/observability.py
backend/app/core/rate_limit.py
backend/app/core/security.py
backend/app/db/__init__.py
backend/app/db/base.py
backend/app/db/models.py
backend/app/db/session.py
backend/app/main.py
```

### Repositories

```text
backend/app/repositories/__init__.py
backend/app/repositories/arquivos_repo.py
backend/app/repositories/certificados_repo.py
backend/app/repositories/empresas_repo.py
backend/app/repositories/jobs_repo.py
backend/app/repositories/locks_repo.py
backend/app/repositories/logs_repo.py
backend/app/repositories/notas_repo.py
backend/app/repositories/processos_repo.py
backend/app/repositories/secrets_repo.py
backend/app/repositories/usuarios_repo.py
```

### Schemas

```text
backend/app/schemas/__init__.py
backend/app/schemas/arquivos.py
backend/app/schemas/auth.py
backend/app/schemas/certificados.py
backend/app/schemas/consultas.py
backend/app/schemas/empresas.py
backend/app/schemas/jobs.py
backend/app/schemas/notas.py
backend/app/schemas/processos.py
backend/app/schemas/secrets.py
backend/app/schemas/usuarios.py
```

### Services

```text
backend/app/services/__init__.py
backend/app/services/arquivos_service.py
backend/app/services/auth_service.py
backend/app/services/certificado_metadata_service.py
backend/app/services/certificados_service.py
backend/app/services/cnpj_cache_service.py
backend/app/services/cnpj_enrichment_service.py
backend/app/services/cnpj_receita_service.py
backend/app/services/consultas_service.py
backend/app/services/danfse_service.py
backend/app/services/empresas_service.py
backend/app/services/legacy_adapter.py
backend/app/services/legacy_ingestion_service.py
backend/app/services/legacy_processing_service.py
backend/app/services/locks_service.py
backend/app/services/logs_service.py
backend/app/services/nfse_xml_parser.py
backend/app/services/notas_archive_service.py
backend/app/services/notas_download_service.py
backend/app/services/notas_service.py
backend/app/services/nsu_control_service.py
backend/app/services/operational_fields_service.py
backend/app/services/pdf_status_service.py
backend/app/services/portal_support_service.py
backend/app/services/processos_service.py
backend/app/services/retencoes_calculo_service.py
backend/app/services/retencoes_regras_service.py
backend/app/services/secrets_service.py
backend/app/services/storage_naming_service.py
backend/app/services/storage_service.py
backend/app/services/valor_liquido_backfill_service.py
```

### Scripts

```text
backend/app/scripts/__init__.py
backend/app/scripts/aplicar_seguranca_rls.py
backend/app/scripts/arquivar_notas_antigas.py
backend/app/scripts/auditar_incidencia_iss.py
backend/app/scripts/auditar_integridade_certificados.py
backend/app/scripts/auditar_rls_supabase.py
backend/app/scripts/backup_supabase_nfse.ps1
backend/app/scripts/baixar_pdfs_oficiais_periodo.py
backend/app/scripts/corrigir_integridade_certificados.py
backend/app/scripts/corrigir_simples_pendentes_online.py
backend/app/scripts/db_migration_common.py
backend/app/scripts/diagnosticar_banco.py
backend/app/scripts/diagnosticar_empresas_nsu_202608.py
backend/app/scripts/diagnosticar_filtro_monitor_202608.py
backend/app/scripts/diagnosticar_imperatriz_online.py
backend/app/scripts/diagnosticar_motor_e_arquivos_202608.py
backend/app/scripts/diagnosticar_notas_faltantes_202608.py
backend/app/scripts/diagnosticar_nsu_certificado.py
backend/app/scripts/enfileirar_reprocessamento_certificados.py
backend/app/scripts/gerar_apresentacao_resultados.py
backend/app/scripts/gerar_espelhos_ausentes.py
backend/app/scripts/importar_base_cnpj_receita.py
backend/app/scripts/listar_consultas_simples_pendentes.py
backend/app/scripts/melhorar_apresentacao_resultados.py
backend/app/scripts/migrar_banco.py
backend/app/scripts/migrar_rbac.py
backend/app/scripts/migrar_sqlite_para_postgres.py
backend/app/scripts/migrar_storage_para_r2.py
backend/app/scripts/promover_usuarios_locais.py
backend/app/scripts/r2_common.py
backend/app/scripts/recalcular_alertas_fiscais.py
backend/app/scripts/reconciliar_notas_certificados.py
backend/app/scripts/reconciliar_storage.py
backend/app/scripts/regenerar_carimbos_pdfs.py
backend/app/scripts/regenerar_espelhos_competencia.py
backend/app/scripts/restaurar_monitor_global_202608.py
backend/app/scripts/revalidar_status_pdfs.py
backend/app/scripts/sincronizar_cnpjs_portal.py
backend/app/scripts/status_reprocessamento_certificados.py
backend/app/scripts/testar_r2.py
backend/app/scripts/validar_migracao_postgres.py
```

### Worker

```text
backend/app/worker/__init__.py
backend/app/worker/jobs.py
backend/app/worker/scheduler.py
backend/app/worker/worker.py
```

### DANFSe PHP

```text
backend/danfse/README.md
backend/danfse/assets/fonts/ttf/arial-bold.ttf
backend/danfse/assets/fonts/ttf/arial.ttf
backend/danfse/assets/fonts/ttf/ms-sans-serif.ttf
backend/danfse/assets/logos/nfse.png
backend/danfse/assets/xml/teste.xml
backend/danfse/composer.json
backend/danfse/composer.lock
backend/danfse/generate.php
backend/danfse/src/Danfse/Config/DanfseConfig.php
backend/danfse/src/Danfse/Config/MunicipalityBranding.php
backend/danfse/src/Danfse/DanfseGenerator.php
backend/danfse/src/Danfse/Data/Municipios.php
backend/danfse/src/Danfse/Dto/AtvEvento.php
backend/danfse/src/Danfse/Dto/CServ.php
backend/danfse/src/Danfse/Dto/Destinatario.php
backend/danfse/src/Danfse/Dto/Dps.php
backend/danfse/src/Danfse/Dto/DpsIBSCBS.php
backend/danfse/src/Danfse/Dto/DpsIBSCBSTrib.php
backend/danfse/src/Danfse/Dto/DpsIBSCBSValores.php
backend/danfse/src/Danfse/Dto/Emitente.php
backend/danfse/src/Danfse/Dto/Endereco.php
backend/danfse/src/Danfse/Dto/EnderecoEmitente.php
backend/danfse/src/Danfse/Dto/EnderecoExterior.php
backend/danfse/src/Danfse/Dto/EnderecoNacional.php
backend/danfse/src/Danfse/Dto/GCBSTot.php
backend/danfse/src/Danfse/Dto/GIBSMunTot.php
backend/danfse/src/Danfse/Dto/GIBSTot.php
backend/danfse/src/Danfse/Dto/GIBSUFTot.php
backend/danfse/src/Danfse/Dto/GItemPed.php
backend/danfse/src/Danfse/Dto/GibsCbs.php
backend/danfse/src/Danfse/Dto/IBSCBS.php
backend/danfse/src/Danfse/Dto/IBSCBSFed.php
backend/danfse/src/Danfse/Dto/IBSCBSMun.php
backend/danfse/src/Danfse/Dto/IBSCBSUf.php
backend/danfse/src/Danfse/Dto/IBSCBSValores.php
backend/danfse/src/Danfse/Dto/Imovel.php
backend/danfse/src/Danfse/Dto/InfDPS.php
backend/danfse/src/Danfse/Dto/InfNFSe.php
backend/danfse/src/Danfse/Dto/InfoCompl.php
backend/danfse/src/Danfse/Dto/Intermediario.php
backend/danfse/src/Danfse/Dto/LocPrest.php
backend/danfse/src/Danfse/Dto/NFSe.php
backend/danfse/src/Danfse/Dto/Obra.php
backend/danfse/src/Danfse/Dto/PisCofins.php
backend/danfse/src/Danfse/Dto/Prestador.php
backend/danfse/src/Danfse/Dto/RegTrib.php
backend/danfse/src/Danfse/Dto/Servico.php
backend/danfse/src/Danfse/Dto/Subst.php
backend/danfse/src/Danfse/Dto/Tomador.php
backend/danfse/src/Danfse/Dto/TotCIBS.php
backend/danfse/src/Danfse/Dto/TotTrib.php
backend/danfse/src/Danfse/Dto/TotTribPercent.php
backend/danfse/src/Danfse/Dto/TotTribValues.php
backend/danfse/src/Danfse/Dto/TribFederal.php
backend/danfse/src/Danfse/Dto/TribMunicipal.php
backend/danfse/src/Danfse/Dto/Tributacao.php
backend/danfse/src/Danfse/Dto/VServPrest.php
backend/danfse/src/Danfse/Dto/Valores.php
backend/danfse/src/Danfse/Dto/ValoresNFSe.php
backend/danfse/src/Danfse/Enums/OpSimpNac.php
backend/danfse/src/Danfse/Enums/RegApTribSN.php
backend/danfse/src/Danfse/Enums/RegEspTrib.php
backend/danfse/src/Danfse/Enums/TipoAmbiente.php
backend/danfse/src/Danfse/Enums/TpRetISSQN.php
backend/danfse/src/Danfse/Enums/TribISSQN.php
backend/danfse/src/Danfse/Exception/InvalidXmlException.php
backend/danfse/src/Danfse/Exception/NfseException.php
backend/danfse/src/Danfse/Formatter.php
backend/danfse/src/Danfse/Template/DanfseTemplate.php
backend/danfse/src/Danfse/Template/danfse.php
backend/danfse/src/Danfse/XmlToArray.php
backend/danfse/tests/run.php
```
+
## Inventário do frontend compatível (`src/`)

Os 83 arquivos TypeScript/TSX do repositório irmão foram conferidos no commit `0fd4b07`. `api.ts`/hooks têm efeitos HTTP; componentes e pages consomem esses hooks; `ui`/CSS são apresentação; testes `*.test.ts` validam utilitários/contrato local.

```text
src/app/page-loaders.ts
src/app/query-client.ts
src/app/router.tsx
src/components/auth/ProtectedRoute.tsx
src/components/certificados/CertificadoExpiryTicker.tsx
src/components/certificados/CertificadoUploadForm.tsx
src/components/conferencia/ConferenciaDrawer.tsx
src/components/conferencia/ConferenciaFilters.tsx
src/components/conferencia/ConferenciaMobileCard.tsx
src/components/conferencia/ConferenciaTable.tsx
src/components/conferencia/conferenciaUtils.ts
src/components/dashboard/QuickTasks.tsx
src/components/layout/AppLayout.tsx
src/components/layout/CommandPalette.tsx
src/components/layout/FocusModeButton.tsx
src/components/layout/OnboardingTour.tsx
src/components/layout/Sidebar.tsx
src/components/layout/Topbar.tsx
src/components/live/CycleSummary.tsx
src/components/live/LiveStatusBar.tsx
src/components/live/StartConsultasButton.tsx
src/components/notas/NotaDetailSections.tsx
src/components/notas/NotaDrawer.tsx
src/components/notas/NotaMobileCard.tsx
src/components/notas/NotasDownloadActions.tsx
src/components/notas/NotasFilterPanel.tsx
src/components/notas/NotasTable.tsx
src/components/operator/OperatorGate.tsx
src/components/operator/OperatorNameModal.tsx
src/components/processos/ProcessoDrawer.tsx
src/components/ui/AppErrorBoundary.tsx
src/components/ui/Badge.tsx
src/components/ui/Button.tsx
src/components/ui/Card.tsx
src/components/ui/ConfirmDialog.tsx
src/components/ui/Drawer.tsx
src/components/ui/EmptyState.tsx
src/components/ui/FilterChips.tsx
src/components/ui/InfiniteScrollSentinel.tsx
src/components/ui/PageHeader.tsx
src/components/ui/ResizableDataTable.tsx
src/components/ui/SavedViews.tsx
src/components/ui/Skeleton.tsx
src/components/ui/Toaster.tsx
src/hooks/queryInvalidation.ts
src/hooks/useAuth.tsx
src/hooks/useCertificados.ts
src/hooks/useConferenciaNotas.ts
src/hooks/useElementWidth.ts
src/hooks/useEmpresas.ts
src/hooks/useFocusMode.tsx
src/hooks/useHealth.ts
src/hooks/useLiveStatus.ts
src/hooks/useNotas.ts
src/hooks/useNotasDownload.ts
src/hooks/useNotasTotals.ts
src/hooks/useOperator.tsx
src/hooks/usePersistentState.ts
src/hooks/useProcessos.ts
src/hooks/useTheme.ts
src/lib/api.test.ts
src/lib/api.ts
src/lib/auth-storage.ts
src/lib/config.ts
src/lib/format.ts
src/lib/incidenciaSearch.test.ts
src/lib/notaFilters.ts
src/lib/operator.ts
src/lib/smartSearch.ts
src/main.tsx
src/pages/Admin.css
src/pages/Admin.tsx
src/pages/AdminArchive.css
src/pages/Certificados.tsx
src/pages/Conferencia.tsx
src/pages/Configuracoes.tsx
src/pages/CriarConta.tsx
src/pages/Dashboard.tsx
src/pages/Fila.tsx
src/pages/Login.tsx
src/pages/MotorAdn.tsx
src/pages/NotasConsultadas.tsx
src/pages/Processos.tsx
src/styles.css
src/types/api.ts
src/vite-env.d.ts
```


### Documentação

```text
docs/DEPLOY_PRODUCAO.md
docs/PENDENCIAS_BACKEND_PORTAL.md
```

### Testes

```text
tests/conftest.py
tests/test_adn_data_cutoff.py
tests/test_auth_account.py
tests/test_certificados_contagem.py
tests/test_cnpj_receita.py
tests/test_cnpj_receita_cache.py
tests/test_consultas_api.py
tests/test_correcao_analise_fiscal.py
tests/test_cors.py
tests/test_danfse_integration.py
tests/test_danfse_nacional_service.py
tests/test_db_migration_scripts.py
tests/test_db_startup.py
tests/test_http_security.py
tests/test_incidencia_search.py
tests/test_legacy_log_privacy.py
tests/test_legacy_pdf_pause.py
tests/test_logs_security.py
tests/test_nfse_xml_parser.py
tests/test_notas_archive_service.py
tests/test_notas_download_lote.py
tests/test_notas_recentes.py
tests/test_notas_tipo_direcao.py
tests/test_operational_fields.py
tests/test_pdf_status_service.py
tests/test_portal_support_endpoints.py
tests/test_prestador_pessoa_fisica.py
tests/test_rbac.py
tests/test_retencoes_regras.py
tests/test_security_config.py
tests/test_sincronizar_cnpjs_portal.py
tests/test_storage_r2.py
```

### Outros backend

```text
backend/app/__init__.py
backend/app/api/__init__.py
backend/app/api/deps.py
backend/app/api/routers/__init__.py
backend/app/api/routers/admin.py
backend/app/api/routers/arquivos.py
backend/app/api/routers/auth.py
backend/app/api/routers/certificados.py
backend/app/api/routers/cnpj.py
backend/app/api/routers/consultas.py
backend/app/api/routers/danfse.py
backend/app/api/routers/db_health.py
backend/app/api/routers/empresas.py
backend/app/api/routers/eventos.py
backend/app/api/routers/execucoes.py
backend/app/api/routers/health.py
backend/app/api/routers/logs.py
backend/app/api/routers/nfse_compat.py
backend/app/api/routers/notas.py
backend/app/api/routers/nsu.py
backend/app/api/routers/processos.py
backend/app/api/routers/relatorios.py
backend/app/api/routers/storage.py
backend/app/backup_supabase/roles.sql
backend/app/core/__init__.py
backend/app/core/config.py
backend/app/core/observability.py
backend/app/core/rate_limit.py
backend/app/core/security.py
backend/app/db/__init__.py
backend/app/db/base.py
backend/app/db/models.py
backend/app/db/session.py
backend/app/main.py
backend/app/repositories/__init__.py
backend/app/repositories/arquivos_repo.py
backend/app/repositories/certificados_repo.py
backend/app/repositories/empresas_repo.py
backend/app/repositories/jobs_repo.py
backend/app/repositories/locks_repo.py
backend/app/repositories/logs_repo.py
backend/app/repositories/notas_repo.py
backend/app/repositories/processos_repo.py
backend/app/repositories/secrets_repo.py
backend/app/repositories/usuarios_repo.py
backend/app/schemas/__init__.py
backend/app/schemas/arquivos.py
backend/app/schemas/auth.py
backend/app/schemas/certificados.py
backend/app/schemas/consultas.py
backend/app/schemas/empresas.py
backend/app/schemas/jobs.py
backend/app/schemas/notas.py
backend/app/schemas/processos.py
backend/app/schemas/secrets.py
backend/app/schemas/usuarios.py
backend/app/scripts/__init__.py
backend/app/scripts/aplicar_seguranca_rls.py
backend/app/scripts/arquivar_notas_antigas.py
backend/app/scripts/auditar_incidencia_iss.py
backend/app/scripts/auditar_integridade_certificados.py
backend/app/scripts/auditar_rls_supabase.py
backend/app/scripts/backup_supabase_nfse.ps1
backend/app/scripts/baixar_pdfs_oficiais_periodo.py
backend/app/scripts/corrigir_integridade_certificados.py
backend/app/scripts/corrigir_simples_pendentes_online.py
backend/app/scripts/db_migration_common.py
backend/app/scripts/diagnosticar_banco.py
backend/app/scripts/diagnosticar_empresas_nsu_202608.py
backend/app/scripts/diagnosticar_filtro_monitor_202608.py
backend/app/scripts/diagnosticar_imperatriz_online.py
backend/app/scripts/diagnosticar_motor_e_arquivos_202608.py
backend/app/scripts/diagnosticar_notas_faltantes_202608.py
backend/app/scripts/diagnosticar_nsu_certificado.py
backend/app/scripts/enfileirar_reprocessamento_certificados.py
backend/app/scripts/gerar_apresentacao_resultados.py
backend/app/scripts/gerar_espelhos_ausentes.py
backend/app/scripts/importar_base_cnpj_receita.py
backend/app/scripts/listar_consultas_simples_pendentes.py
backend/app/scripts/melhorar_apresentacao_resultados.py
backend/app/scripts/migrar_banco.py
backend/app/scripts/migrar_rbac.py
backend/app/scripts/migrar_sqlite_para_postgres.py
backend/app/scripts/migrar_storage_para_r2.py
backend/app/scripts/promover_usuarios_locais.py
backend/app/scripts/r2_common.py
backend/app/scripts/recalcular_alertas_fiscais.py
backend/app/scripts/reconciliar_notas_certificados.py
backend/app/scripts/reconciliar_storage.py
backend/app/scripts/regenerar_carimbos_pdfs.py
backend/app/scripts/regenerar_espelhos_competencia.py
backend/app/scripts/restaurar_monitor_global_202608.py
backend/app/scripts/revalidar_status_pdfs.py
backend/app/scripts/sincronizar_cnpjs_portal.py
backend/app/scripts/status_reprocessamento_certificados.py
backend/app/scripts/testar_r2.py
backend/app/scripts/validar_migracao_postgres.py
backend/app/services/__init__.py
backend/app/services/arquivos_service.py
backend/app/services/auth_service.py
backend/app/services/certificado_metadata_service.py
backend/app/services/certificados_service.py
backend/app/services/cnpj_cache_service.py
backend/app/services/cnpj_enrichment_service.py
backend/app/services/cnpj_receita_service.py
backend/app/services/consultas_service.py
backend/app/services/danfse_service.py
backend/app/services/empresas_service.py
backend/app/services/legacy_adapter.py
backend/app/services/legacy_ingestion_service.py
backend/app/services/legacy_processing_service.py
backend/app/services/locks_service.py
backend/app/services/logs_service.py
backend/app/services/nfse_xml_parser.py
backend/app/services/notas_archive_service.py
backend/app/services/notas_download_service.py
backend/app/services/notas_service.py
backend/app/services/nsu_control_service.py
backend/app/services/operational_fields_service.py
backend/app/services/pdf_status_service.py
backend/app/services/portal_support_service.py
backend/app/services/processos_service.py
backend/app/services/retencoes_calculo_service.py
backend/app/services/retencoes_regras_service.py
backend/app/services/secrets_service.py
backend/app/services/storage_naming_service.py
backend/app/services/storage_service.py
backend/app/services/valor_liquido_backfill_service.py
backend/app/worker/__init__.py
backend/app/worker/jobs.py
backend/app/worker/scheduler.py
backend/app/worker/worker.py
backend/danfse/README.md
backend/danfse/assets/fonts/ttf/arial-bold.ttf
backend/danfse/assets/fonts/ttf/arial.ttf
backend/danfse/assets/fonts/ttf/ms-sans-serif.ttf
backend/danfse/assets/logos/nfse.png
backend/danfse/assets/xml/teste.xml
backend/danfse/composer.json
backend/danfse/composer.lock
backend/danfse/generate.php
backend/danfse/src/Danfse/Config/DanfseConfig.php
backend/danfse/src/Danfse/Config/MunicipalityBranding.php
backend/danfse/src/Danfse/DanfseGenerator.php
backend/danfse/src/Danfse/Data/Municipios.php
backend/danfse/src/Danfse/Dto/AtvEvento.php
backend/danfse/src/Danfse/Dto/CServ.php
backend/danfse/src/Danfse/Dto/Destinatario.php
backend/danfse/src/Danfse/Dto/Dps.php
backend/danfse/src/Danfse/Dto/DpsIBSCBS.php
backend/danfse/src/Danfse/Dto/DpsIBSCBSTrib.php
backend/danfse/src/Danfse/Dto/DpsIBSCBSValores.php
backend/danfse/src/Danfse/Dto/Emitente.php
backend/danfse/src/Danfse/Dto/Endereco.php
backend/danfse/src/Danfse/Dto/EnderecoEmitente.php
backend/danfse/src/Danfse/Dto/EnderecoExterior.php
backend/danfse/src/Danfse/Dto/EnderecoNacional.php
backend/danfse/src/Danfse/Dto/GCBSTot.php
backend/danfse/src/Danfse/Dto/GIBSMunTot.php
backend/danfse/src/Danfse/Dto/GIBSTot.php
backend/danfse/src/Danfse/Dto/GIBSUFTot.php
backend/danfse/src/Danfse/Dto/GItemPed.php
backend/danfse/src/Danfse/Dto/GibsCbs.php
backend/danfse/src/Danfse/Dto/IBSCBS.php
backend/danfse/src/Danfse/Dto/IBSCBSFed.php
backend/danfse/src/Danfse/Dto/IBSCBSMun.php
backend/danfse/src/Danfse/Dto/IBSCBSUf.php
backend/danfse/src/Danfse/Dto/IBSCBSValores.php
backend/danfse/src/Danfse/Dto/Imovel.php
backend/danfse/src/Danfse/Dto/InfDPS.php
backend/danfse/src/Danfse/Dto/InfNFSe.php
backend/danfse/src/Danfse/Dto/InfoCompl.php
backend/danfse/src/Danfse/Dto/Intermediario.php
backend/danfse/src/Danfse/Dto/LocPrest.php
backend/danfse/src/Danfse/Dto/NFSe.php
backend/danfse/src/Danfse/Dto/Obra.php
backend/danfse/src/Danfse/Dto/PisCofins.php
backend/danfse/src/Danfse/Dto/Prestador.php
backend/danfse/src/Danfse/Dto/RegTrib.php
backend/danfse/src/Danfse/Dto/Servico.php
backend/danfse/src/Danfse/Dto/Subst.php
backend/danfse/src/Danfse/Dto/Tomador.php
backend/danfse/src/Danfse/Dto/TotCIBS.php
backend/danfse/src/Danfse/Dto/TotTrib.php
backend/danfse/src/Danfse/Dto/TotTribPercent.php
backend/danfse/src/Danfse/Dto/TotTribValues.php
backend/danfse/src/Danfse/Dto/TribFederal.php
backend/danfse/src/Danfse/Dto/TribMunicipal.php
backend/danfse/src/Danfse/Dto/Tributacao.php
backend/danfse/src/Danfse/Dto/VServPrest.php
backend/danfse/src/Danfse/Dto/Valores.php
backend/danfse/src/Danfse/Dto/ValoresNFSe.php
backend/danfse/src/Danfse/Enums/OpSimpNac.php
backend/danfse/src/Danfse/Enums/RegApTribSN.php
backend/danfse/src/Danfse/Enums/RegEspTrib.php
backend/danfse/src/Danfse/Enums/TipoAmbiente.php
backend/danfse/src/Danfse/Enums/TpRetISSQN.php
backend/danfse/src/Danfse/Enums/TribISSQN.php
backend/danfse/src/Danfse/Exception/InvalidXmlException.php
backend/danfse/src/Danfse/Exception/NfseException.php
backend/danfse/src/Danfse/Formatter.php
backend/danfse/src/Danfse/Template/DanfseTemplate.php
backend/danfse/src/Danfse/Template/danfse.php
backend/danfse/src/Danfse/XmlToArray.php
backend/danfse/tests/run.php
```
