# Achados abertos, riscos e dívida

> Atualizado em 27/10/2026 (ARCH-001 corrigido no código; cópia local da `main` `6b038bd`). Antes: 16/10/2026 (revisão das mudanças de 15/10 sobre `ae9d4e2d`; cópia sem `.git`, sem hash próprio). Fonte principal: `../historico/AUDITORIA_BACKEND_2026-10-08.md` (evidências completas, logs do Railway). Status: **CONFIRMADO**, **FORTEMENTE_INDICADO**, **HIPOTESE**, **NAO_DETERMINADO**. Severidade = impacto potencial.
>
> Regra: item corrigido sai da tabela de abertos e vai para "Resolvidos", com commit e data. Item novo segue o modelo do fim do arquivo.

## Abertos

| ID | Sev. | Status | Resumo | Onde |
|---|---|---|---|---|
| ARCH-002 | alta | CONFIRMADO | `GET /notas` lento sob carga + requisições abandonadas pelo frontend esgotam o pool (5+10); derrubou um job em 08/10 | `notas_service.listar_notas`, `session.py`, pool compartilhado |
| ARCH-004 | média | FORTEMENTE_INDICADO | Banco em ca-central-1 e app em us-west2 + consultas N+1 (`/certificados` 6,5 s, `/nsu/status`, `/admin/grupos`) | `certificados_repo.list_certificados`, `routers/nsu.py`, `admin.py` |
| ARCH-005 | média | CONFIRMADO (lógica) | Proteção do NSU em falha de ingestão anulável: `erros_detalhes` limitado a 20 e compartilhado com avisos de PDF; `obter_ultimo_nsu` usa o maior NSU das notas | `legacy_processing_service._limitar_nsu_por_falhas`, `nsu_control_service.obter_ultimo_nsu` |
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
| ARCH-019 | baixa | CONFIRMADO (Vulture + `git grep`) | Código morto: 22 funções/classes sem nenhuma referência (nem em testes), 2 arquivos de dados sem leitura no código e 1 import/parâmetro sobrando. Lista em "Detalhes" | ver Detalhes |
| ARCH-020 | alta | CONFIRMADO (métricas 15/10) | Banco Supabase no plano Micro com CPU em 91% sob uso normal + worker; login de 5 a 60 s. Plano em `PLANO_CARGA_BANCO.md` | Supabase, `useLiveStatus` (10 s), `/certificados` N+1, lista de notas |
| FIND-L01 | média | CONFIRMADO | Regras de atribuição automática da fila (`/fila-regras-atribuicao*` do backend antigo) não existem | `../historico/PENDENCIAS_BACKEND_PORTAL.md` |
| FIND-L02 | alta | CONFIRMADO | Banco e storage sem transação comum: o objeto vai ao R2 antes do commit; órfãos ou linhas sem objeto | `legacy_ingestion_service`, `certificados_service`; mitigação: `scripts/limpar_orfaos_storage`, `reconciliar_storage` |
| FIND-L03 | média | CONFIRMADO (código) | Verificação de consulta ativa seguida de insert, sem constraint: duas requisições simultâneas criam consultas iguais | `consultas_service.enqueue_consultas_pendentes` |
| FIND-L05 | média | HIPOTESE | Parsing tolerante pode aceitar XML com campos ausentes sem telemetria | `legacy_ingestion_service`, `nfse_xml_parser` |
| FIND-L06 | baixa | CONFIRMADO | SLA trata datetime sem fuso como UTC | `operational_fields_service.calcular_sla_operacional` |
| FIND-L07 | média | FORTEMENTE_INDICADO | ZIP e XLSX gerados de forma síncrona na requisição (até 10.000 notas, 16 threads, arquivo temporário) | `notas_download_service`, `portal_support_service` |
| FIND-L08 | baixa | CONFIRMADO | Métricas em memória: somem no restart | `core/observability.py` |
| FIND-L09 | alta | CONFIRMADO | Isolamento entre grupos só na aplicação; RLS do Supabase é opcional (scripts `aplicar_seguranca_rls`/`auditar_rls_supabase`); serviços aceitam `grupo=None` = todos | `api/deps.py`, services |
| ARCH-019 | média | FORTEMENTE_INDICADO | A paginação por cursor compara `coalesce(...)` e nenhum índice cobre essas expressões: cada página ainda lê e ordena todas as notas do filtro (sem descartar as anteriores, como o OFFSET fazia). Em produção existem `ix_notas_cursor_emissao`/`ix_notas_cursor_recentes` (migração 0006), mas a consulta passa o `1900-01-01` como parâmetro e o planejador provavelmente não casa a expressão com o índice. Medir o p95 de `/notas` e o `EXPLAIN` em produção | `notas_repo.chaves_ordem`, `list_notas` |
| FIND-L10 | alta | NAO_DETERMINADO (rotação) | Segredos e PFX no histórico do Git (achado de 06/10); rotação não reconferida | `../historico/SEGURANCA_CERTIFICADOS_2026-10-06.md`, `SECURITY.md` |

