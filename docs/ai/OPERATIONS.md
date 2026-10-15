# Operação: ambiente, deploy, variáveis, logs e runbooks

> Verificado em 08/10/2026: código `a0cfbaf4`; Railway (config do serviço, nomes das variáveis sem valores, logs e métricas). Valores de variáveis citados como "(06/10)" vêm do checklist de deploy daquela data.

## Produção

| Item | Valor |
|---|---|
| Railway | projeto `daring-flexibility` (`7b512b35-2f19-4800-ac18-3ce7601ed9b7`), serviço `Backend-Portal-NSU` (`51bb13e4-5cc7-4222-a4b6-4a0bdb7bf7ab`), ambiente `production` |
| Domínio | `backend-portal-nsu-production.up.railway.app` (porta 8080) |
| Região / réplicas | `us-west2`, 1 réplica |
| Volume | montado em `/app/data` (saída do motor, temporários, bases locais) |
| Origem | GitHub `kaio100/Backend-Portal-NSU`, branch `main`: **push na main = deploy** |
| Build | `Dockerfile` (o painel mostra RAILPACK, mas o log segue o Dockerfile) |
| Banco | Supabase `xiqiuumoaqhxajqtppmf` (`ca-central-1`, Postgres 17), só como Postgres |
| Arquivos | Cloudflare R2 (`STORAGE_BACKEND=r2`) |
| Frontend | `https://frontend-portal-nsu.vercel.app` (CORS fixo no código) |
| Deploy ativo em 08/10 | `42f3951f` = commit `a0cfbaf4`, desde 07/10 17:11 UTC |
| Recursos (7 dias até 08/10) | CPU média 0,06 vCPU (limite 24); memória 0,5–3,2 GB (média 2,2); disco 2,2 → 5,8 GB |

## Deploy

1. Local: `python -m pytest -q`, `python -m compileall -q backend tests`, `php -l backend/danfse/generate.php` e `php backend/danfse/tests/run.php backend/danfse/assets/xml/teste.xml` (o mesmo do CI).
2. Push na `main` → build → o `CMD` roda `python -m backend.app.scripts.migrar_banco` (advisory lock + Alembic) e só então sobe o `uvicorn`. Migração que falha impede a subida.
3. Depois: `GET /health`, `/db/health`, `/storage/health` com HTTP 200; no log, "Agendador de consultas automaticas iniciado" e, em até 15 min, "Agendador de consultas: {...}".
4. Scripts pós-deploy, quando o commit exigir: sempre simulação primeiro, depois `--aplicar`/`--executar`. Ex.: `corrigir_status_fiscal` (após mudança de classificação), `sincronizar_eventos_lote --todas --desde AAAA-MM-DD`.
5. **Rollback:** "Rollback" do deploy anterior no Railway. As revisões Alembic não têm `downgrade` útil (são aditivas): voltar o código não desfaz colunas novas, o que é seguro enquanto o código antigo as ignora.

## Ambiente local

- `python iniciar_local.py`: SQLite `data/local_test.db`, storage em `storage/`, worker e agendador embutidos, validações de produção ligadas. **Consultas ao ADN são reais.**
- **Nunca** `uvicorn backend.app.main:app` direto com o `.env` desta máquina: ele aponta `DATABASE_URL` (e o R2) para **produção**.
- Testes: `pip install -r requirements-dev.txt` e `python -m pytest -q` (o `conftest` força SQLite `data/test_suite.db` e storage local).
- Rodar o motor fora de um servidor em UTC: ver ARCH-012 (a ingestão pode ignorar as linhas).

## Variáveis de ambiente

"No Railway" = o nome existe nas variáveis do serviço em 08/10. Sem ele, vale o padrão do código.

