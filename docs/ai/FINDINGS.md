# Achados abertos, riscos e dívida

> Atualizado em 15/10/2026, commit `ae9d4e2d`. Fonte principal: `../historico/AUDITORIA_BACKEND_2026-10-08.md` (evidências completas, logs do Railway). Status: **CONFIRMADO**, **FORTEMENTE_INDICADO**, **HIPOTESE**, **NAO_DETERMINADO**. Severidade = impacto potencial.
>
> Regra: item corrigido sai da tabela de abertos e vai para "Resolvidos", com commit e data. Item novo segue o modelo do fim do arquivo.

## Abertos

| ID | Sev. | Status | Resumo | Onde |
|---|---|---|---|---|
| ARCH-001 | crítica | FORTEMENTE_INDICADO | Agendador embutido morre na primeira exceção e ninguém o recria; em 08/10 parou às ~11h10 UTC | `main.py:143-153` |
| ARCH-002 | alta | CONFIRMADO | `GET /notas` lento sob carga + requisições abandonadas pelo frontend esgotam o pool (5+10); derrubou um job em 08/10 | `notas_service.listar_notas`, `session.py`, pool compartilhado |
| ARCH-003 | média | CONFIRMADO | Deadlock heartbeat × ingestão incremental (ordem inversa de UPDATE), 4× de 06 a 08/10 | `job_lease_service.py:341-348`, `legacy_processing_service.py:274-281` |
| ARCH-004 | média | FORTEMENTE_INDICADO | Banco em ca-central-1 e app em us-west2 + consultas N+1 (`/certificados` 6,5 s, `/nsu/status`, `/admin/grupos`) | `certificados_repo.list_certificados`, `routers/nsu.py`, `admin.py` |
| ARCH-005 | média | CONFIRMADO (lógica) | Proteção do NSU em falha de ingestão anulável: `erros_detalhes` limitado a 20 e compartilhado com avisos de PDF; `obter_ultimo_nsu` usa o maior NSU das notas | `legacy_processing_service._limitar_nsu_por_falhas`, `nsu_control_service.obter_ultimo_nsu` |
| ARCH-006 | média | FORTEMENTE_INDICADO | Excluir usuário com token de verificação, redefinição ou convite falha no Postgres (FK sem `ondelete`); o teste passa no SQLite | `admin.excluir_usuario`, `models.py` |
| ARCH-007 | média | CONFIRMADO | Operador envia e autocadastra certificado (cria empresa, grava senha, dispara consulta), mas só admin edita ou exclui. Decisão pendente | `routers/certificados.py` |
| ARCH-008 | média | CONFIRMADO | Alertas sem canal: log só diz "Operacao falhou" sem a descrição; sem `ALERT_WEBHOOK_URL`; `ALERTA_EMAILS` e `METRICS_TOKEN` vazios em 06/10; morte de tarefa sem log; `/health` não reflete worker nem agendador; `logs_processos` sem retenção | `observability.alert_failure`, `operacao_service`, `health.py` |
| ARCH-009 | média | CONFIRMADO | Volume `/app/data` de 2,2 para 5,8 GB em 7 dias; XMLs e índices do motor nunca são apagados | `legacy_processing_service._limpar_respostas_antigas` |
| ARCH-010 | baixa | CONFIRMADO (código) | Lock ocupado devolve o job sem espera: loop quente e bloqueio da fila do grupo. Não visto nos logs de 01–08/10 | `worker/jobs.py:311-314`, `main.py:102-107` |
| ARCH-011 | baixa | CONFIRMADO | Estado do arquivamento é um dict de módulo compartilhado entre grupos | `admin.py:249` |
| ARCH-012 | baixa | CONFIRMADO | Motor grava `atualizado_em` sem fuso; a ingestão compara com UTC: fora de servidor UTC nada é ingerido | `adn_nfse_downloader.agora_iso`, filtro `updated_after` |
| ARCH-013 | baixa | HIPOTESE | HTTP 400 do ADN tratado como lote vazio: job "finalizado" sem documentos e sem erro | `adn_nfse_downloader.py:270-276` |
| ARCH-014 | baixa | CONFIRMADO (código) | Cliente boto3 recriado a cada chamada (inclusive a cada ~3 s na ingestão) | `storage_service.get_storage_service` |
| ARCH-015 | baixa | CONFIRMADO | Subprocesso PHP herda todos os segredos do ambiente | `danfse_service.py:69` |
| ARCH-016 | média | CONFIRMADO | Testes rodam como admin por padrão (`conftest.py` autouse), em SQLite (sem FK, pool ou deadlock), sem Postgres no CI; Python local 3.10 × produção 3.11 | `tests/conftest.py`, `.github/workflows/ci.yml` |
| ARCH-017 | info | CONFIRMADO | Variáveis no Railway que o código não lê: `LOCAL_SIGNUP_ENABLED`, `FRONTEND_CRIAR_CONTA_URL`, `FRONTEND_RESET_PASSWORD_URL` | Railway × `config.py` |
| ARCH-018 | média | FORTEMENTE_INDICADO | Planilha fiscal de produção pode não ser a do Git: `data/RETENCOES_REGRAS.xlsx` ganha da raiz, `data/` é o volume e o `.dockerignore` exclui `data/`; mudanças em `data/RETENCOES_REGRAS.xlsx` no repo não chegam à produção | `retencoes_regras_service.REGRAS_XLSX_PATH`, `.dockerignore`, volume `/app/data` |
| FIND-L01 | média | CONFIRMADO | Regras de atribuição automática da fila (`/fila-regras-atribuicao*` do backend antigo) não existem | `../historico/PENDENCIAS_BACKEND_PORTAL.md` |
| FIND-L02 | alta | CONFIRMADO | Banco e storage sem transação comum: o objeto vai ao R2 antes do commit; órfãos ou linhas sem objeto | `legacy_ingestion_service`, `certificados_service`; mitigação: `scripts/limpar_orfaos_storage`, `reconciliar_storage` |
| FIND-L03 | média | CONFIRMADO (código) | Verificação de consulta ativa seguida de insert, sem constraint: duas requisições simultâneas criam consultas iguais | `consultas_service.enqueue_consultas_pendentes` |
| FIND-L05 | média | HIPOTESE | Parsing tolerante pode aceitar XML com campos ausentes sem telemetria | `legacy_ingestion_service`, `nfse_xml_parser` |
| FIND-L06 | baixa | CONFIRMADO | SLA trata datetime sem fuso como UTC | `operational_fields_service.calcular_sla_operacional` |
| FIND-L07 | média | FORTEMENTE_INDICADO | ZIP e XLSX gerados de forma síncrona na requisição (até 10.000 notas, 16 threads, arquivo temporário) | `notas_download_service`, `portal_support_service` |
| FIND-L08 | baixa | CONFIRMADO | Métricas em memória: somem no restart | `core/observability.py` |
| FIND-L09 | alta | CONFIRMADO | Isolamento entre grupos só na aplicação; RLS do Supabase é opcional (scripts `aplicar_seguranca_rls`/`auditar_rls_supabase`); serviços aceitam `grupo=None` = todos | `api/deps.py`, services |
| SEC-B314 | média | CONFIRMADO (Bandit B314/B405, Semgrep) | XML de terceiros (ADN e upload do DANFSe avulso) lido com `xml.etree`, sem proteção contra expansão de entidades. Recomendação: `defusedxml.ElementTree` como substituto direto | `services/danfse_service.py:24`, `services/legacy_ingestion_service.py`, `scripts/corrigir_status_fiscal.py`, `scripts/reconciliar_notas_certificados.py` |
| FIND-L10 | alta | NAO_DETERMINADO (rotação) | Segredos e PFX no histórico do Git (achado de 06/10); rotação não reconferida | `../historico/SEGURANCA_CERTIFICADOS_2026-10-06.md`, `SECURITY.md` |

