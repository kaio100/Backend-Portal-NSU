# Auditoria do backend — modo `/analyze` (2026-10-08)

Feita com o roteiro do agente "Arquiteto de Software" (SYSTEM + BRAIN + `WORKFLOWS/audit_repository.md` + `QUALITY/EVIDENCE_PROTOCOL.md`). Somente leitura: nenhum arquivo do projeto, configuração, banco ou serviço foi alterado.

## 0. Contrato e escopo

| Item | Situação |
|---|---|
| Código | `nfse_adn_limpo` em `main` @ `a0cfbaf4`, working tree com 3 docs não versionados em `docs/` |
| Produção (Railway) | **Acessado, só leitura**: deploys, config do serviço, nomes de variáveis (sem valores), logs de build/runtime/HTTP de 01/10 a 08/10, métricas de 7 dias |
| Produção (Supabase) | **Não acessado**: o conector voltou a apontar para a organização "Hub Contabil" (`fcxuiyehtockwefgozea`); o projeto do portal (`xiqiuumoaqhxajqtppmf`) recusou as consultas |
| Testes | **Não executados**: `tests/conftest.py` grava `data/test_suite.db` e `storage/` dentro do projeto, o que viola o "não modificar nada" |
| Frontend | Fora do escopo desta rodada |
| R2 (storage) | Não acessado |

Lido integralmente: `main.py`, `core/*` (config, security, rate_limit, rede), `db/session.py`, `db/models.py`, `api/deps.py`, todos os routers (alguns por trechos: `notas.py` 1–145 e 400–683), `worker/*`, `jobs_repo`, `locks_repo`, `locks_service`, `job_lease_service`, `consultas_service`, `processos_service`, `nsu_control_service`, `legacy_processing_service`, `certificados_service`, `contas_service`, `auth_service`, `email_service`, `secrets_service`, `notas_archive_service`, `danfse_service`, `generate.php`, Dockerfile, compose, CI, `.env.example`.
Lido por trechos: `legacy_ingestion_service` (laço principal e storage), `adn_nfse_downloader.py` (HTTP/retry/processamento), `storage_service`, `notas_service.listar_notas`, `notas_download_service`, `notas_repo`, `operacao_service`, `observability.alert_failure`.
Não lido: `portal_support_service` (1.453 linhas), `operational_fields_service`, `retencoes_*`, `nfse_xml_parser`, `eventos_sync_service`, scripts de `backend/app/scripts/`, template PHP.

Status de certeza: **CONFIRMADO** (evidência direta) · **FORTEMENTE_INDICADO** (várias evidências coerentes, sem prova completa) · **HIPOTESE** · **NAO_DETERMINADO**.

---

## 1. Incidente em andamento (prioridade imediata)

### ARCH-001 — O agendador automático parou às ~11h10 UTC de hoje e não volta sozinho

- **Status:** FORTEMENTE_INDICADO (o defeito de código é CONFIRMADO; a morte da tarefa é inferida pela ausência de logs, porque uma tarefa asyncio que morre não registra nada)
- **Severidade:** crítica
- **Evidência:**
  - `backend/app/main.py:143-153`: `_run_consultas_scheduler` não tem `try/except`. Qualquer exceção em `is_enabled()` ou `_enqueue_consultas_automaticas()` encerra a tarefa para sempre. O supervisor (`main.py:110-140`) só cria workers para grupos novos e não reinicia o agendador. O agendador avulso `worker/scheduler.py:127-132` tem o `try`; o embutido, que é o usado em produção, não tem.
  - Produção usa o agendador embutido: serviço único, sem `EMBEDDED_SCHEDULER_ENABLED` nas variáveis (padrão `True`).
  - Logs: "Agendador de consultas: {...}" a cada 15 min desde 07/10 17h21 (37–47 certificados por ciclo). **Último registro: 08/10 10:55:30 UTC.**
  - 08/10 11:09:36–11:09:44 UTC: `QueuePool limit of size 5 overflow 10 reached` (ver ARCH-002). O próximo ciclo cairia às ~11:10.
  - 15:07 e 15:17 UTC: `POST /consultas/iniciar` manual. Esse caminho enfileira direto e zera `proximo_ciclo_em`, então um agendador vivo teria rodado de novo às ~15:32. Nenhum ciclo apareceu.
  - Os jobs pararam às 15:55 UTC (fila esvaziada). Às 21:19 UTC veio o alerta `operacao_empresas_sem_consulta`.
