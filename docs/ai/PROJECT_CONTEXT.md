# Contexto do projeto: domínio, atores e regras

> Verificado contra o código em 15/10/2026, commit `ae9d4e2d` (branch `ajustes/seguranca-admin-paginacao`, não implantada). Regras marcadas com † foram herdadas do mapa de 15/09–06/10 e tiveram só a função âncora conferida em 08/10, não o comportamento linha a linha.

## Para que serve

As empresas atendidas pelas equipes da Planning recebem e emitem NFS-e (padrão nacional). O portal busca todos esses documentos no **ADN** com o certificado A1 de cada empresa, guarda o XML e um PDF espelho (DANFSe), calcula as retenções esperadas (ISS, IRRF, INSS, PIS/COFINS/CSLL) e compara com o que veio na nota. Depois coloca cada nota numa **fila de conferência** para um analista revisar, e exporta ZIP com XML/PDF e planilha de conferência.

## Glossário

| Termo | Significado |
|---|---|
| **ADN** | Ambiente de Dados Nacional da NFS-e (`adn.nfse.gov.br/contribuintes`). Acesso por mTLS com o certificado da empresa |
| **NSU** | Número sequencial único que o ADN dá a cada documento de um CNPJ. A consulta percorre `DFe/{nsu}` em lotes |
| **NSU central** | `nsu_controle.ultimo_nsu` por (empresa, certificado): até onde o portal confirmou que importou |
| **E2220 / NENHUM_DOCUMENTO_LOCALIZADO** | Resposta (HTTP 404) do ADN quando não há documento a partir do NSU. É resposta normal, não erro |
| **Chave de acesso** | Identificador de 50 dígitos da NFS-e (contém o CNPJ do emitente) |
| **Evento** | Documento do ADN que muda a situação de uma nota: cancelamento (e101101, e105104), substituição (e105102) e outros |
| **DANFSe / PDF espelho** | PDF gerado pelo portal a partir do XML (biblioteca PHP em `backend/danfse`). O PDF "oficial" do ADN foi desativado |
| **Grupo** | Equipe isolada (`planning_hub`, `planning_ma`). Empresas e usuários pertencem a um grupo; funciona como um muro: um grupo não vê nada do outro |
| **Admin geral** | Admin cujo e-mail está em `SUPER_ADMIN_EMAILS`. Único que vê e administra todos os grupos |
| **Processo / Job** | Uma consulta ao ADN para um certificado (`processos`) e sua unidade de execução na fila (`processos_jobs`) |
| **Monitor** | `monitoramento_config` por grupo: liga o agendador automático e guarda os filtros (`empresa_ids`, `certificado_ids`) |
| **Status fiscal** | `notas.status_documento`: autorizada, cancelada, substituida, `cstat_N`. Vem só do XML |
| **Status da fila** | Situação da conferência (correta, divergente, cancelada…), calculada ou definida manualmente. Não é o status fiscal |
| **Retificação** | Regravar uma análise que já tem responsável (`retificar=true`), com histórico |
| **Data de corte** | `NOTAS_DATA_CORTE` (2026-01-01): documentos emitidos antes são descartados na consulta |

## Atores

- **Operador** (padrão de quem entra por convite): consulta, confere, exporta, gera convite, pede releitura e cadastra certificado (ver ARCH-007).
- **Admin do grupo**: o que o operador faz, mais gestão de usuários do grupo, empresas, senhas de certificado e arquivamento. O painel `/admin` exige senha + 2FA a cada 30 min.
- **Admin geral**: cria, edita e exclui grupos, move usuários entre grupos e reseta o 2FA de outros admins. `/auth/me` devolve `super_admin=true` para ele.
- **Sistemas externos**: ADN (consulta), Cloudflare R2 (arquivos), Resend (e-mail), Supabase/Postgres (banco), Invertexto (CNPJ, opcional), base local da Receita (`cnpj_receita.sqlite3`).

## Fluxos que geram valor

1. **Coleta:** monitor ligado → agendador a cada `intervalo_minutos` (15) cria um processo por certificado elegível → worker consulta o ADN → ingestão grava nota, evento e arquivos → NSU central avança.
2. **Conferência:** analista abre a nota → compara tributos (calculado × XML) → grava status, observação, prioridade → histórico.
3. **Exportação:** filtros da tela → ZIP (XML/PDF) ou planilha de conferência, sem canceladas/substituídas.
4. **Cadastro:** certificado (autocadastro identifica a empresa pelo CNPJ do certificado) e contas por convite.