## Detalhes e recomendações

**ARCH-001.** Evidência: último "Agendador de consultas:" às 10:55:30 UTC de 08/10; `QueuePool` às 11:09; dois `POST /consultas/iniciar` manuais (15:07 e 15:17) sem ciclo depois; fila vazia às 15:55; alerta `empresas_sem_consulta` às 21:19. Alternativa não descartada: monitor desligado por alguém (conferir `monitoramento_config`). Ação imediata: reiniciar o serviço. Correção: `try/except` + log no laço, supervisor que recria tarefa morta, "último tick" em `/health/operacao`, alerta após 30 min sem tick.

**ARCH-002.** O frontend corta em 15 s e repete, mas o servidor segue com a requisição e a conexão. Opções: `statement_timeout`, classificação e paginação em SQL em `listar_notas`, pool ou processo separado para o worker, frontend com cancelamento e sem repetição imediata. Validação: p95 de `/notas` abaixo de 2 s com o worker ativo; zero `QueuePool` em 7 dias.

**ARCH-003.** O heartbeat da thread de ingestão ficou redundante depois do `manter_lease`. Retirar de `_loop_ingestao_incremental`, ou usar a mesma ordem (job → processo → lock) nos dois.

**ARCH-004.** `joinedload(Certificado.empresa)` nas listagens; contar consultas por request; ADR sobre colocar banco e app na mesma região.

