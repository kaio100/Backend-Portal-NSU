# Changelog do backend

Uma linha por mudança relevante, mais recente primeiro. Detalhe: `git show <commit>`. Os documentos de estado atual (`docs/ai/*`) não carregam histórico; ele fica aqui.

## 2026-10-30
- ZIP em lote: com notas de uma só empresa, o arquivo e a pasta raiz levam o nome da empresa (`<Empresa>.zip` com `xml/` e `pdf/` direto na raiz; `RELATORIO_ERROS.txt` e a planilha também); com várias empresas, `notas_nfse_<data>.zip` com `notas_nfse/<Empresa>/{xml,pdf}`. Testes em `test_notas_download_lote.py`. Frontend: "PDF + Planilha" passa a enviar `incluir_relatorio` (um ZIP só) e `preferirPdfOriginal` saiu. Sem commit/deploy.
- PDF oficial removido do código: a ingestão (índice e varredura) não lê mais `pdf_path`/`*.pdf` da pasta de saída nem grava `pdf_oficial`; o ZIP (`notas_download_service._select_arquivos`) e a lista de arquivos da nota (`notas_service._selecionar_arquivos_visiveis`) entregam só XML + `PDF_ESPELHO`. `preferir_pdf_original` saiu do schema e da rota (clientes que ainda o enviam são ignorados). Colunas legadas, `build_pdf_oficial_key`, arquivamento e `limpar_orfaos_storage` continuam para não apagar objetos antigos do R2. Novo script `regenerar_espelhos_desde.py` (notas com `data_emissao >= 2026-09-01`; simulação por padrão). Testes ajustados em `test_notas_download_lote.py` e `test_consultas_api.py`. Sem commit/deploy.

## 2026-10-20
- Download em lote: `incluir_relatorio` (POST no corpo, GET na query) coloca a planilha de conferência dentro do ZIP (`notas_nfse/relatorio_conferencia_*.xlsx`). A planilha segue os filtros, não os `nota_ids`; sai mesmo sem PDF disponível; erro de limite da planilha aborta antes de ler o storage. Testes em `tests/test_notas_download_lote.py`. Sem commit/deploy.
- Layouts de planilha (`services/relatorio_layouts_service.py`): `planning_ma` (conferência, padrão) e `planning_hub` (relação de NFS-e e retenções, modelo VS Engenharia; exige `empresa_id`, cabeçalho com nome/CNPJ da empresa, rodapé fixo PLANNING MAROX, CNO em branco, código IBGE traduzido pela tabela do DANFSe). `layout` em `POST /relatorios/conferencia`, `relatorio_layout` em `/notas/download-lote`. Validado com 130 XMLs reais da A IDEAL. Plano e decisões em `PLANO_LAYOUT_PLANILHA.md`. Sem commit/deploy.

