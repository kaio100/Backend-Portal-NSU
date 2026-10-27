# Banco de dados

> Verificado contra `backend/app/db/models.py`, `session.py` e `migrations/` em 08/10/2026, commit `a0cfbaf4`. O banco de produção **não** foi consultado nesta data (conector Supabase sem acesso); as linhas sobre produção vêm da revisão `0001_baseline` e das verificações de 25/09 e 06/10.

## Engine e conexão

- `DATABASE_URL`: em produção é o Postgres do Supabase (`postgresql://` é convertido para `postgresql+psycopg://`). Local e testes usam SQLite (`data/nfse_backend.db`, `data/test_suite.db`).
- Postgres: `pool_pre_ping`, `pool_size`/`max_overflow`/`pool_timeout`/`pool_recycle` vindos do ambiente. **Produção: 5 + 10**, timeout de 30 s (log de 08/10). A API e todas as threads do worker dividem esse pool (ARCH-002).
- SQLite: WAL, `busy_timeout` de 60 s, `executar_escrita_com_retry` e `renovar_snapshot` para concorrência local. `sqlite_write_lock` não faz nada (mantido por compatibilidade).
- **O SQLite não aplica chaves estrangeiras** (sem `PRAGMA foreign_keys=ON`): testes passam em casos que falham no Postgres (ARCH-006).

## Migração

`migrate_db()` (chamado por `scripts/migrar_banco.py`, que é o primeiro passo do `CMD`), numa transação só:

1. `pg_advisory_xact_lock(802611025)` no Postgres (duas réplicas não disputam DDL);
2. `Base.metadata.create_all` (cria tabelas que faltam; não altera as existentes);
3. `_ensure_runtime_columns`: ajustes anteriores ao Alembic. **Congelado, não acrescente nada.** Roda `UPDATE`s de normalização a cada deploy (grupo vazio → `planning_hub`, `importado_em` nulo etc.);
4. `alembic upgrade head` (`backend/app/db/migrations`). Revisões **idempotentes** (helpers `tabela_existe`/`coluna_existe` em `migrations/util.py`), porque o banco novo já nasce completo pelo `create_all`.

| Revisão | O que faz |
|---|---|
| `0001_baseline` | Nada: marca o ponto de partida. Registra que produção tem sobras de set/2026 fora dos modelos: tabelas `feedbacks`, `auditoria_admin`, `configuracoes_sistema` e colunas extras em `usuarios`, `certificados` e `processos` |
| `0002_historico_conferencia` | Cria `notas_conferencia_historico` se não existir |
| `0003_contas_convite` | `usuarios.email_verificado`, `usuarios.token_version`, `redefinicoes_senha_tokens.tentativas`; converte papel `leitura` → `operador` |
| `0005_erros_vistos` | Tabela `erros_vistos` (grupo, `visto_ate`, `usuario_id`): o "Limpar" do painel admin |
| `0004_seguranca_admin` | `usuarios.totp_segredo_cifrado`, `totp_ativo`, `totp_ultimo_passo`; tabelas `tentativas_acesso` e `auditoria_painel_admin` (o nome evita a sobra `auditoria_admin`, que em produção tem outras colunas e está vazia — conferido em 15/10) |
| `0006_indices_carga_banco` | Índices `ix_notas_cursor_emissao`, `ix_notas_cursor_recentes` (só Postgres), `ix_processos_jobs_status_updated_at`, `ix_tentativas_acesso_chave_criado_em`. Criada num deploy manual de 15/10 fora do Git e recriada em 16/10 a partir do `pg_indexes` de produção; só `IF NOT EXISTS` |

Mudança nova de esquema: modelo **e** revisão Alembic idempotente, no mesmo commit. Linha de comando: `alembic -c alembic.ini current|revision -m "..."`.

## Tabelas (23 no modelo)

`erros_vistos`: PK `grupo`; até quando os erros do grupo já foram vistos no painel admin. `/admin/erros` e o contador de `/admin/overview` só mostram o que veio depois (processos e logs continuam no banco).