**ARCH-005.** Guardar o menor NSU com erro de ingestão num campo próprio, sem limite de 20; quando houver falha registrada, partir do NSU central, não do maior NSU das notas. Hoje a releitura noturna cobre o buraco.

**ARCH-006.** Tratar (ou cascatear) `verificacoes_email_tokens`, `redefinicoes_senha_tokens` e `convites_cadastro.criado_por_usuario_id` antes do `delete`; conferir as FKs reais em produção; teste com Postgres.

**ARCH-007.** Decidir em ADR se operador cadastra certificado. Se não, `require_admin` nas 4 rotas de envio; se sim, documentar e permitir também a troca de senha.

**ARCH-008.** Incluir a descrição no log de `alert_failure`; configurar e-mail ou webhook; retenção de `logs_processos` (`LOGS_RETENCAO_DIAS`); trocar `print` por logger; health com estado do worker e do agendador.

**ARCH-009.** Apagar XMLs do motor já ingeridos e confirmados no R2 depois de N dias; alerta de disco; conferir o tamanho do volume no Railway.

**ARCH-010.** Devolver com `available_at = agora + 30 s` e dormir quando o motivo for `lock_indisponivel`.

**ARCH-018.** Conferir no container se existe `/app/data/RETENCOES_REGRAS.xlsx` e qual o log "Planilha de regras fiscais carregada: N subitens de <caminho>" no startup. Definir uma fonte única versionada (ou variável de caminho) e registrar o checksum da planilha usada.

**ARCH-016.** Job de CI com serviço Postgres; fixture de operador e de outro grupo como padrão nos testes de rota; Python 3.11 local.

## Resolvidos (referência)

- FIND-L04 (limite de tentativas em memória): resolvido na branch de 15/10 com `RateLimiterBanco` (tabela `tentativas_acesso`).
- ARCH-002 (parcial, 15/10): `/notas` e as varreduras internas paginam por cursor; o frontend não repete pedido após timeout e a Conferência só conta notas com clique. Falta o pool separado para o worker.

| Item antigo | Resolução |
|---|---|
| RSK-001 migração sem Alembic | F2 (`541f8018`): Alembic + advisory lock; `_ensure_runtime_columns` congelado |
| RSK-002 motor sem checkpoint | F3 (`11c8f8bd`): saída no volume, NSU central só no fim e limitado pela primeira falha (ver ARCH-005 para os limites dessa proteção) |
| RSK-005 claim/lock concorrentes | F3: UPDATE condicional + savepoint; recuperação por heartbeat; `manter_lease` em `a0cfbaf4` |
| RSK-007 retificação sem histórico | F2: `notas_conferencia_historico` |
| RSK-008 `exportar_conferencia_xlsx` duplicada | Uma definição só (`portal_support_service.py:1413`) |
| RSK-009/010 corte silencioso em 5.000 | F5 (`26f65cb9`): `buscar_notas_exportacao` + erro acima do teto |
| RSK-011 GET de download com menos filtros | F5: GET aceita os mesmos filtros do POST |
| RSK-012 `/auth/criar-conta` inexistente | F4 (`87672e78`): cadastro por convite |
| Classificação de status por palavras | `2052dd62` + script `corrigir_status_fiscal` (REG-014) |
| Certificado vencido repetido na fila | Sai da fila (REG-042); ~90 falhas por dia sumiram após o deploy de 06/10 |
| Monitor restringido pelo autocadastro | F6 (`66ee175e`): REG-039 + vigia de empresas sem consulta |

A validar no frontend: RSK-013 (`/auth/grupos` só admin) e o contrato de telas da F4/F7.

## Modelo para item novo

```text
ID: ARCH-0NN
Título:
Status: CONFIRMADO | FORTEMENTE_INDICADO | HIPOTESE | NAO_DETERMINADO
Severidade: crítica | alta | média | baixa | info
Evidência: arquivo:linha, log (data/hora), consulta, teste
Impacto:
Causa (só se comprovada):
Recomendação / opções:
Como validar:
Rollback:
```