- **Impacto:** nenhuma consulta automática ao ADN desde ~08h10 (Brasília). As notas não se perdem, porque o ADN guarda tudo e a releitura volta depois da parada, mas o portal fica desatualizado. É a terceira vez que a coleta para sem que alguém perceba na hora.
- **Hipótese alternativa:** alguém desligou o monitor às ~11h. Não pode ser descartada sem o banco (`monitoramento_config.automatico_ativo`), mas o clique em "iniciar" às 15h07 teria religado.
- **Ação imediata (sua):** reiniciar o serviço no Railway recria a tarefa. Não fiz isso por ser modo só leitura.
- **Correção sugerida:** `try/except` com log no laço; supervisor que recria tarefa morta; registrar o "último tick" do agendador e expor em `/health/operacao`; alerta quando passar de 30 min sem tick.
- **Como validar:** teste que injeta exceção em `enqueue_consultas_pendentes` e verifica que o laço continua; métrica do último tick.
- **Rollback:** mudança local em `main.py`, sem efeito em dados.

---

## 2. Achados por severidade

### ARCH-002 — Listagem de notas lenta + requisições abandonadas esgotam o pool de conexões

- **Status:** CONFIRMADO
- **Severidade:** alta
- **Evidência (08/10, 11:02–11:10 UTC, log HTTP):** `GET /notas` com 8–13 s e depois 499 (cliente fecha em 15 s) dezenas de vezes; `GET /notas/todas` sempre 499 em 15 s. Até `/health` e `/db/health` chegaram a 10–15 s. Às 11:09:36 veio o `QueuePool limit of size 5 overflow 10 reached` em `deps.get_current_usuario`. **O job 44468 falhou pelo mesmo motivo** ("Job 44468 do processo 44468 falhou: QueuePool…").
- **Causa (parcialmente comprovada):**
  1. O frontend desiste em 15 s e repete, mas o servidor continua executando a requisição abandonada e segurando a conexão.
  2. `notas_service.listar_notas` pode carregar e classificar até 5.000 notas em memória quando há filtro de direção sem empresa (comentário no próprio código; teto em `notas_repo.py:182`).
  3. API e worker dividem o mesmo pool (5 + 10) no mesmo processo. O worker abre várias sessões em paralelo: a principal, a thread de ingestão a cada ~3 s, o heartbeat a cada 30 s e a checagem de cancelamento a cada chamada ao ADN.
  4. Latência entre regiões (ARCH-004) multiplica o tempo de cada consulta.
  - No fim da tarde, sem carga, `/notas` fica com mediana de 0,6 s. O problema é a combinação de carga com consulta pesada.
- **Impacto:** telas travando, job de consulta falhando e o gatilho provável do ARCH-001.
- **Opções:** (a) `statement_timeout` no Postgres e paginação/classificação em SQL; (b) pool ou engine separado para o worker, ou o worker em processo separado (o `docker-compose.yml` já modela isso); (c) frontend sem repetição agressiva e com cancelamento real.
- **Validação:** p95 de `/notas` abaixo de 2 s com o worker rodando; zero `QueuePool` nos logs por 7 dias.

### ARCH-003 — Deadlock entre o heartbeat do job e a ingestão incremental

- **Status:** CONFIRMADO
- **Severidade:** média
- **Evidência:** 4 ocorrências de `psycopg.errors.DeadlockDetected` em 06/10 18:36, 07/10 00:34, 07/10 23:27 e 08/10 00:54 UTC, em `processos_jobs` e em `processos`. A ordem dos travamentos é invertida:
  - `job_lease_service.renovar_lease` atualiza `Job` e depois `Processo` (linhas 341–348);
  - `legacy_processing_service._loop_ingestao_incremental` grava `processo.updated_at` e `job.updated_at` na mesma transação (linhas 274–281), e o ORM grava `processos` antes de `processos_jobs`.
  - Os dois renovam o mesmo heartbeat: o da thread de ingestão ficou redundante depois do `manter_lease` (commit `a0cfbaf4`).
- **Impacto:** a volta da ingestão incremental é desfeita (o heartbeat e o log daquela volta). As notas já confirmadas linha a linha não se perdem. Gera ruído e risco se a frequência subir.
- **Recomendação:** tirar o heartbeat da thread de ingestão e deixar só o `manter_lease`, ou usar a mesma ordem nos dois.