| Tabela | Identidade / constraints | Conteúdo | Escrita por |
|---|---|---|---|
| `grupos` | `codigo` único | Equipes; `ativo` bloqueia os usuários | `admin.py` (admin geral), `_ensure_runtime_columns` (semeia `planning_hub`, `planning_ma`) |
| `empresas` | `cnpj` único (global) | Empresa atendida; `grupo` é texto, **sem FK** para `grupos` | `empresas_service`, autocadastro de certificado |
| `certificados` | FK empresa | `storage_key` do PFX no R2 (`pending` até subir), `senha_secret_ref`, validade, thumbprint | `certificados_service` |
| `secrets` | `ref` único | Valor cifrado (Fernet) da senha do PFX: `certificado:{id}:senha` | `secrets_service` |
| `processos` | FK empresa, certificado | Uma consulta: status, NSU início/fim, limite, `erro_resumo` (também avisos) | `consultas_service`, `processos_service`, worker |
| `processos_jobs` | FK processo | Execução: status, `locked_by/at`, `available_at`, `payload_json`, `updated_at` = heartbeat | `jobs_repo`, `job_lease_service`, ingestão incremental |
| `locks_processamento` | único (empresa, certificado) | Lock com `expires_at` (TTL 1 h) | `locks_repo`, `job_lease_service` |
| `monitoramento_config` | `grupo` único | Monitor automático: ativo, intervalo, último/próximo ciclo, `filtros_json` | `consultas_service` |
| `nsu_controle` | único (empresa, certificado) | NSU central, origem, `ultima_reconciliacao_em` | `nsu_control_service` |
| `notas` | **único (empresa, chave)**; índices por empresa + datas/CNPJ | Dados da NFS-e, valores, retenções calculadas, status fiscal, campos de fila/conferência, chaves de storage, arquivamento | `legacy_ingestion_service`, `notas_service` (conferência), scripts de correção |
| `notas_conferencia_historico` | FK nota (anulável), empresa, usuário (anulável) | Quem, quando, `analise`/`retificacao`, `alteracoes` JSON | `notas_service.salvar_conferencia` |
| `eventos` | **único (empresa, chave_evento)** | Cancelamento/substituição etc., `chave_afetada`, NSU | ingestão, `eventos_sync_service` |
| `arquivos` | FK empresa, nota, processo | Objeto no storage: tipo, chave, tamanho, checksum | ingestão, arquivamento, scripts |
| `logs_processos` | FK processo, empresa | Linha do tempo do job (~15 linhas por job), contexto JSON sanitizado na leitura | `logs_service`. **Sem retenção** se `LOGS_RETENCAO_DIAS=0` (padrão) |
| `cnpj_cache` | PK (cnpj, fonte) | Simples Nacional/CNAE de provedor externo, expiração | `cnpj_cache_service`, `cnpj_enrichment_service` |
| `usuarios` | `email` único; FK empresa **obrigatória** | Login, grupo, papel, `email_verificado`, `token_version`, 2FA (`totp_segredo_cifrado` com `SECRETS_KEY`, `totp_ativo`, `totp_ultimo_passo` contra reuso de código) | `auth_service`, `contas_service`, `admin_seguranca_service`, `admin.py` |
| `tentativas_acesso` | índice em `chave`, `criado_em` | Uma linha por tentativa em rota com limite; `chave` é hash (sem e-mail ou IP) | `core/rate_limit.RateLimiterBanco` (limpa a janela a cada tentativa e, de vez em quando, o que tem mais de 1 dia) |
| `auditoria_painel_admin` | índices em `usuario_id`, `grupo`, `created_at` | Ações do painel admin e tentativas de abrir a sessão | `deps.auditar_admin`, `admin_seguranca_service.registrar`, `GET /admin/auditoria` |
| `acessos_usuarios` | FK usuário | Login por IP/user-agent | `routers/auth.py`, `contas_service` |
| `convites_cadastro` | `token_hash` | Convite por grupo, usos, validade | `contas_service` |
| `verificacoes_email_tokens` | FK usuário (NOT NULL), convite | Código de confirmação (HMAC), tentativas | `contas_service` |
| `redefinicoes_senha_tokens` | FK usuário (NOT NULL) | Código de redefinição de senha (HMAC), tentativas | `contas_service` |

Nenhuma FK do modelo declara `ondelete`. Excluir uma linha referenciada falha no Postgres a menos que quem exclui trate os filhos (ex.: `admin.excluir_usuario` trata acessos, histórico, tokens de e-mail e senha, convites e `feedbacks`). Em produção as três tabelas de conta existiam antes do modelo; as regras de FK reais não foram conferidas.

### Campos de `notas` por domínio

- **Identidade e origem:** `empresa_id`, `chave`, `primeiro_nsu`, `ultimo_nsu`, `processo_id`, `importado_em`.
- **Documento:** `numero_nfse`, `data_emissao`, `competencia`, prestador/tomador (CNPJ/CPF e nome), `municipio`, códigos de serviço (`codigo_servico*`, `subitem_lc116`, `codigo_servico_nacional`), descrições, `cnae`.
- **Valores do XML:** `valor_servico`, `valor_base`, `valor_liquido`, `iss`, `irrf`, `inss`, `csrf`, `valor_pis/cofins/csll/csrf`, `aliquota_iss`, `iss_retido`, `valor_iss_retido`, deduções e descontos.
- **Calculado:** `*_calculado`, `valor_liquido_calculado`, `valor_liquido_correto`, `status_*` (irrf, inss, csrf, iss, base, valor líquido), `regra_*`, `alertas_fiscais`, `divergencia`, `incidencia_iss`, Simples Nacional.
- **Status fiscal:** `status_documento`, `status_rotulo` (REG-014).
- **Fila e conferência:** `prioridade(_manual)`, `status_fila_manual`, `sla`, `sla_status`, `entrada`, `responsavel`, `conferencia_*`, `operator_*`, `device_id`.
- **Arquivos:** `xml_storage_key`, `pdf_espelho_storage_key`, `pdf_oficial_storage_key` (legado), `status_nota_pdf`.
- **Arquivamento:** `arquivada`, `arquivada_em`, `arquivo_backup_storage_key`. O arquivamento atual apaga a linha (REG-031); as colunas vêm de uma versão anterior.

Colunas legadas: `processos.baixar_pdf_oficial` (sempre `False`, NOT NULL em produção); `cnpj_cache.status/simples_status/json_completo` (duplicam as colunas novas, copiadas a cada deploy).

## Riscos de integridade

- Banco e storage sem transação comum: arquivo órfão ou linha sem objeto (FIND-L02).
- `empresas.grupo` e `usuarios.grupo` são texto sem FK: grupo digitado errado cria um "grupo" sem cadastro (o acesso continua, porque `get_current_usuario` só bloqueia grupo existente e inativo).
- `logs_processos` sem retenção cresce ~15 linhas por job (ARCH-008).
- Verificar no banco (pendente): regras de FK das tabelas de conta, tamanho das tabelas, jobs duplicados por certificado.