## Detalhes e recomendações

**ARCH-002.** O frontend corta em 15 s e repete, mas o servidor segue com a requisição e a conexão. Opções: `statement_timeout`, classificação e paginação em SQL em `listar_notas`, pool ou processo separado para o worker, frontend com cancelamento e sem repetição imediata. Validação: p95 de `/notas` abaixo de 2 s com o worker ativo; zero `QueuePool` em 7 dias.

**ARCH-004.** `joinedload(Certificado.empresa)` nas listagens; contar consultas por request; ADR sobre colocar banco e app na mesma região.

**ARCH-005.** Guardar o menor NSU com erro de ingestão num campo próprio, sem limite de 20; quando houver falha registrada, partir do NSU central, não do maior NSU das notas. Hoje a releitura noturna cobre o buraco.

**ARCH-007.** Decidir em ADR se operador cadastra certificado. Se não, `require_admin` nas 4 rotas de envio; se sim, documentar e permitir também a troca de senha.

**ARCH-008.** Incluir a descrição no log de `alert_failure`; configurar e-mail ou webhook; retenção de `logs_processos` (`LOGS_RETENCAO_DIAS`); trocar `print` por logger; health com estado do worker e do agendador.

**ARCH-009.** Apagar XMLs do motor já ingeridos e confirmados no R2 depois de N dias; alerta de disco; conferir o tamanho do volume no Railway.

**ARCH-010.** Devolver com `available_at = agora + 30 s` e dormir quando o motivo for `lock_indisponivel`.

**ARCH-018.** Conferir no container se existe `/app/data/RETENCOES_REGRAS.xlsx` e qual o log "Planilha de regras fiscais carregada: N subitens de <caminho>" no startup. Definir uma fonte única versionada (ou variável de caminho) e registrar o checksum da planilha usada.

**ARCH-016.** Job de CI com serviço Postgres; fixture de operador e de outro grupo como padrão nos testes de rota; Python 3.11 local.

**ARCH-019 (código morto, 15/10/2026).** Achado com `vulture --min-confidence 60` e conferido com `git grep -w` (0 referências fora da própria definição). Validadores do Pydantic, middleware e listeners de evento foram descartados como falsos positivos, porque o framework os chama via decorador.
- Repositórios: `jobs_repo.get_job`, `jobs_repo.get_next_pending_job`, `locks_repo._como_utc`, `notas_repo.count_notas_grupo`, `usuarios_repo.get_usuario`, `usuarios_repo.list_usuarios`.
- Services: `consultas_service.has_active_consulta_for_certificado`, `notas_service.classificar_tipo_nota`, `nsu_control_service.sincronizar_com_notas`, `operational_fields_service.consulta_simples_api_from_payload`, `portal_support_service._format_value` e `_relatorio_money`, `storage_service.build_export_key`, `build_raw_key`, `build_json_key` e `build_log_key`.
- API e schemas: `deps.require_certificado_grupo` (só aparece na lista do gerador de índices), `schemas/arquivos.ArquivoDownloadInfo`, `schemas/notas.NotaArquivoResumo`.
- Scripts: `db_migration_common.table_names_for_models`.
- Sobras pequenas: import `List` não usado em `adn_nfse_downloader.py:38`; parâmetro `commit_every` ignorado em `legacy_ingestion_service.py:1022`.
- Arquivos: `data/consultas_auto.json` (o estado do agendador hoje fica em `monitoramento_config`; só o README cita o arquivo) e `empresas.example.json` (nenhum código lê). `RETENCOES_REGRAS.xlsx` da raiz é idêntica à de `data/` e serve de reserva no import (ARCH-018), então **não** é morta.
- Usados só em testes (manter ou decidir): `portal_support_service._normalizar_invertexto_payload`, `retencoes_regras_service.resolver_subitem_lc116` (citado na REG-033), `StorageService.list_prefix`.
- Scripts de uso único, já executados, que só o `OPERATIONS.md` cita: `migrar_sqlite_para_postgres`, `validar_migracao_postgres`, `migrar_storage_para_r2`, `migrar_rbac`, `promover_usuarios_locais`, `backfill_documentos_partes`. Não são código morto (são ferramentas manuais), mas podem ir para um arquivo histórico se a decisão for não mantê-los.
- Nenhum módulo da aplicação ficou sem import.

