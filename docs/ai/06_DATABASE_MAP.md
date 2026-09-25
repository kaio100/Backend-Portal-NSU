# Mapa do banco de dados

## Engine e migração

**Desde 2026-09-25 (F2):** `migrate_db()` roda numa transação só, com `pg_advisory_xact_lock` no Postgres (réplicas não disputam DDL): `create_all` → `_ensure_runtime_columns` (CONGELADO, não acrescentar) → Alembic (`backend/app/db/migrations`, `alembic.ini` na raiz). Toda mudança nova de esquema é uma revisão idempotente (helpers `tabela_existe`/`coluna_existe`), porque o banco novo nasce completo pelo `create_all` e o de produção tem sobras da linha de set/2026 (6 tabelas e colunas extras, listadas na `0001_baseline`). Revisões: `0001_baseline`, `0002_historico_conferencia`.

`backend/app/db/session.py` lê `DATABASE_URL`. SQLite usa WAL, `busy_timeout` e `check_same_thread=false`; PostgreSQL usa pool. `init_db()` executa `Base.metadata.create_all` e `_ensure_runtime_columns()` com `ALTER TABLE`/índices idempotentes. `scripts/migrar_banco.py` é o caminho explícito de produção. Alembic está instalado, mas não há `alembic/versions` versionado; o estado real do schema deve ser verificado contra `models.py` e o script de migração antes de deploy.

## Entidades e colunas críticas

| Tabela | Chave/constraints | Colunas de negócio | Relações e uso |
|---|---|---|---|
| `grupos` | `id`; `codigo` unique/index | `codigo`, `nome`, `ativo`, timestamps | administração e isolamento lógico |
| `empresas` | `id`; `cnpj` unique/index | `nome`, `cnpj`, `ambiente`, `ativo`, `grupo` | raiz de certificados, processos, notas, eventos, arquivos, usuários |
| `certificados` | `id`; FK `empresa_id` | `storage_key`, `senha_secret_ref`, thumbprint/CN/validade, `ativo` | credencial do ADN; 1:N processos/jobs/locks |
| `processos` | `id`; FK empresa/certificado | `tipo`, `status`, `nsu_inicio/final`, `limite`, `pausa`, flags PDF, erro e timestamps | execução visível; tem jobs, notas, arquivos e logs |
| `processos_jobs` | `id`; FKs processo/empresa/certificado | status, attempts, lock, available_at, payload, erro | fila reclamada pelo worker |
| `monitoramento_config` | `id`; `grupo` unique | ativo, intervalo, último/próximo ciclo, filtros JSON | scheduler por grupo |
| `nsu_controle` | `id`; unique `(empresa_id, certificado_id)` | CNPJ, último NSU, origem, reconciliação | cursor monotônico por credencial |
| `notas` | `id`; unique `(empresa_id, chave)`; índices empresa+competência/emissão | identidade/NSU, datas, prestador/tomador, valores/retenções, serviço, status, conferência, SLA, chaves de storage, arquivamento | núcleo fiscal; eventos/arquivos e processo |
| `eventos` | `id`; FKs empresa/nota | chave evento/afetada, tipo, descrição, data, XML key, NSU | cancelamento/substituição e histórico fiscal |
| `arquivos` | `id`; FKs empresa/nota/processo | tipo, backend/bucket/key, filename, content-type, tamanho, checksum | índice do storage; download/preview |
| `logs_processos` | `id`; FKs processo/empresa | level, mensagem, contexto JSON, created_at | observabilidade por execução |
| `locks_processamento` | `id`; unique `(empresa_id, certificado_id)` | worker, locked_at, expires_at | exclusão mútua de consulta |
| `cnpj_cache` | PK composta `(cnpj, fonte)` | payload, CNAE, status, erro, consulta/expiração | enriquecimento de relatório |
| `secrets` | `id`; `ref` unique | tipo, `encrypted_value` | senha PFX e outros segredos cifrados |
| `usuarios` | `id`; email unique; FK empresa | email/hash/nome/ativo/grupo/is_admin/papel | autenticação e RBAC |
| `notas_conferencia_historico` | `id`; FKs nota (nula após arquivamento), empresa, usuário (nulo após exclusão) | chave, usuario_nome/email, acao, alteracoes JSON, created_at | histórico imutável da análise fiscal |
| `acessos_usuarios` | `id`; FK usuário | grupo, IP, user-agent, timestamp | auditoria de acessos |

