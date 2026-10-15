# Impacto de mudança: se eu alterar X, o que pode quebrar?

> Verificado contra o código em 08/10/2026, commit `a0cfbaf4`. Linhas exatas: `gerado/SIMBOLOS.md`.

## Arquivos críticos

| Arquivo | Por que é crítico | Cuidado |
|---|---|---|
| `backend/app/main.py` | Sobe API, workers por grupo, supervisor e agendador no mesmo processo | Toda tarefa em background precisa de `try/except` e de quem a recrie (ARCH-001) |
| `backend/app/core/config.py` | Padrões de tudo; valida segredos em produção | `worker_dry_run=True` e `api_worker_enabled=True` são padrões perigosos se a variável sumir |
| `backend/app/db/models.py` | Contrato persistido (20 tabelas) | Coluna nova = revisão Alembic idempotente |
| `backend/app/db/session.py` | Engine, pool e `migrate_db` | `_ensure_runtime_columns` congelado |
| `backend/app/api/deps.py` | JWT, papéis e filtro por grupo | Falha aqui = vazamento entre equipes |
| `backend/app/worker/jobs.py` + `repositories/jobs_repo.py` + `locks_repo.py` + `services/job_lease_service.py` | Claim, lock, heartbeat, recuperação | Ordem de UPDATE (ARCH-003); devolução sem espera (ARCH-010) |
| `backend/app/services/consultas_service.py` | Elegibilidade, monitor, criação de processos | Filtros do monitor (REG-039) |
| `backend/app/services/nsu_control_service.py` | De onde a consulta parte | Pular NSU = nota que nunca chega (ARCH-005) |
| `backend/app/services/legacy_processing_service.py` | Ponte com o motor, ingestão incremental, NSU final | Threads e sessões em paralelo |
| `adn_nfse_downloader.py` | Protocolo ADN, retry, gravação em disco | Carregado de novo a cada job (`importlib`); timestamps sem fuso |
| `backend/app/services/legacy_ingestion_service.py` | Upsert de nota/evento, retenções, PDF, storage | Mudança vale para todas as notas futuras e para as releituras |
| `backend/app/services/nfse_status_service.py` | Status fiscal (`classificar_xml`) | REG-014; testes com XML reais |
| `backend/app/services/notas_service.py` | Listagem, direção, exportação, conferência | Rota mais lenta do sistema (ARCH-002) |
| `backend/app/services/operational_fields_service.py` | Fila, prioridade, SLA, Simples | Precedências são regra de negócio |
| `backend/app/services/retencoes_calculo_service.py` + `retencoes_regras_service.py` + `RETENCOES_REGRAS.xlsx` | Cálculo fiscal em Decimal | Qual planilha vale em produção (ARCH-018) |
| `backend/app/services/portal_support_service.py` | DTOs, resumos, XLSX (uma definição de `exportar_conferencia_xlsx`, linha ~1413) | 1.453 linhas; muitas rotas dependem |
| `backend/app/services/storage_service.py` | Local/R2, proteção de caminho, `build_*_key` | Mudar nome de chave exige migrar objetos |
| `backend/app/schemas/notas.py` | Filtros, aliases, campos somente leitura, `retificar` | GET e POST de download dependem do mesmo schema |
| `backend/danfse/` (`generate.php`, `src/`) | PDF espelho | Assets, Composer, PHP 8.1+ |

## Por área

### Autenticação e autorização
**Arquivos:** `core/security.py`, `core/rate_limit.py`, `core/rede.py`, `api/deps.py`, `routers/auth.py`, `services/auth_service.py`, `services/contas_service.py`, `models.Usuario/AcessoUsuario/ConviteCadastro/*Token`.
**Afeta:** todas as rotas, o frontend (`useAuth`, `api.ts`) e as sessões abertas. Mudar claims, algoritmo ou `JWT_SECRET` derruba todos os logins e invalida códigos de e-mail pendentes (o HMAC usa `JWT_SECRET`). Testar 401/403/404 entre grupos **sem** o admin automático do `conftest.py` (ARCH-016).