### ARCH-004 — Banco e aplicação em regiões diferentes + consultas N+1

- **Status:** FORTEMENTE_INDICADO
- **Severidade:** média
- **Evidência:** Supabase em `ca-central-1` e Railway em `us-west2`. `/db/health` (`SELECT 1` + pre-ping) leva ~280 ms. `GET /certificados` tem mediana de **6,5 s**: `certificados_repo.list_certificados` não carrega `empresa` junto, e `CertificadoRead` lê `empresa_nome`/`empresa_cnpj`, uma consulta por certificado (~80 × ~70 ms). `/nsu/status` faz ~4 consultas por empresa (84 empresas). `/admin/grupos` conta usuários e empresas por grupo em laço.
- **Recomendação:** `joinedload`/`selectinload` nas listagens; medir a contagem de consultas por request; decidir em um ADR se banco e aplicação devem ficar na mesma região.

### ARCH-005 — Proteção do NSU contra falha de ingestão pode ser anulada

- **Status:** CONFIRMADO (lógica); impacto real NAO_DETERMINADO (sem banco)
- **Severidade:** média
- **Evidência:**
  1. `legacy_ingestion_service.ingerir_saida_legado` guarda no máximo 20 itens em `erros_detalhes`, e esse espaço é compartilhado com os avisos de PDF (`etapa: pdf_espelho`). `legacy_processing_service._limitar_nsu_por_falhas` (linhas 106–125) só segura o cursor com itens `etapa == "ingestao"`. Se os 20 primeiros itens forem avisos de PDF, o NSU avança mesmo com `erros > 0`. Linhas sem chave contam erro sem NSU.
  2. `nsu_control_service.obter_ultimo_nsu` (linhas 57–69) usa `max(central, maior_nsu_importado)`. No job seguinte, o ponto de partida é o maior NSU já gravado menos 50. Uma falha mais de 50 NSUs abaixo fica para trás até a releitura noturna.
  - O teste `test_consulta_adn_confiavel.py:183` cobre só o caso simples (3 itens).
- **Mitigação existente:** a releitura profunda noturna e a "volta de parada".
- **Recomendação:** guardar o menor NSU com falha num contador separado, sem limite; o ponto de partida deve respeitar o NSU central quando houver falha registrada.

### ARCH-006 — Excluir usuário pode dar erro 500 no Postgres

- **Status:** FORTEMENTE_INDICADO
- **Severidade:** média
- **Evidência:** `admin.py:385-397` apaga `acessos_usuarios` e anula o autor no histórico, mas não trata `verificacoes_email_tokens.usuario_id`, `redefinicoes_senha_tokens.usuario_id` (NOT NULL) nem `convites_cadastro.criado_por_usuario_id`. As FKs em `models.py:466-503` não têm `ondelete`. Todo usuário que entrou por convite tem token de verificação. O teste `test_conferencia_auditavel.py:152` passa porque o SQLite não aplica FKs por padrão.
- **Validação pendente:** conferir no banco as regras de exclusão das FKs (o Supabase estava inacessível).

### ARCH-007 — Permissões incoerentes em certificados

- **Status:** CONFIRMADO (código); se é intencional: HIPOTESE
- **Severidade:** média
- **Evidência:** `POST /certificados`, `/certificados/upload`, `/certificados/autocadastrar` e `/empresas/{id}/certificados` exigem só login. Por eles, um operador cria empresa, grava a senha do PFX e dispara consulta. Já `PUT`, `PATCH`, `DELETE`, `/senha` e `/testar` exigem admin. O autocadastro também informa "Esta empresa pertence a outro grupo", revelando que o CNPJ existe em outro grupo.
- **Decisão necessária:** operador pode ou não cadastrar certificado? Registrar em ADR e alinhar as rotas.

### ARCH-008 — Observabilidade não mostra o que importa

- **Status:** CONFIRMADO
- **Severidade:** média
- **Evidência:**
  - `observability.alert_failure` registra só "Operacao falhou" + `event`; a descrição (quais empresas, quantas) vai só para webhook ou e-mail. `ALERT_WEBHOOK_URL` não está nas variáveis do Railway.
  - A morte de tarefa asyncio não gera log (ARCH-001). `/health` responde ok mesmo sem agendador.
  - `print` em vez de logger em `main.py` e no worker.
  - `logs_processos` sem retenção (`LOGS_RETENCAO_DIAS` não configurado; padrão 0 = nunca apaga), com ~15 linhas por job e ~80 jobs a cada 15 min.