## Campos de `notas` por domínio

- Identidade: `chave`, `numero_nfse`, `primeiro_nsu`, `ultimo_nsu`, `data_emissao`, `competencia`, `entrada`.
- Partes: `prestador_cnpj/nome`, `tomador_cnpj/nome`, `municipio`.
- Valores: `valor_servico`, `valor_base`, `iss`, `irrf`, `inss`, `csrf`, PIS/COFINS/CSLL/outras retenções, descontos e `valor_liquido*`.
- Serviço/fiscal: `codigo_servico*`, `subitem_lc116`, descrição, `aliquota_iss`, `iss_retido`, `valor_iss_retido`, `cnae`, Simples, incidência.
- Operação: `status_documento`, `status_rotulo`, `prioridade*`, `responsavel`, conferência, operador/dispositivo, `status_nota_pdf`, `divergencia`, `status_fila_manual`, `alertas_fiscais`, SLA.
- Armazenamento: `xml_storage_key`, `pdf_oficial_storage_key`, `pdf_espelho_storage_key`, `arquivada*`, `arquivo_backup_storage_key`.

## Mapa tabela → leitura → escrita → exclusão

| Tabela | Lida principalmente por | Escrita/atualização | Exclusão/risco |
|---|---|---|---|
| `empresas` | `deps`, empresas/certificados/consultas/notas/admin | `empresas_service`, routers, scripts | excluir empresa pode deixar storage órfão; confirmar FKs |
| `certificados` | consultas, worker, routers certificados | upload/metadata/secrets/serviço | exclusão não remove automaticamente todos artefatos |
| `processos` | processos, worker, logs, portal | `processos_service`, jobs, legado | arquivamento/limpeza pode perder histórico |
| `processos_jobs` | `jobs_repo`, worker, consultas | enqueue/claim/finalização/cancelamento | retry/claim concorrente; jobs abandonados |
| `monitoramento_config` | scheduler/consultas/admin | consultas_service | configuração por grupo é única |
| `nsu_controle` | NSU/consultas/worker | nsu service/legado | atualização fora de ordem pode retroceder sem proteção externa |
| `notas` | notas_repo/service, relatórios, portal, compat | ingestão, conferência, cálculo, scripts | archive/remove; identidade exige unique por empresa |
| `eventos` | notas/portal/eventos | ingestão | deduplicação depende de chave lógica, sem unique composto |
| `arquivos` | arquivos/portal/download/storage | ingestão/serviços | DB/storage não transacionais; órfãos |
| `logs_processos` | logs/admin/portal | worker/serviço de logs | volume cresce; limpeza deve ser explícita |
| `locks_processamento` | locks/worker | claim/renew/release | lock expirado ou processo morto exige recuperação |
| `cnpj_cache` | relatório/CNPJ | integração/cache | validade/erro podem ficar obsoletos |
| `secrets` | secrets/certificados/worker | cifra/rotação/remover | exposição se chave Fernet perder-se; nunca logar valor |
| `usuarios` | auth/admin/deps | auth/admin/scripts | email globalmente único pode limitar multiempresa |
| `acessos_usuarios` | admin/relatórios de acesso | login middleware/serviço | auditoria sem política de retenção |

## Riscos de integridade

1. `Nota`, `Evento` e `Arquivo` são atualizados em sessões e etapas diferentes; uma falha após storage pode deixar índice incompleto.
2. `eventos` não declara unique composto para chave/tipo; reprocessar o mesmo XML precisa continuar idempotente no serviço.
3. `nsu_controle` é único por empresa/certificado, mas o fallback ao maior NSU de notas cria dependência de dados parcialmente importados.
4. `notas_archive_service` remove linhas e grava manifesto; é operação destrutiva e precisa de backup/reconciliação.
5. Migração runtime concorrente em múltiplos processos pode disputar `ALTER TABLE`/índice; em produção execute uma migração controlada antes de subir réplicas.