Recomendação: apagar a lista "sem referência" num commit só, com a suíte completa antes e depois; não apagar os usados em testes nem os scripts sem decisão do responsável.

## Resolvidos (referência)

- SEC-B314 (27/10, código): XML de terceiros lido com `defusedxml` (upload do DANFSe, ingestão do ADN, parser do PDF, motor e os scripts `corrigir_status_fiscal`/`reconciliar_notas_certificados`); declaração de entidades vira "XML inválido" pelo mesmo caminho de um XML malformado. Os tipos (`Element`) continuam da biblioteca padrão. Dependência nova `defusedxml==0.7.1`. Testes `tests/test_xml_seguro.py` (3 falham com o código anterior); Bandit B313/B314 nesses arquivos: 7 → 0. O PHP do DANFSe lê o XML por conta própria (libxml) e não foi alterado.
- ARCH-003 (27/10, código): a ingestão incremental não grava mais `updated_at` de processo/job nem renova o lock; isso fica só com `manter_lease` (mesma empresa, certificado e worker, a cada 30 s), que envolve toda a execução. Some a ordem inversa de UPDATE que travava no Postgres. Teste `test_ingestao_incremental_nao_grava_heartbeat_de_job_e_processo` (falha com o código anterior). Validar em produção: zero `DeadlockDetected` no log.
- ARCH-006 (16/10, `6b038bd`): `DELETE /admin/usuarios/{id}` apaga os tokens de e-mail e senha, solta os convites e apaga `feedbacks` antes do usuário. Teste `test_excluir_usuario_com_tokens_de_email_e_senha`; conferido em Postgres 16 local.
- ARCH-001 (27/10, código; produção não verificada): o laço do agendador embutido captura exceções, registra o "último tick" e o último erro; o supervisor recria a tarefa se ela terminar; `/health/operacao` mostra o tick e o vigia avisa `agendador_parado` após `ALERTA_AGENDADOR_PARADO_MINUTOS` (30). Testes `tests/test_agendador_resiliente.py` (os dois do laço/supervisor falham com o `main.py` anterior). Continua valendo conferir o primeiro ciclo depois do deploy.
- FIND-L04 (limite de tentativas em memória): resolvido na branch de 15/10 com `RateLimiterBanco` (tabela `tentativas_acesso`).
- SEC-2FA (16/10): com a senha (e o login que ela dá), um admin com 2FA ativo podia gerar outro segredo em `/auth/2fa/iniciar`, cadastrar o próprio celular e abrir o painel; reproduzido com teste. Agora responde 409; teste `test_quem_so_tem_a_senha_nao_troca_o_2fa_ativo`.
- Deploy (16/10): `UPDATE arquivos SET updated_at = created_at WHERE updated_at IS NULL` rodava a cada subida (varredura sem índice, o mesmo risco do loop de 15/10). Agora só quando a coluna é criada; `gerar_espelhos_ausentes` passa a gravar `updated_at`.
- Listagem (16/10): com filtro de tipo **e** empresa, uma nota descartada pela anotação (ex.: da empresa para ela mesma) deixava a página incompleta e o `X-Next-Cursor` sumia antes do fim. Agora percorre em lotes até completar a página; teste `test_cursor_com_tipo_e_empresa_nao_para_antes_do_fim`.
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

## Validação local do plano de carga (15/10/2026)

ARCH-004: N+1 da listagem de certificados corrigido localmente com joinedload; teste mede 1 SELECT com mais de uma empresa e confirma isolamento de grupo. As outras consultas N+1 e regiões diferentes continuam abertas. ARCH-020: índices, distribuição automática e limitador preparados, ainda sem comprovação de ganho em produção. Contadores desde julho registrados em `medicoes/carga-banco-2026-10-15.json`; não confundir média histórica com CPU atual. Redução de campos da lista permanece pendente porque o DTO inclui quase todas as colunas da nota.

> Seção do plano de carga verificada em 15/10/2026 sobre `2d05450f` + alterações locais; o restante mantém o carimbo original.