### Grupos e empresas
**Arquivos:** `routers/admin.py`, `routers/empresas.py`, `empresas_service.py`, `models.Grupo/Empresa`, `deps.py`, `consultas_service.py`, `main._worker_groups`.
**Afeta:** filtros de tudo, workers por grupo (grupo novo ganha worker em até 60 s), monitor por grupo. CNPJ é único globalmente.

### Certificados e segredos
**Arquivos:** `routers/certificados.py`, `certificados_service.py`, `certificado_metadata_service.py`, `secrets_service.py`, `storage_service.build_certificado_key`, `scripts/rotacionar_segredos.py`.
**Afeta:** a consulta ao ADN (sem senha legível o certificado some da fila com log de erro). Trocar a `SECRETS_KEY`: coloque a chave nova na frente da lista, rode `rotacionar_segredos --aplicar` e só depois remova a antiga.

### Consulta NSU e worker
**Arquivos:** `consultas_service.py`, `nsu_control_service.py`, `processos_service.py`, `worker/*`, `jobs_repo.py`, `locks_repo.py`, `job_lease_service.py`, `legacy_processing_service.py`, `adn_nfse_downloader.py`, `main.py`.
**Afeta:** completude da coleta, carga no pool de conexões, disco do volume. Testar: exceção no agendador, dois workers, lock ocupado, cancelamento no meio, falha de ingestão com mais de 20 avisos, reinício no meio do job, NSU informado manualmente, releitura.

### Ingestão, parsing e status
**Arquivos:** `legacy_ingestion_service.py`, `nfse_status_service.py`, `nfse_xml_parser.py`, `operational_fields_service.py`, `retencoes_*`, `danfse_service.py`, `models.Nota/Evento/Arquivo`.
**Afeta:** todas as notas novas e as releituras (`notas_inalteradas` depende de checksum, NSU e arquivos). Use `tests/fixtures/nfse_reais`. Dados já gravados com regra antiga precisam de script com simulação (`scripts/corrigir_status_fiscal`, `recalcular_alertas_fiscais`).

### Conferência e retificação
**Arquivos:** `schemas/notas.py`, `routers/notas.py`, `routers/nfse_compat.py`, `notas_service.salvar_conferencia`, `models.ConferenciaHistorico`.
**Afeta:** 409 sem `retificar`, histórico e telas de conferência. Os dois contratos (`PATCH /notas/{id}/conferencia` e `PUT /nfse/{id}`) precisam da mesma regra.

### Listagem, filtros e exportação
**Arquivos:** `notas_repo.py`, `notas_service.py` (`listar_notas`, `iterar_notas`, `buscar_notas_exportacao`), `notas_download_service.py`, `portal_support_service.py`, `routers/notas.py`, `routers/relatorios.py`.
**Afeta:** desempenho com o worker rodando (pool de 15 conexões), limites 10.000/20.000, exclusão de canceladas (REG-036). Medir o tempo com dados reais antes e depois.

### Banco e migração
**Arquivos:** `models.py`, `session.py`, `migrations/`, `scripts/migrar_banco.py`, `scripts/db_migration_common.py`, `tests/test_db_migration_scripts.py`.
**Afeta:** o deploy inteiro (o `CMD` migra antes de subir). Revisão idempotente, testada em SQLite **e** Postgres; backup antes.

### Storage e DANFSe
**Arquivos:** `storage_service.py`, `storage_naming_service.py`, `routers/arquivos.py`, `arquivos_service.py`, `danfse_service.py`, `backend/danfse/*`, scripts `regenerar_*`, `gerar_espelhos_ausentes`, `reconciliar_storage`, `limpar_orfaos_storage`.
**Afeta:** documentos já gravados (chaves antigas precisam continuar válidas). PDFs já armazenados não são regerados por mudança de layout (decisão de 06/10).

## Antes de qualquer mudança

1. Ache o contrato HTTP e o consumidor (`gerado/ROTAS.md`, frontend `src/lib/api.ts`).
2. Leia router → schema → service → repository/model → testes do fluxo.
3. Liste os efeitos em banco, storage, worker e processo (este arquivo).
4. Escreva o teste de regressão (incluindo grupo e papel) antes de mexer.
5. Altere, rode a suíte, atualize os docs (`00_LEIA_PRIMEIRO.md` → "Como manter") e o `CHANGELOG.md`.