## Invariantes e regras de negócio

| ID | Regra | Onde | Consequência / cuidado |
|---|---|---|---|
| REG-001 | Todo dado operacional é limitado ao `grupo` do usuário; sem correspondência → 404. Admin também fica no próprio grupo; só o admin geral vê todos. Grupo desativado bloqueia os usuários dele | `api/deps.py::require_*_grupo`, `get_current_usuario`; `admin.py::_escopo` | Rota nova precisa do filtro. Serviços aceitam `grupo=None` como "todos": nunca passe `None` vindo de rota de usuário |
| REG-002 | Usuário precisa estar ativo e com e-mail verificado. Só existem os papéis `admin` e `operador`. O JWT carrega `ver` = `usuarios.token_version`; trocar ou redefinir a senha incrementa a versão e derruba as sessões | `deps.py`, `core/security.py`, `contas_service.py` | JWT de usuário desativado, não verificado ou com versão antiga dá 401 |
| REG-003 | Login limitado no banco (`tentativas_acesso`, chaves com hash): IP real + e-mail 8 em 5 min, por conta 20 em 15 min, por IP 60 em 15 min; 2FA 10 em 15 min; sessão admin 5 em 5 min. Atrás do proxy, o IP é o último do `X-Forwarded-For`. Login com e-mail inexistente leva o mesmo tempo | `core/rate_limit.py` (`RateLimiterBanco`), `core/rede.py`, `routers/auth.py` | Vale entre réplicas e sobrevive a restart. Resposta 429 |
| REG-004 | Empresa tem CNPJ de 14 dígitos, único no banco inteiro (não por grupo) | `models.Empresa`, `empresas_service.py` | Autocadastro de CNPJ de outro grupo é recusado ("pertence a outro grupo") |
| REG-005 | Certificado elegível para consulta: ativo, empresa ativa do grupo, `storage_key` válido, senha salva e legível, não vencido | `consultas_service.list_certificados_elegiveis` | Vencido ou com senha ilegível sai da fila com log de aviso/erro |
| REG-006 | Não se cria processo para certificado com consulta pendente ou rodando, salvo `forcar` | `consultas_service._active_consulta_certificado_ids` | Verificação seguida de insert, sem constraint: duas requisições simultâneas podem duplicar (FIND-L03) |
| REG-007 | `monitoramento_config.grupo` é único; o agendador só enfileira grupos com monitor ativo e `proximo_ciclo_em` vencido | `consultas_service.enqueue_consultas_pendentes`, `main._run_consultas_scheduler` | Exceção no ciclo não derruba o agendador; o vigia avisa `agendador_parado` após `ALERTA_AGENDADOR_PARADO_MINUTOS` (30) sem volta concluída |
| REG-008 | NSU central por (empresa, certificado) só avança (`atualizar_ultimo_nsu` ignora valor menor). Início normal = confirmado − `NSU_LOOKBACK_NORMAL` (50) | `nsu_control_service.py` | "Confirmado" = max(central, maior `ultimo_nsu` das notas da empresa): ver ARCH-005 |
| REG-009 | Processo: `pendente → rodando → finalizado/erro/cancelado`. Cancelar um processo rodando marca `cancelado` e o motor para na próxima chamada ao ADN (`_processo_cancelado` antes de cada consulta) | `processos_service.cancelar_processo`, `legacy_processing_service._executar_baixa_empresa_compat` | A chamada HTTP em andamento termina; o NSU já avançado fica |
| REG-010 | Com `WORKER_DRY_RUN=true` o job só simula estados, sem chamar o ADN. Padrão do código: `True` | `worker/jobs.py::processar_job_simulado`, `config.py:30` | Produção precisa da variável valendo `false` |
| REG-011 | Lock único por (empresa, certificado), TTL de 1 h, renovado pelo heartbeat a cada 30 s. Job "rodando" sem heartbeat há `JOBS_TRAVADOS_MINUTOS` (15) volta para a fila e os locks do worker são apagados | `locks_repo.py`, `job_lease_service.py`, `jobs_repo.recuperar_jobs_travados` | Lock ocupado devolve o job sem espera (ARCH-010) |
| REG-012 | Identidade da nota: `(empresa_id, chave)` único. Evento: `(empresa_id, chave_evento)` único | `models.Nota`, `models.Evento`, `notas_repo.upsert_nota_by_chave` | Mesma NFS-e em duas empresas (emitente e tomador) = duas linhas |
| REG-013 | XML lido por nome local da tag (ignora namespace); datas e decimais com normalização tolerante | `legacy_ingestion_service.py`, `nfse_xml_parser.py` | XML sem chave conta erro de ingestão |
| REG-014 | `status_documento` vem só da estrutura do XML. Raiz `<NFSe>` = nota; raiz `<evento>` = evento. cStat 100/101/102/103 → autorizada; 107 → autorizada "MEI"; outro → `cstat_N`. Eventos e101101 e e105104 → cancelada; e105102 → substituida; e101103, e105105 e manifestações não mudam status; código desconhecido não muda e gera log. Nota com `chSubstda` marca a antiga como substituida. Prioridade cancelada > substituida > demais; reprocessar nunca rebaixa | `services/nfse_status_service.py::classificar_xml`, `legacy_ingestion_service::_status_final_nota/_aplicar_substituicao/_registrar_evento_xml` | Nunca usar `status_fila_manual` para mudar status fiscal. Testes com XML reais em `tests/fixtures/nfse_reais` |
| REG-015 † | Direção emitida/recebida: CNPJ da empresa comparado com prestador e tomador | `notas_service.classificar_direcao_nota` | Sem CNPJ → direção desconhecida |
| REG-016 † | Status da fila: manual vence; depois cancelada/substituída; alertas/divergências → divergente; sem alertas → correta | `operational_fields_service.calcular_status_fila` | Afeta painel, conferência e relatórios |
| REG-017 † | Prioridade manual vence a calculada; divergência com campo ausente = alta, outra divergência/alerta = média, resto = baixa | `calcular_prioridade_fila` | SLA usa a prioridade final |
| REG-018 | SLA (horas de alerta/perigo): alta 24/48, média 36/72, baixa 72/120; sem data = "Sem prazo" | `operational_fields_service.SLA_THRESHOLDS`, `calcular_sla_operacional` | Datetime sem fuso é tratado como UTC |
| REG-019 † | Simples Nacional vem preferencialmente do XML; códigos 1/2/3 → Não optante / MEI / Optante S.N. | `operational_fields_service` | API externa não sobrescreve o XML |
| REG-020 † | `observacao_interna` e `alertas_fiscais` são somente leitura no payload de conferência; valores calculados para a tela (`definir_valor_exibicao`) nunca são gravados | `schemas/notas.NotaConferenciaUpdate`, `operational_fields_service.definir_valor_exibicao` | API não forja alerta fiscal |
| REG-021 | Status de conferência aceito: `pendente`, `ok`, `corrigir`, `observacao` (normalizado para minúsculo) | `schemas/notas.py` | Outro valor → 422 |
| REG-022 | Nota com `responsavel` dá 409 sem `retificar=true` (em `PATCH /notas/{id}/conferencia` e `PUT /nfse/{id}`). Autor e data vêm do login; campos de autor no corpo e cabeçalhos `X-Responsavel`/`X-Usuario-Nome` são ignorados. Cada gravação com mudança vai para `notas_conferencia_historico` (`analise`/`retificacao`, campo de→para) | `notas_service.salvar_conferencia`, `routers/notas.py`, `routers/nfse_compat.py` | O histórico sobrevive ao arquivamento (nota_id nulo) e à exclusão do usuário |
| REG-023 † | Filtros têm aliases (`status`→`status_documento`, datas, CNPJs, conferência, SLA); `sort` só `recentes` ou `emissao` | `schemas/notas.NotasDownloadFiltros`, routers | Mudar nome exige compatibilidade no GET e no POST |
| REG-024 † | Download em lote sanitiza IDs (positivos, únicos), seleciona XML/PDF, deduplica nomes, filtra por grupo | `schemas.NotasDownloadLoteRequest`, `notas_download_service` | Arquivo ausente é contado em `X-Arquivos-Ausentes` |
| REG-025 † | PDF: oficial quando pedido e existente; senão espelho | `notas_download_service` | Nota pode não ter arquivo físico |
| REG-026 † | Retenções em `Decimal` com `ROUND_HALF_UP` em centavos; comparação com tolerância de 0,01 | `retencoes_calculo_service.calcular_retencoes_esperadas` | Float em regra fiscal gera divergência falsa |
| REG-027 | Regras LC116 vêm da aba `Planilha2` de `RETENCOES_REGRAS.xlsx` (flags SIM/NAO/DEPENDE). Exceção fixa em código: IRRF do subitem 7.04 = 1% | `retencoes_regras_service.py` (`IRRF_ALIQUOTAS_POR_SUBITEM`) | Trocar a planilha muda o cálculo sem mudar Python |
| REG-028 | Storage local ou R2; chaves normalizadas, sem `..`, caminho absoluto ou saída da raiz | `storage_service.normalize_storage_key`, `build_*_key` | Montar chave só pelos `build_*_key` |
| REG-029 | PFX guardado como bytes no storage; a senha fica cifrada (Fernet/MultiFernet) em `secrets`, referenciada por `senha_secret_ref` | `certificados_service`, `secrets_service` | Perder a `SECRETS_KEY` = perder as senhas. Rotação: `scripts/rotacionar_segredos` |
| REG-030 | DANFSe só pelo PHP (`generate.php`), com limite de tamanho e timeout; sem fallback Python | `danfse_service.py`, `backend/danfse` | PHP e Composer são dependências de produção (Dockerfile) |
| REG-031 | Arquivamento grava manifesto JSON no storage, confere o tamanho e só então apaga as notas anteriores ao ano (competência; emissão quando não há competência). Exige digitar "EXCLUIR ANTERIORES A {ano}" | `notas_archive_service.py`, `/admin/arquivamento` | Destrutivo: as linhas saem do banco |
| REG-032 † | CNPJ externo em cache por `(cnpj, fonte)` com expiração; Invertexto pode estar desligado | `cnpj_cache_service.py`, `cnpj_receita_service.py` | "Não consultado" não é erro da nota |
| REG-033 † | Subitem fiscal: usa o primeiro candidato que tenha regra na planilha; senão tenta `cTribMun`, `itemListaServico` e os demais; se nenhum tiver regra, mantém o primeiro para diagnóstico | `retencoes_regras_service.resolver_subitem_lc116`, `legacy_ingestion_service.extrair_codigo_servico_xml` | Evita falso "regra não encontrada" |
| REG-034 | A planilha é escolhida **uma vez, no import**: `data/RETENCOES_REGRAS.xlsx` se existir, senão a da raiz. Fica em cache por processo; resultado vazio não é cacheado e gera log de erro | `retencoes_regras_service.REGRAS_XLSX_PATH`, `carregar_regras_retencao` | Editar a planilha exige reiniciar. Em produção `data/` é o volume: ver ARCH-018 |
| REG-035 † | Código municipal simples de 3 dígitos não vira subitem LC116 (evita `501`→`5.01`) | `legacy_ingestion_service.extrair_codigo_servico_xml` | A função `normalizar_candidato_subitem` citada antes não existe mais; localizar a regra antes de mexer |
| REG-036 | Notas canceladas ou substituídas (qualquer caixa, também no masculino) nunca entram no ZIP nem na planilha; a listagem continua mostrando. Filtro em SQL, antes do limite; status `NULL` entra | `notas_repo._somente_exportaveis` | Filtrar explicitamente por cancelada numa exportação → 404 / planilha vazia |
| REG-037 | Cadastro só por convite: operador ou admin gera link para o próprio grupo (padrão 7 dias, usos limitados); a pessoa cria a conta e confirma com código de 6 dígitos por e-mail (Resend; HMAC com `JWT_SECRET`; 15 min; 5 tentativas) e entra como operador. Esqueci a senha usa o mesmo modelo | `contas_service.py`, `email_service.py`, `routers/auth.py` | Grupo sem empresa ativa não aceita cadastro (`usuarios.empresa_id` obrigatório). Trocar `JWT_SECRET` invalida códigos pendentes |
| REG-038 | Nenhuma listagem, contagem ou exportação corta em 5.000 sem avisar. Exportação usa `buscar_notas_exportacao` (mesmos filtros da tela, sem canceladas/substituídas); acima de `DOWNLOAD_LOTE_MAX_NOTAS` (10.000) ou `RELATORIO_MAX_NOTAS` (20.000) responde 400 pedindo para refinar | `notas_service.iterar_notas/buscar_notas_exportacao` | `listar_notas` ainda classifica até 5.000 notas em memória em alguns filtros (ARCH-002) |
| REG-039 | Monitor global = `empresa_ids` e `certificado_ids` nulos; as listas se combinam (empresa E certificado). Autocadastro nunca restringe: soma o certificado só às listas já restritas e, com o monitor parado, faz consulta avulsa. `GET /consultas/status` informa `monitor.escopo`. O vigia avisa empresa sem consulta finalizada há `ALERTA_EMPRESA_SEM_CONSULTA_HORAS` (6) | `consultas_service.iniciar_certificado_sem_substituir_monitor/descrever_monitor`, `operacao_service.empresas_sem_consulta` | Incidente de 01–06/10 (`historico/ANALISE_CANOPUS_...`) |
| REG-040 | Releitura profunda parte de antes do 1º dia do mês anterior (− `NSU_LOOKBACK_RECONCILIACAO`, 1000): (1) uma vez por noite na janela 19h–05h; (2) quando a empresa volta depois de `NSU_RELEITURA_APOS_HORAS_SEM_CONSULTA` (6) sem consulta finalizada; (3) por `POST /consultas/releitura-mes-anterior`. Nota com XML idêntico, NSU já registrado e arquivos completos é pulada (`notas_inalteradas`) | `nsu_control_service.planejar_inicio_consulta/voltou_de_parada`, `consultas_service.solicitar_releitura_mes_anterior` | É a rede de segurança para documentos pulados pelo NSU |
| REG-041 | Documento emitido antes de `NOTAS_DATA_CORTE` é descartado no download (o NSU avança sobre ele) | `adn_nfse_downloader.processar_documento`, `legacy_processing_service` (`data_corte_documentos`) | Releitura de período antigo não reimporta |
| REG-042 | Certificado vencido não entra na fila; erro de senha/certificado (`ValueError`) não é repetido | `consultas_service.list_certificados_elegiveis`, `adn_nfse_downloader.requisicao_json_com_retry` | Antes eram ~90 falhas por dia (até 06/10) |
| REG-043 | Rotas `/admin/*` exigem, além do JWT de admin, sessão admin aberta com senha + código TOTP (`POST /auth/admin/sessao`, 30 min, header `X-Admin-Token`). Sem sessão: 403 `admin_sessao_necessaria`. 2FA obrigatório por padrão (`ADMIN_2FA_OBRIGATORIO`). Com o 2FA ativo, o próprio admin não gera outro segredo (`/auth/2fa/iniciar` → 409): trocar de celular só pelo reset do admin geral. Alterações ficam em `auditoria_painel_admin` | `api/deps.py::require_admin_sessao/auditar_admin`, `routers/auth.py`, `core/totp.py`, `services/admin_seguranca_service.py` | A tabela `auditoria_admin` de produção é outra (schema diferente, vazia): não reutilizar. Reset de 2FA: `scripts/resetar_2fa_admin` (simular antes) |
| REG-044 | `GET /notas` pagina por cursor: ordem estável com desempate por `id`; `X-Next-Cursor` só quando a página veio cheia; OFFSET mantido para clientes antigos | `notas_repo.chaves_ordem/codificar_cursor/decodificar_cursor`, `notas_service.proximo_cursor`, `routers/notas.py` | Mudar `sort` ou as chaves invalida cursores em uso (o cliente recomeça) |
| REG-045 | "Limpar" erros no admin não apaga nada: grava `erros_vistos.visto_ate` por grupo (todos os grupos para o admin geral); `/admin/erros` mostra só o que veio depois | `admin.limpar_erros/_somente_nao_vistos`, `models.ErroVisto` | O admin geral marca todos os grupos (tabela `grupos` + `empresas.grupo`) e `__sem_grupo__` (empresa removida); o join usa `coalesce(empresas.grupo, '__sem_grupo__')` |
| REG-046 | Volumetria do admin respeita o grupo (`_escopo`); "por grupo" só para o admin geral | `volumetria_service.calcular` | Agregações em SQL; período pelo parâmetro `dias` |


## Ajustes do plano de carga — publicados no backend `4e4302c0` (15/10/2026)

- **REG-047:** ciclos automáticos com monitor ativo distribuem os jobs elegíveis pelo intervalo via `available_at`; todos continuam entrando na fila. Pedidos manuais/forçados e releituras avulsas são imediatos. A verificação de certificado já pendente/rodando permanece.
- **REG-003 (implementação):** a admissão grava só se a contagem dentro da janela permitir; não apaga linhas da chave em cada tentativa. Postgres serializa pela chave com advisory lock e usa pool/tempos limitados. Em falha, o contador em memória inclui tentativas feitas com banco saudável; a reserva continua sendo por processo. Limites e respostas HTTP não mudam.

> Seção do plano de carga verificada em 15/10/2026 sobre `2d05450f` + alterações locais; o restante mantém o carimbo original.
