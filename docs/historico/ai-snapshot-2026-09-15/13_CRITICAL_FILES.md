# Arquivos críticos

| Arquivo | Por que é crítico | Dependentes | Cuidados |
|---|---|---|---|
| `backend/app/main.py` | lifecycle, registro de routers, workers e scheduler embutidos | toda API/deploy | startup executa efeitos e tarefas; conferir flags |
| `backend/app/core/config.py` | defaults de banco, storage, segurança, worker, limites e CORS | todos módulos | production validation; nunca commitar segredos |
| `backend/app/db/models.py` | contrato persistido de 16 tabelas | session/repositories/services/scripts | alterar coluna exige migration e backfill |
| `backend/app/db/session.py` | engine e DDL runtime | lifespan/scripts/testes | DDL concorrente e Postgres exigem plano |
| `backend/app/api/deps.py` | JWT, papéis e isolamento de grupo | quase todos routers | falha pode virar vazamento cross-tenant |
| `backend/app/core/security.py` | hash/JWT | login/deps/frontend | preservar compatibilidade de claims e expiração |
| `backend/app/services/legacy_processing_service.py` | ponte para ADN legado | worker real | path/import dinâmico, timeout e cancelamento |
| `adn_nfse_downloader.py` | protocolo e autenticação ADN | legado/scripts | chamadas externas e certificado real |
| `backend/app/services/legacy_ingestion_service.py` | parse/upsert/status/arquivos | worker e reprocessamentos | uma mudança altera todas as notas futuras |
| `backend/app/services/notas_service.py` | filtros, direção, resumo e conferência | routers/download/portal | grande raio e regras implícitas |
| `backend/app/services/operational_fields_service.py` | status fila, prioridade, SLA e Simples | ingestão, telas, relatórios | precedências são regra de negócio |
| `backend/app/services/retencoes_calculo_service.py` | cálculo fiscal Decimal | ingestão/relatório/backfill | não converter para float |
| `backend/app/services/portal_support_service.py` | DTOs, resumo e XLSX | muitas rotas | duas definições de exportação; validar retorno |
| `backend/app/services/storage_service.py` | backend local/R2 e segurança de caminho | documentos/certificados/downloads | preservar chaves e impedir traversal |
| `backend/app/services/storage_naming_service.py` | naming canônico de todos objetos | ingestão/download/certificados | mudança exige migração/reconciliação |
| `backend/app/worker/jobs.py` | claim, lock, retry e finalização | worker/scheduler | testar crash e concorrência |
| `backend/app/schemas/notas.py` | contrato de filtros e retificação | routers/relatórios/frontend | aliases/read-only/validações |
| `backend/app/api/routers/notas.py` | endpoints mais usados e retificação | frontend inteiro | GET/POST têm filtros diferentes |
| `backend/danfse/generate.php` + `backend/danfse/src/*` | PDF oficial | danfse service/frontend | assets/composer/runtime |
| `frontend/src/lib/api.ts` | cliente HTTP central e download | hooks/pages | qualquer rota renomeada quebra vários fluxos |

## Trechos críticos (linhas aproximadas)

- `app/main.py::lifespan` (~170–215): inicialização, migrações e tarefas em background.
- `db/session.py::_ensure_runtime_columns` (~92 em diante): alterações de schema runtime.
- `api/deps.py::get_current_usuario/require_*_grupo` (~41–105): autorização global.
- `consultas_service.py::_create_consulta_job/enqueue_consultas_pendentes` (~182–268): criação e deduplicação de fila.
- `worker/jobs.py::processar_job_consulta_nfse_real` (~141–232): transação, lock e ponte real.
- `legacy_ingestion_service.py::_status_from_xml` (~366–388): status fiscal.
- `legacy_ingestion_service.py::ingerir_saida_legado` (~802–1151): principal fronteira de ingestão.
- `notas_service.py::listar_notas` (~278–388): filtros e classificação de listagem.
- `notas_service.py::atualizar_conferencia` (~710–762): gravação da análise.
- `routers/notas.py::patch_conferencia_nota` (~576–607): bloqueio 409 e retificação.
- `notas_download_service.py::_buscar_notas/gerar_zip_notas` (~148–245): seleção, limite e ZIP.
- `portal_support_service.py::exportar_conferencia_xlsx` (~696 e ~1235): relatório duplicado.
- `retencoes_calculo_service.py::calcular_retencoes_esperadas` (~116–200): cálculo fiscal.
- `storage_service.py` (métodos put/get/delete/list): fronteira de bytes e path.
- `frontend/src/lib/api.ts` (~795 linhas): headers, timeout, erros e todos contratos REST.