### ARCH-009 — Volume `/app/data` crescendo sem limite

- **Status:** CONFIRMADO (crescimento); risco de lotar: NAO_DETERMINADO (tamanho do volume não consultado)
- **Severidade:** média
- **Evidência:** métrica de disco de **2,2 GB para 5,8 GB em 7 dias**. A saída do motor legado foi para o volume na F3, e `_limpar_respostas_antigas` (`legacy_processing_service.py:128-146`) só apaga `raw/` e `json/`; os XMLs e índices CSV ficam para sempre.
- **Recomendação:** política de retenção dos XMLs já ingeridos (o R2 já tem a cópia) e alerta de disco.

### ARCH-010 — Loop quente quando o lock do certificado está ocupado

- **Status:** CONFIRMADO (código); ocorrência em produção: não apareceu nos logs de 01–08/10
- **Severidade:** baixa (hoje)
- **Evidência:** `worker/jobs.py:311-314` devolve o job com `mark_job_pending` sem `available_at` futuro. `main.py:102-107` só dorme quando a resposta é `sem_job`. `claim_next_pending_job` ordena por `available_at, id`, então o mesmo job volta na hora, grava 2 logs por volta e bloqueia a fila do grupo. Gatilhos: cancelar e reenfileirar o mesmo certificado, `forcar=true` ou worker zumbi.
- **Recomendação:** `available_at = agora + 30 s` ao devolver e dormir quando a resposta for `lock_indisponivel`.

### ARCH-011 — Estado do arquivamento compartilhado entre grupos

- **Status:** CONFIRMADO
- **Severidade:** baixa (hoje só um grupo em uso)
- **Evidência:** `admin.py:249` usa o dict de módulo `_arquivamento_estado`. O admin do grupo A vê resultado e erro do arquivamento do grupo B e recebe 409 enquanto B arquiva. O estado se perde ao reiniciar.

### ARCH-012 — Fuso horário quebra a ingestão fora de servidor em UTC

- **Status:** CONFIRMADO (código); só afeta ambiente local
- **Severidade:** baixa
- **Evidência:** o motor grava `atualizado_em` com `datetime.now()` sem fuso (`adn_nfse_downloader.py:102-103`). A ingestão filtra as linhas com `>= run_started_at` em UTC (`legacy_processing_service.py:522`, `legacy_ingestion_service` filtro `updated_after`). Num Windows em Brasília, as linhas ficam 3 h "no passado" e nada é ingerido. Em produção (container em UTC) funciona.

### ARCH-013 — HTTP 400 do ADN vira "lote vazio"

- **Status:** HIPOTESE (impacto)
- **Severidade:** baixa
- **Evidência:** `adn_nfse_downloader.py:270-276` aceita 400 como resposta normal. Sem `LoteDFe`, o laço conta como vazio e o job termina "finalizado" sem documentos e sem erro. Um certificado sem permissão para o CNPJ ficaria invisível. Não procurei 400 nos logs.

### ARCH-014 — Cliente R2 recriado a cada chamada

- **Status:** CONFIRMADO (código); efeito na memória: HIPOTESE
- **Severidade:** baixa
- **Evidência:** `storage_service.get_storage_service` (linhas 346–361) cria `boto3.client` novo por request e a cada volta da ingestão incremental. A memória do serviço variou de 0,48 a 3,24 GB na semana (média de 2,2 GB).

### ARCH-015 — Subprocesso PHP herda todos os segredos

- **Status:** CONFIRMADO
- **Severidade:** baixa (defesa em profundidade)
- **Evidência:** `danfse_service.py:69` passa `env = os.environ.copy()` ao PHP, que processa XML enviado por usuário. O processo PHP recebe `JWT_SECRET`, `DATABASE_URL` e as chaves do R2. O dompdf está com `isRemoteEnabled = false` (bom).

### ARCH-016 — Testes não exercitam papéis, FKs nem concorrência real

- **Status:** CONFIRMADO
- **Severidade:** média (testabilidade)
- **Evidência:** `tests/conftest.py:36-64` injeta um admin de `planning_hub` em todos os testes, exceto `test_auth_account.py`. Regras de operador e de isolamento só são testadas onde o teste desfaz isso (`test_rbac`, `test_contas_e_grupos`). Os testes rodam em SQLite (sem FK, sem deadlock, sem pool) e o CI não tem Postgres. Python local 3.10, produção 3.11.

