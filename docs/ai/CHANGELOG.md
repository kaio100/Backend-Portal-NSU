# Changelog do backend

Uma linha por mudança relevante, mais recente primeiro. Detalhe: `git show <commit>`. Os documentos de estado atual (`docs/ai/*`) não carregam histórico; ele fica aqui.

## 2026-10-16
- Migração `0006_indices_carga_banco` recriada no repositório. Ela tinha sido aplicada em produção por um deploy manual de 15/10 (`railway up`, fora do Git); sem o arquivo, o deploy da `main` de 16/10 09h45 parou no startup ("Can't locate revision") e derrubou o login até o Railway voltar à versão de 15/10. Conferido no Supabase: todas as colunas dos modelos existem em produção, as sobras (`feedbacks`, `auditoria_admin`, `configuracoes_sistema`, colunas extras de `certificados`/`processos`) são anuláveis; rotas usadas pelo frontend nos logs do Railway existem todas no código. Testado em Postgres 16 local (banco novo e banco já em 0006).
- Script `promover_admin --email ... [--aplicar]`: promove a admin uma conta existente, sem mexer em senha, grupo ou 2FA. Teste `test_promover_admin_simula_antes_e_libera_o_painel`.
- Revisão das mudanças de 15/10: suíte 338 passados (2 pulados), `compileall` ok. Correções abaixo; achado novo ARCH-019 (cursor sem índice).
- Segurança: `/auth/2fa/iniciar` responde 409 quando o 2FA já está ativo (antes só a senha bastava para cadastrar outro celular e entrar no painel). Teste `test_quem_so_tem_a_senha_nao_troca_o_2fa_ativo`.
- Deploy: o `UPDATE arquivos ... updated_at` de `_ensure_runtime_columns` só roda quando a coluna é criada (mesmo padrão do hotfix da `cnpj_cache`); `gerar_espelhos_ausentes` grava `updated_at`.
- `GET /notas` com tipo e empresa: percorre em lotes até completar a página, para o cursor não encerrar a lista antes do fim. Teste `test_cursor_com_tipo_e_empresa_nao_para_antes_do_fim` (chama o serviço direto: pelo `TestClient`, o recálculo de valores líquidos do startup regrava as notas no meio da paginação e o SQLite trunca `updated_at` no segundo).

## 2026-10-15
- Hotfix do deploy de 15/10 (`d0c508a0`): a subida ficou em loop porque `_ensure_runtime_columns` rodava a cada start os `UPDATE cnpj_cache SET ... WHERE ... IS NULL` e, com o banco lento, estourava o `statement_timeout`. As cópias de coluna antiga da `cnpj_cache` agora só rodam quando a coluna nova acaba de ser criada.
- Auditoria repetida depois das correções: import-linter 3/3 contratos (core sem api/services/repositories; services sem api; repositories sem api/services), Ruff 542 avisos (nenhum novo nas linhas alteradas; B008 é o padrão do FastAPI), Bandit sem achado novo, Betterleaks sem vazamento.
- `POST /admin/erros/limpar` do admin geral passa a marcar também os grupos citados pelas empresas (mesmo sem linha em `grupos`) e a chave `__sem_grupo__` (erros de empresa removida); antes esses erros continuavam aparecendo. Teste `test_limpar_do_admin_geral_inclui_empresa_de_grupo_sem_cadastro`.
- Documentação: ARCHITECTURE_CURRENT, CHANGE_IMPACT, PROJECT_CONTEXT (REG-043 a REG-046) e FINDINGS (SEC-B314, `defusedxml`) atualizados para `ae9d4e2d`. Auditoria de 15/10: import-linter 3/3 contratos; Bandit/Semgrep apontam `xml.etree` (SEC-B314), SHA-1 de impressão digital de certificado e SQL textual em scripts de admin (os dois últimos aceitos).
- Painel admin: `GET /admin/volumetria` (notas por dia e mês, valores, tomadas × prestadas, situação, top empresas, por grupo, pendentes por responsável, consultas ao ADN por dia, duração média, certificados por vencimento; `volumetria_service`) e `POST /admin/erros/limpar` (marca os erros como vistos por grupo, sem apagar processos nem logs; tabela `erros_vistos`, migração `0005_erros_vistos`). `/auth/me` informa `super_admin`.
- Branch `ajustes/seguranca-admin-paginacao` (sem commit): paginação por cursor em `/notas` (`cursor` + cabeçalho `X-Next-Cursor`) e em todas as varreduras internas (`_percorrer_repo`), no lugar do OFFSET que deixou as páginas finais com 10–16 s e esgotou o pool em 15/10.
- Mesma branch, segurança: limite de tentativas gravado no banco (`tentativas_acesso`, `RateLimiterBanco`), com limites novos no login por conta (20 em 15 min) e por IP (60 em 15 min); token do portal de 24 h para 12 h; painel `/admin` exige sessão própria de 30 min aberta com senha + 2FA (TOTP) e registra as alterações em `auditoria_painel_admin`; migração `0004_seguranca_admin`; scripts `resetar_2fa_admin` e `exportar_openapi`.
- Ambiente de auditoria instalado fora do repo (Serena MCP no Claude Code em somente leitura, Ruff, Bandit, Vulture, import-linter, Semgrep, ast-grep, Betterleaks, OSV-Scanner; Dependency Cruiser, Knip e Playwright para o frontend). Ver `docs/ai/FERRAMENTAS/`. Pasta `.serena/` criada no repo.