| Variável | Padrão no código | No Railway | Observação |
|---|---|---|---|
| `ENVIRONMENT` | `local` | sim | `production` liga validações, HSTS/CSP e esconde `/docs` |
| `DATABASE_URL` | SQLite local | sim | |
| `DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW` | 5 / 5 | sim (5 / 10 pelo log) | Pool compartilhado API + worker (ARCH-002) |
| `DATABASE_POOL_TIMEOUT` / `DATABASE_POOL_RECYCLE` | 30 / 300 | não | |
| `API_KEY`, `JWT_SECRET`, `SECRETS_KEY` | — | sim | Obrigatórias em produção; `SECRETS_KEY` aceita lista separada por vírgula |
| `JWT_EXPIRE_MINUTES` | 720 | sim | O valor no Railway, se existir, vence o padrão: conferir se ainda é 1440 |
| `ADMIN_2FA_OBRIGATORIO` | `true` | não | `false` só em emergência: o painel volta a exigir apenas o papel de admin |
| `ADMIN_SESSAO_MINUTOS` | 30 | não | Duração da sessão do painel admin |
| `CORS_ORIGINS` | localhost | sim | |
| `STORAGE_BACKEND`, `R2_*` | `local` | sim | |
| `WORKER_DRY_RUN` | **`True`** | sim | Precisa valer `false` em produção |
| `API_WORKER_ENABLED` / `EMBEDDED_SCHEDULER_ENABLED` | `True` / `True` | não | Por isso tudo roda num processo só |
| `API_WORKER_CONCURRENCY`, `API_WORKER_SLEEP` | 1 / 0,2 | sim | Workers por grupo |
| `CONSULTAS_SCHEDULER_SLEEP`, `CONSULTAS_DEFAULT_LIMITE`, `CONSULTAS_DEFAULT_PAUSA` | 1 / 1000 / 0 | sim | O agendador dorme no mínimo 5 s |
| `WORKER_REAL_MAX_LIMITE`, `WORKER_REAL_MAX_PAUSA`, `WORKER_CONSULTA_LOTE_TAMANHO`, `WORKER_TEMP_DIR`, `WORKER_DRY_RUN_SLEEP` | 1000 / 0 / 1000 / `data/tmp_worker` / 0,2 | sim | |
| `WORKER_ADN_LOTE` | `True` | não | |
| `LEGACY_OUTPUT_DIR`, `LEGACY_OUTPUT_RETENCAO_DIAS` | `data/saida_adn_nfse` / 15 | não | A retenção só vale para `raw/` e `json/` (ARCH-009) |
| `JOBS_TRAVADOS_MINUTOS` | 15 | não | |
| `NOTAS_DATA_CORTE` | 2026-01-01 | sim | |
| `NSU_LOOKBACK_NORMAL` / `NSU_LOOKBACK_RECONCILIACAO` / `NSU_RECONCILIACAO_HORA_INICIO`/`FIM` / `NSU_RELEITURA_APOS_HORAS_SEM_CONSULTA` / `NSU_MAX_VAZIOS_CONSECUTIVOS` | 50 / 1000 / 19–5 / 6 / 5 | não | |
| `NOTAS_RECEBIDAS_DIA_CORTE_MES_ANTERIOR` | 3 | sim | |
| `DOWNLOAD_LOTE_MAX_NOTAS` / `RELATORIO_MAX_NOTAS` / `DOWNLOAD_STORAGE_WORKERS` | 10.000 / 20.000 / 16 | não | |
| `RESEND_ENABLED`, `RESEND_API_KEY`, `RESEND_FROM_EMAIL` | desligado | sim | Sem Resend em produção o cadastro falha (503) |
| `FRONTEND_BASE_URL` | — | sim | Link do convite |
| `SUPER_ADMIN_EMAILS` | — | sim | Admin geral |
| `ALERTA_EMAILS` | — | sim (vazio em 06/10) | Sem e-mail o vigia só escreve no log |
| `ALERT_WEBHOOK_URL` | — | não | |
| `METRICS_TOKEN` | — | sim (vazio em 06/10) | Vazio → `/metrics` e `/health/operacao` dão 404 |
| `ALERTA_FILA_PARADA_MINUTOS` / `ALERTA_FALHAS_POR_HORA` / `ALERTA_INTERVALO_HORAS` / `ALERTA_EMPRESA_SEM_CONSULTA_HORAS` | 60 / 10 / 6 / 6 | não | |
| `LOGS_RETENCAO_DIAS` | 0 (nunca apaga) | não | |
| `INVERTEXTO_*` | desligado | sim | |
| `CNPJ_RECEITA_DB_PATH`, `CNPJ_RECEITA_CACHE_DAYS` | `data/cnpj_receita.sqlite3` / 30 | não | |
| `DANFSE_*` | `backend/danfse`, `php`, 5 MB, 60 s | não | |
| `FUSO_HORARIO` | `America/Sao_Paulo` | não | |
| `NFSE_AMBIENTE`, `NFSE_VERIFY_SSL` | — | sim | Só o motor rodado pela linha de comando lê; o worker usa `empresas.ambiente` e TLS sempre verificado |
| `LOCAL_SIGNUP_ENABLED`, `FRONTEND_CRIAR_CONTA_URL`, `FRONTEND_RESET_PASSWORD_URL` | — | sim | **Não lidas pelo código** (ARCH-017) |

## Como ler os logs (Railway)

| Procure | Significa |
|---|---|
| `Agendador de consultas automaticas iniciado` | Startup do agendador embutido |
| `Agendador de consultas: {'certificados_enfileirados': N` | Um ciclo (a cada ~15 min). **Mais de 30 min sem essa linha, com monitor ligado = agendador parado** |
| `Job reservado` / `API worker 1 (grupo): {...}` | Início e fim de job |
| `Job N do processo N falhou:` | Falha de job (texto do erro em seguida) |
| `QueuePool limit of size` | Pool de conexões esgotado (ARCH-002) |
| `DeadlockDetected` | ARCH-003 |
| `Supervisor: N job(s) sem heartbeat voltaram para a fila` | Recuperação de job travado |
| `Operacao falhou` + `event` | Alerta do vigia; a descrição **não** vai para o log (ARCH-008) |
| `Certificado N ignorado na consulta: vencido` / `senha nao pode ser lida` | Certificado fora da fila |
| `HTTP 499` no log HTTP | Cliente desistiu (o frontend corta em 15 s) |

## Runbooks