## 2026-10-16
- `DELETE /admin/usuarios/{id}`: apaga antes os tokens de verificação de e-mail e de troca de senha, solta os convites criados pela pessoa e apaga a sobra `feedbacks`. Antes, quem tinha token pendente dava 500 (`ForeignKeyViolation` em `verificacoes_email_tokens`, usuário 23 em produção). Teste `test_excluir_usuario_com_tokens_de_email_e_senha`; conferido também em Postgres 16 local, que valida as chaves estrangeiras.
- Painel admin: `POST /auth/admin/sessao` e `POST /auth/2fa/iniciar` respondem 400 (antes 401) para senha ou código errado. Com 401 o frontend deslogava do portal e a pessoa voltava ao login a cada tentativa; caso real em produção logo depois de configurar o 2FA, quando o código da confirmação foi reaproveitado na entrada (anti-reuso). Código repetido ganhou mensagem própria; as mensagens evitam a palavra "senha", que o `friendlyHttpMessage` do frontend troca pela de senha de certificado (registrado para o frontend).
- Migração `0006_indices_carga_banco` recriada no repositório. Ela tinha sido aplicada em produção por um deploy manual de 15/10 (`railway up`, fora do Git); sem o arquivo, o deploy da `main` de 16/10 09h45 parou no startup ("Can't locate revision") e derrubou o login até o Railway voltar à versão de 15/10. Conferido no Supabase: todas as colunas dos modelos existem em produção, as sobras (`feedbacks`, `auditoria_admin`, `configuracoes_sistema`, colunas extras de `certificados`/`processos`) são anuláveis; rotas usadas pelo frontend nos logs do Railway existem todas no código. Testado em Postgres 16 local (banco novo e banco já em 0006).
- Script `promover_admin --email ... [--aplicar]`: promove a admin uma conta existente, sem mexer em senha, grupo ou 2FA. Teste `test_promover_admin_simula_antes_e_libera_o_painel`.
- Revisão das mudanças de 15/10: suíte 338 passados (2 pulados), `compileall` ok. Correções abaixo; achado novo ARCH-019 (cursor sem índice).
- Segurança: `/auth/2fa/iniciar` responde 409 quando o 2FA já está ativo (antes só a senha bastava para cadastrar outro celular e entrar no painel). Teste `test_quem_so_tem_a_senha_nao_troca_o_2fa_ativo`.
- Deploy: o `UPDATE arquivos ... updated_at` de `_ensure_runtime_columns` só roda quando a coluna é criada (mesmo padrão do hotfix da `cnpj_cache`); `gerar_espelhos_ausentes` grava `updated_at`.
- `GET /notas` com tipo e empresa: percorre em lotes até completar a página, para o cursor não encerrar a lista antes do fim. Teste `test_cursor_com_tipo_e_empresa_nao_para_antes_do_fim` (chama o serviço direto: pelo `TestClient`, o recálculo de valores líquidos do startup regrava as notas no meio da paginação e o SQLite trunca `updated_at` no segundo).

## 2026-10-15
- Frontend do plano de carga publicado por CLI na Vercel: commit `e98299a`, deploy `dpl_2DfCPKs4TE4hMWya3H46Bs6bLN9n`, domínio `frontend-portal-nsu.vercel.app`; HTML/scripts/CORS 200 e constantes de polling/login confirmadas no bundle. Agendador do backend criou quatro jobs distribuídos no ciclo de 23:30 UTC.
- Deploy do plano de carga no Railway por upload direto: `753ac481-3d02-49c1-91b6-cfc4f929d844`, commit local de release `4e4302c0`. Migração 0006 e quatro índices confirmados; saúde 200; jobs 44873/44874 concluídos. Consulta representativa das 100 notas recentes: EXPLAIN 123,982 → 1,168 ms. Frontend ainda aguardando autenticação da Vercel.
- Plano de carga iniciado (local, sem commit/deploy): medição pg_stat_statements registrada; certificados sem N+1; revisão 0006 com índices do cursor, jobs e tentativas; distribuição automática por available_at; limitador sem DELETE por chave, pool dedicado e tempos limitados; frontend polling mínimo 30 s e login 60 s. Retenção definida em 90 dias, simulação encontrou 8 candidatos (nenhum apagado); script de simulação/aplicação em lotes criado. DTO resumido da lista de notas segue pendente para preservar contrato.
- Produção: worker/agendador reativados às 21:29 UTC, deploy `ed71dd6f-a37c-490d-ac7d-fc8ba5922cef`; teste real do job 44838 finalizou sem erro às 21:39 UTC.
- Produção: depois do hotfix, o login seguiu lento (5–60 s) com o banco Supabase em 91% de CPU. Worker e agendador pausados por variável no Railway às 19:41 UTC (deploy `c66adfba`); aumento de computação do Supabase iniciado pelo responsável. Plano de redução de carga em `PLANO_CARGA_BANCO.md` (ARCH-020).
- Varredura de código morto (Vulture + `git grep`): 22 funções/classes sem referência e 2 arquivos de dados sem leitura, registrados em FINDINGS ARCH-019. Nada apagado ainda.
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