## 2026-10-08
- Documentação reestruturada: `docs/ai/` passa a descrever só o estado atual (00_LEIA_PRIMEIRO, PROJECT_CONTEXT, ARCHITECTURE_CURRENT, DATABASE, API, CHANGE_IMPACT, FINDINGS, SECURITY, OPERATIONS, DECISIONS, índices gerados). O mapa antigo (01–16) e as análises datadas foram para `docs/historico/`.
- Auditoria do backend no modo só leitura: `docs/historico/AUDITORIA_BACKEND_2026-10-08.md` (ARCH-001..017; ARCH-018 achado na revisão dos docs).
- Produção: o agendador embutido parou por volta das 11h10 UTC, logo depois de esgotar o pool de conexões (ARCH-001).

## 2026-10-06 — F6 (deploy `42f3951f`/`4f3ad950`)
- `a0cfbaf4` worker: heartbeat independente durante o download e a ingestão final (`manter_lease`); pula notas idênticas já completas na releitura.
- `e71fc73c` DANFSe: grade de linhas desenhada por último (só PDFs novos).
- `171cb36a` releitura do mês anterior na volta de uma parada e `POST /consultas/releitura-mes-anterior`; CORS expõe `Content-Disposition`.
- `66ee175e` operação: monitor sempre global no autocadastro (REG-039), vigia de empresas sem consulta, `/health/operacao`.

## 2026-09-25 — F1 a F5 (publicadas em 06/10)
- `26f65cb9` F5: fim do corte silencioso em 5.000 notas (REG-038).
- `87672e78` F4: grupos separados, cadastro por convite e código por e-mail (ADR-0001, ADR-0005).
- `11c8f8bd` F3: consulta ao ADN sem perder documentos e sem travar a fila (ADR-0003).
- `541f8018` F2: análise auditável com histórico, autor do login e Alembic (ADR-0002).
- `6c9a2d6c` canceladas e substituídas fora do ZIP e da planilha (ADR-0007).
- `0e019a2d` script `corrigir_status_fiscal`.
- `13b28521` valores calculados para a tela não são gravados.
- `1d3a7484` ingestão: eventos escondidos pelo índice, eventos já gravados, commit por nota.
- `2052dd62` status fiscal pela estrutura do XML (ADR-0004).
- `09559ad8`, `ebbb4a86`, `83db9afb`, `c43cb834`: limpeza, revert e restauração de `docs/ai`.

## 2026-09-17 (deploy `f2467152`, no ar de 17/09 a 06/10)
- `f2467152` cancelar processo rodando, lock órfão no SQLite, traceback do job no log.
- `44c6e726` estabiliza consultas ADN, remove PDF oficial, adiciona sincronização de eventos (ADR-0008).
- Correções de DANFSe (`2ab916e2`, `218f93f7`, `8369b688`, `a5e89971`), resumo da nota (`e75d3c97`), `recalcular_alertas_fiscais` (`da812b0c`, `87772ad1`, `d7f9fff5`, `fd574927`), `sincronizar_eventos_lote` (`7589f2a8`, `fdb30216`, `a5b123bf`, `12a8657e`), CPF e `dCompet` (`c7ec4bd3`).

## 2026-09-15
- `main` regredida para `f50da548` (03/09); a linha de 11–14/09 foi arquivada na branch local `arquivo/2026-09-14-autocadastro`.

## 2026-09-01 a 03
- `f50da548` retificação de análises; `a4a00b64` preparo para deploy; `d9c1622c` data de corte 2026-01-01; `bfcbb82b` migração antes de iniciar a API; `d3664375` arquivamento de notas antigas.