### ARCH-017 — Configuração divergente

- **Status:** CONFIRMADO
- **Severidade:** informativa
- **Evidência:** `LOCAL_SIGNUP_ENABLED`, `FRONTEND_CRIAR_CONTA_URL` e `FRONTEND_RESET_PASSWORD_URL` estão no Railway e o código não os lê. `WORKER_DRY_RUN` tem padrão `True` no código (`config.py:30`) e `false` no `.env.example`: se a variável sumir, a produção passa a simular sem erro. O Railway mostra builder `RAILPACK`, mas o build segue o `Dockerfile` (confirmado no log de build), então o `CMD` com `migrar_banco` vale.

### Pendente de análise anterior (não reverificado)

- A exposição de segredos no histórico do Git (`docs/SEGURANCA_CERTIFICADOS_2026-10-06.md`) continua listada como ação aberta; esta auditoria não confirmou se houve rotação.

---

## 3. Forças confirmadas

- Filtro por grupo presente em todas as rotas lidas (`require_*_grupo`, `grupo=usuario.grupo`), com correções F4 visíveis nos comentários.
- Autenticação sólida: PBKDF2 com 600 mil iterações, login com tempo constante, `token_version` derruba sessões, limite de tentativas pelo IP real atrás do proxy, código de e-mail com HMAC.
- Validação de segredos obrigatórios em produção, docs/OpenAPI desligados em produção, cabeçalhos de segurança, MultiFernet com rotação de chave.
- Ingestão idempotente (`uq_notas_empresa_chave`, `uq_eventos_empresa_chave_evento`) com commit por nota.
- Claim atômico de job, lock com UPDATE condicional e savepoint, recuperação de job sem heartbeat.
- Migração com Alembic sob advisory lock, rodando antes do `uvicorn` no `CMD`.
- Proteção de caminho nas chaves do storage.
- Certificado vencido fora da fila: as ~90 falhas por dia sumiram depois do deploy de 06/10, confirmado nos logs.
- Comentários de código que registram o porquê de cada correção.

## 4. Características de arquitetura que mandam aqui

1. **Completude da coleta:** nenhuma nota do ADN pode faltar sem aviso. Foi o que mais falhou: ARCH-001, ARCH-005, incidentes de 17/09 e 01/10.
2. **Integridade fiscal e auditabilidade** (status, retenções, histórico de análise).
3. **Isolamento entre grupos.**
4. **Operabilidade:** saber em minutos que algo parou.
5. **Desempenho das telas sob carga do worker.**

## 5. Ordem recomendada

| # | O quê | Por quê |
|---|---|---|
| 0 | **Reiniciar o serviço no Railway** (ação manual sua) | Volta o agendador hoje |
| 1 | ARCH-001 + sinal de "último tick" em `/health/operacao` | Fecha a classe de incidente "parou sem ninguém ver" |
| 2 | ARCH-002 (pool/processo separado do worker, `statement_timeout`, `/notas` em SQL) | Gatilho do item 1 e telas travando |
| 3 | ARCH-003 (remover heartbeat duplicado) | Mudança pequena, deadlock confirmado |
| 4 | ARCH-005 (proteção do NSU) | Completude da coleta |
| 5 | ARCH-006, ARCH-007 (decisões + correções pequenas) | Erros de admin e permissões |
| 6 | ARCH-004 (ADR de região + N+1) | Latência geral |
| 7 | ARCH-008, ARCH-009 (logs, retenção, disco) | Operação |
| 8 | ARCH-016 (Postgres no CI, testes de papel sem o admin automático) | Evita regressão de tudo acima |

**Fitness functions sugeridas:** alerta quando o agendador passar de 30 min sem tick; CI com Postgres (FKs reais); teste que derruba o agendador com exceção; métrica de p95 por rota; contagem de consultas SQL por request nas listagens.

## 6. O que fica para validar com acesso ao banco

- `monitoramento_config` (monitor ativo, filtros) e última consulta finalizada por empresa (ARCH-001)
- regras de exclusão das FKs que apontam para `usuarios` (ARCH-006)
- notas com NSU abaixo do cursor e com erro de ingestão (ARCH-005)
- tamanho de `logs_processos` e das demais tabelas (ARCH-008)
- jobs duplicados por certificado e locks órfãos (ARCH-010)