### Consultas automáticas paradas (sem "Agendador de consultas:" no log)
1. Veja se o monitor está ligado (Motor ADN / `GET /consultas/status` → `automatico_ativo`, `monitor.escopo`).
2. Se está ligado e não há ciclo: o agendador embutido morreu (ARCH-001). **Reinicie o serviço** no Railway; confira a linha de startup e o primeiro ciclo em até 15 min.
3. Procure a causa perto do último ciclo (`QueuePool`, erro de banco).
4. A releitura "após parada" (REG-040) recupera o período sozinha nas próximas consultas.

### Monitor restrito (só algumas empresas consultadas)
`GET /consultas/status` → `monitor.escopo = restrito`. No Motor ADN, use "Voltar a consultar todas" (REG-039). Histórico: `../historico/ANALISE_CANOPUS_CONSULTAS_2026-10-06.md`.

### Notas faltando de uma empresa
1. Última consulta finalizada da empresa e o certificado (vencido? senha ilegível? ver log).
2. `POST /consultas/releitura-mes-anterior` com a empresa.
3. Comparar índice local × banco: `python -m backend.app.scripts.reconciliar_notas_certificados --certificado-id N`.
4. Eventos de notas antigas: `sincronizar_eventos_lote --todas --desde AAAA-MM-DD` (sem `--executar` só conta).

### Lentidão e `QueuePool`
Ver se coincide com o worker processando (log de jobs) e com `GET /notas`/`/notas/todas` em 499, e nos logs do Postgres consultas com `OFFSET` alto ou várias iguais em paralelo (incidente de 15/10: contagem da Conferência e listagens com OFFSET). Desde a branch de 15/10 as listagens usam cursor e o frontend não repete pedido após timeout. Correção estrutural restante (pool separado para o worker) em ARCH-002.

### Admin perdeu o celular (2FA)
O admin geral abre o painel → Usuários → Ações → Zerar 2FA. Sem admin geral disponível: `python -m backend.app.scripts.resetar_2fa_admin --email <e-mail>` (simula) e depois `--aplicar`. A pessoa configura o aplicativo de novo ao abrir `/admin`.

### Disco do volume
Métrica `DISK_USAGE_GB` no Railway. A maior parte é `data/saida_adn_nfse/empresas/*/xml` (ARCH-009). Apague só XMLs já ingeridos e presentes no R2, com backup.

### Troca de `SECRETS_KEY`
Nova chave **na frente** (`nova,antiga`) → deploy → `python -m backend.app.scripts.rotacionar_segredos` (simula) → `--aplicar` → conferir zero falhas → remover a antiga.

## Scripts (`backend/app/scripts/`, `python -m backend.app.scripts.<nome>`)

Todos usam o `DATABASE_URL` do ambiente: com o `.env` local, isso é **produção**. Rode a simulação antes.

| Grupo | Scripts |
|---|---|
| Banco e migração | `migrar_banco` (é o `CMD`), `migrar_sqlite_para_postgres`, `validar_migracao_postgres`, `diagnosticar_banco`, `db_migration_common` (biblioteca), `migrar_rbac`, `promover_usuarios_locais` |
| Status e dados fiscais | `corrigir_status_fiscal` (corrige status gravado pela classificação antiga), `recalcular_alertas_fiscais` (subitem, ISS retido, valor líquido; aceita `--desde`), `backfill_documentos_partes` (CNPJ/CPF ausentes a partir do XML), `auditar_incidencia_iss`, `corrigir_simples_pendentes_online`, `listar_consultas_simples_pendentes` |
| NSU, consultas e eventos | `diagnosticar_nsu_certificado`, `reconciliar_notas_certificados` (reimporta do índice local), `enfileirar_reprocessamento_certificados`, `status_reprocessamento_certificados`, `sincronizar_eventos_lote` (varre notas autorizadas e consulta eventos no ADN) |
| Storage e PDFs | `reconciliar_storage` (banco × objetos), `limpar_orfaos_storage` (acha e, com `--aplicar`, apaga objetos sem registro), `gerar_espelhos_ausentes`, `regenerar_carimbos_pdfs`, `regenerar_espelhos_competencia`, `migrar_storage_para_r2`, `testar_r2`, `r2_common` (biblioteca) |
| Certificados e segredos | `auditar_integridade_certificados`, `corrigir_integridade_certificados`, `rotacionar_segredos`, `resetar_2fa_admin` (zera o 2FA de um admin; sem `--aplicar` só mostra) |
| Contrato da API | `exportar_openapi` (grava o OpenAPI para o frontend gerar os tipos com `npm run gerar:tipos`; não conecta no banco) |
| Segurança do Supabase | `aplicar_seguranca_rls`, `auditar_rls_supabase` (usam `SUPABASE_DATABASE_URL`) |
| CNPJ | `importar_base_cnpj_receita` (base local da Receita), `sincronizar_cnpjs_portal` (usa `ONLINE_DATABASE_URL`) |
| Arquivamento | `arquivar_notas_antigas` (mesma regra de `/admin/arquivamento`; destrutivo) |

Descrição de cada um: `gerado/ARQUIVOS.md` (docstring) ou o `--help` do script.
