# Índice de arquivos versionados

> Gerado por `docs/ai/gerado/gerar_indices.py` em 2026-10-15 sobre o commit `12cf6026`. Não editar à mão.


350 arquivos (fora `backend/danfse/vendor/`, que é instalado pelo Composer).


## `./`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `.dockerignore` |  |  |
| `.env.docker.example` |  |  |
| `.env.example` |  |  |
| `.gitignore` |  |  |
| `CLAUDE.md` | 9 |  |
| `Dockerfile` |  |  |
| `README.md` | 240 |  |
| `RETENCOES_REGRAS.xlsx` |  |  |
| `adn_nfse_downloader.py` | 972 | ADN NFS-e Downloader |
| `alembic.ini` | 7 |  |
| `docker-compose.yml` | 32 |  |
| `empresas.example.json` | 21 |  |
| `iniciar_local.py` | 63 | Executa consultas reais com persistencia exclusivamente local. |
| `requirements-dev.txt` | 4 |  |
| `requirements.txt` | 14 |  |

## `.github/workflows/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `ci.yml` | 30 |  |

## `backend/app/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `__init__.py` | 1 |  |
| `main.py` | 317 |  |

## `backend/app/api/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `__init__.py` | 1 |  |
| `deps.py` | 176 |  |

## `backend/app/api/routers/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `__init__.py` | 1 |  |
| `admin.py` | 439 |  |
| `arquivos.py` | 71 |  |
| `auth.py` | 272 |  |
| `certificados.py` | 496 |  |
| `cnpj.py` | 34 |  |
| `consultas.py` | 63 |  |
| `danfse.py` | 36 |  |
| `db_health.py` | 21 |  |
| `empresas.py` | 89 |  |
| `eventos.py` | 45 |  |
| `execucoes.py` | 115 |  |
| `health.py` | 50 |  |
| `logs.py` | 77 |  |
| `nfse_compat.py` | 226 |  |
| `notas.py` | 694 |  |
| `nsu.py` | 98 |  |
| `processos.py` | 157 |  |
| `relatorios.py` | 40 |  |
| `storage.py` | 59 |  |

## `backend/app/core/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `__init__.py` | 1 |  |
| `config.py` | 190 |  |
| `observability.py` | 76 |  |
| `php_runtime.py` | 63 | Localiza o PHP e habilita as extensoes exigidas pelo DANFSe oficial. |
| `rate_limit.py` | 82 |  |
| `rede.py` | 35 | IP de quem fez a requisicao, mesmo atras do proxy do Railway. |
| `security.py` | 102 |  |
| `tempo.py` | 43 | Datas de negocio no fuso do escritorio. |
| `totp.py` | 54 | Codigos de verificacao em duas etapas (TOTP, RFC 6238), compativeis com |

## `backend/app/db/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `__init__.py` | 1 |  |
| `base.py` | 5 |  |
| `models.py` | 560 |  |
| `session.py` | 346 |  |

## `backend/app/db/migrations/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `__init__.py` | 0 |  |
| `env.py` | 30 | Ambiente do Alembic. |
| `script.py.mako` |  |  |
| `util.py` | 22 | Verificacoes para revisoes idempotentes do Alembic. |

## `backend/app/db/migrations/versions/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `0001_baseline.py` | 29 | Linha de base do versionamento de esquema. |
| `0002_historico_conferencia.py` | 46 | Historico da analise fiscal (notas_conferencia_historico). |
| `0003_contas_convite.py` | 40 | Contas por convite: versao de token, verificacao de e-mail e fim do papel leitura. |
| `0004_seguranca_admin.py` | 66 | Seguranca: limite de tentativas no banco, 2FA de administrador e auditoria do admin. |
| `0005_erros_vistos.py` | 33 | Erros ja vistos no painel admin (botao "Limpar" sem apagar o historico). |

## `backend/app/repositories/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `__init__.py` | 1 |  |
| `arquivos_repo.py` | 104 |  |
| `certificados_repo.py` | 59 |  |
| `empresas_repo.py` | 47 |  |
| `jobs_repo.py` | 177 |  |
| `locks_repo.py` | 95 |  |
| `logs_repo.py` | 31 |  |
| `notas_repo.py` | 356 |  |
| `processos_repo.py` | 89 |  |
| `secrets_repo.py` | 32 |  |
| `usuarios_repo.py` | 29 |  |

## `backend/app/schemas/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `__init__.py` | 1 |  |
| `arquivos.py` | 50 |  |
| `auth.py` | 110 |  |
| `certificados.py` | 56 |  |
| `consultas.py` | 92 |  |
| `empresas.py` | 106 |  |
| `jobs.py` | 24 |  |
| `notas.py` | 364 |  |
| `processos.py` | 56 |  |
| `secrets.py` | 13 |  |
| `usuarios.py` | 20 |  |

## `backend/app/scripts/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `__init__.py` | 0 |  |
| `aplicar_seguranca_rls.py` | 208 |  |
| `arquivar_notas_antigas.py` | 28 |  |
| `auditar_incidencia_iss.py` | 25 |  |
| `auditar_integridade_certificados.py` | 131 |  |
| `auditar_rls_supabase.py` | 88 |  |
| `backfill_documentos_partes.py` | 79 | Preenche CNPJ/CPF de prestador e tomador ausentes a partir do XML salvo. |
| `backup_supabase_nfse.ps1` |  |  |
| `corrigir_integridade_certificados.py` | 78 |  |
| `corrigir_simples_pendentes_online.py` | 166 |  |
| `corrigir_status_fiscal.py` | 430 | Corrige o status fiscal gravado pela classificacao antiga (por palavras). |
| `db_migration_common.py` | 168 |  |
| `diagnosticar_banco.py` | 41 |  |
| `diagnosticar_nsu_certificado.py` | 103 |  |
| `enfileirar_reprocessamento_certificados.py` | 75 |  |
| `exportar_openapi.py` | 28 | Exporta o contrato da API (OpenAPI) para o frontend gerar os tipos TypeScript. |
| `gerar_espelhos_ausentes.py` | 106 | Gera PDFs espelho ausentes a partir dos XMLs ja armazenados. |
| `importar_base_cnpj_receita.py` | 216 |  |
| `limpar_orfaos_storage.py` | 103 | Acha (e, com --aplicar, apaga) arquivos do storage que nenhum registro usa. |
| `listar_consultas_simples_pendentes.py` | 119 |  |
| `migrar_banco.py` | 15 |  |
| `migrar_rbac.py` | 76 |  |
| `migrar_sqlite_para_postgres.py` | 133 |  |
| `migrar_storage_para_r2.py` | 82 |  |
| `promover_usuarios_locais.py` | 117 |  |
| `r2_common.py` | 29 |  |
| `recalcular_alertas_fiscais.py` | 260 | Recalcula os alertas fiscais (subitem LC116, ISS retido, valor liquido) |
| `reconciliar_notas_certificados.py` | 216 |  |
| `reconciliar_storage.py` | 46 | Compara referencias de XML/PDF no banco com os objetos existentes no storage. |
| `regenerar_carimbos_pdfs.py` | 135 | Regenera PDFs espelho de notas canceladas ou substituidas. |
| `regenerar_espelhos_competencia.py` | 161 | Regenera exclusivamente PDFs espelho de uma competência e certificado. |
| `resetar_2fa_admin.py` | 42 | Zera a verificacao em duas etapas de um administrador que perdeu o celular. |
| `rotacionar_segredos.py` | 53 | Recifra as senhas de certificado com a chave nova de SECRETS_KEY. |
| `sincronizar_cnpjs_portal.py` | 189 |  |
| `sincronizar_eventos_lote.py` | 202 | Varre notas autorizadas e consulta seus eventos no ADN. |
| `status_reprocessamento_certificados.py` | 59 |  |
| `testar_r2.py` | 31 |  |
| `validar_migracao_postgres.py` | 130 |  |

## `backend/app/services/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `__init__.py` | 1 |  |
| `admin_seguranca_service.py` | 103 | Verificacao em duas etapas do administrador, sessao do painel e auditoria. |
| `arquivos_service.py` | 56 |  |
| `auth_service.py` | 47 |  |
| `certificado_metadata_service.py` | 124 |  |
| `certificados_service.py` | 569 |  |
| `cnpj_cache_service.py` | 140 |  |
| `cnpj_enrichment_service.py` | 128 |  |
| `cnpj_receita_service.py` | 214 |  |
| `consultas_service.py` | 500 |  |
| `contas_service.py` | 325 | Contas por convite, confirmacao de e-mail e redefinicao de senha por codigo. |
| `danfse_service.py` | 109 |  |
| `email_service.py` | 78 | E-mail transacional pelo Resend (codigo de cadastro e de redefinicao de senha). |
| `empresas_service.py` | 47 |  |
| `eventos_sync_service.py` | 277 | Consulta os eventos de uma NFS-e no ADN e aplica na nota ja importada. |
| `job_lease_service.py` | 61 | Heartbeat independente da ingestao, durante toda a execucao real do job. |
| `legacy_ingestion_service.py` | 1655 |  |
| `legacy_processing_service.py` | 936 |  |
| `locks_service.py` | 46 |  |
| `logs_service.py` | 103 |  |
| `nfse_status_service.py` | 173 | Classificacao fiscal de um XML do ADN: nota ou evento, e qual o seu status. |
| `nfse_xml_parser.py` | 760 |  |
| `notas_archive_service.py` | 168 |  |
| `notas_download_service.py` | 300 |  |
| `notas_service.py` | 953 |  |
| `nsu_control_service.py` | 247 |  |
| `operacao_service.py` | 205 | Saude da operacao: estado da fila, vigia com aviso e retencao de logs. |
| `operational_fields_service.py` | 312 |  |
| `portal_support_service.py` | 1453 |  |
| `processos_service.py` | 134 |  |
| `retencoes_calculo_service.py` | 297 |  |
| `retencoes_regras_service.py` | 182 |  |
| `secrets_service.py` | 66 |  |
| `storage_naming_service.py` | 54 |  |
| `storage_service.py` | 361 |  |
| `valor_liquido_backfill_service.py` | 47 |  |
| `volumetria_service.py` | 192 | Numeros agregados para a secao Volumetria do painel administrativo. |

## `backend/app/worker/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `__init__.py` | 1 |  |
| `jobs.py` | 261 |  |
| `scheduler.py` | 49 |  |
| `worker.py` | 90 |  |

## `backend/danfse/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `README.md` | 117 |  |
| `composer.json` | 42 |  |
| `composer.lock` |  |  |
| `generate.php` | 49 |  |

## `backend/danfse/assets/fonts/ttf/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `arial-bold.ttf` |  |  |
| `arial.ttf` |  |  |
| `ms-sans-serif.ttf` |  |  |

## `backend/danfse/assets/logos/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `nfse.png` |  |  |

## `backend/danfse/assets/xml/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `teste.xml` |  |  |

## `backend/danfse/src/Danfse/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `DanfseGenerator.php` | 360 |  |
| `Formatter.php` | 192 |  |
| `XmlToArray.php` | 95 |  |

## `backend/danfse/src/Danfse/Config/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `DanfseConfig.php` | 50 |  |
| `MunicipalityBranding.php` | 34 |  |

## `backend/danfse/src/Danfse/Data/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `Municipios.php` | 5593 |  |

## `backend/danfse/src/Danfse/Dto/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `AtvEvento.php` | 22 |  |
| `CServ.php` | 13 |  |
| `Destinatario.php` | 21 |  |
| `Dps.php` | 11 |  |
| `DpsIBSCBS.php` | 15 |  |
| `DpsIBSCBSTrib.php` | 10 |  |
| `DpsIBSCBSValores.php` | 10 |  |
| `Emitente.php` | 20 |  |
| `Endereco.php` | 15 |  |
| `EnderecoEmitente.php` | 16 |  |
| `EnderecoExterior.php` | 11 |  |
| `EnderecoNacional.php` | 11 |  |
| `GCBSTot.php` | 10 |  |
| `GIBSMunTot.php` | 10 |  |
| `GIBSTot.php` | 12 |  |
| `GIBSUFTot.php` | 10 |  |
| `GItemPed.php` | 11 |  |
| `GibsCbs.php` | 12 |  |
| `IBSCBS.php` | 13 |  |
| `IBSCBSFed.php` | 12 |  |
| `IBSCBSMun.php` | 12 |  |
| `IBSCBSUf.php` | 12 |  |
| `IBSCBSValores.php` | 14 |  |
| `Imovel.php` | 19 |  |
| `InfDPS.php` | 25 |  |
| `InfNFSe.php` | 30 |  |
| `InfoCompl.php` | 14 |  |
| `Intermediario.php` | 22 |  |
| `LocPrest.php` | 11 |  |
| `NFSe.php` | 11 |  |
| `Obra.php` | 11 |  |
| `PisCofins.php` | 16 |  |
| `Prestador.php` | 19 |  |
| `RegTrib.php` | 12 |  |
| `Servico.php` | 14 |  |
| `Subst.php` | 12 |  |
| `Tomador.php` | 22 |  |
| `TotCIBS.php` | 12 |  |
| `TotTrib.php` | 14 |  |
| `TotTribPercent.php` | 12 |  |
| `TotTribValues.php` | 12 |  |
| `TribFederal.php` | 15 |  |
| `TribMunicipal.php` | 18 |  |
| `Tributacao.php` | 12 |  |
| `VDescCondIncond.php` | 12 |  |
| `VServPrest.php` | 11 |  |
| `Valores.php` | 14 |  |
| `ValoresNFSe.php` | 15 |  |

## `backend/danfse/src/Danfse/Enums/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `OpSimpNac.php` | 26 |  |
| `RegApTribSN.php` | 25 |  |
| `RegEspTrib.php` | 33 |  |
| `TipoAmbiente.php` | 22 |  |
| `TpRetISSQN.php` | 25 |  |
| `TribISSQN.php` | 27 |  |

## `backend/danfse/src/Danfse/Exception/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `InvalidXmlException.php` | 9 |  |
| `NfseException.php` | 11 |  |

## `backend/danfse/src/Danfse/Pdf/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `GradeCanvas.php` | 248 |  |

## `backend/danfse/src/Danfse/Template/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `DanfseTemplate.php` | 597 |  |
| `danfse.php` | 976 |  |

## `backend/danfse/tests/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `run.php` | 73 |  |

## `data/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `RETENCOES_REGRAS.xlsx` |  |  |
| `consultas_auto.json` | 20 |  |

## `docs/ai/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `00_LEIA_PRIMEIRO.md` | 62 |  |
| `API.md` | 58 |  |
| `ARCHITECTURE_CURRENT.md` | 135 |  |
| `CHANGELOG.md` | 45 |  |
| `CHANGE_IMPACT.md` | 73 |  |
| `DATABASE.md` | 80 |  |
| `FINDINGS.md` | 100 |  |
| `OPERATIONS.md` | 139 |  |
| `PROJECT_CONTEXT.md` | 93 |  |
| `SECURITY.md` | 60 |  |

## `docs/ai/DECISIONS/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `ADR-0001-isolamento-por-grupo.md` | 26 |  |
| `ADR-0002-esquema-alembic-idempotente.md` | 21 |  |
| `ADR-0003-nsu-confirmado-no-fim-do-job.md` | 20 |  |
| `ADR-0004-status-fiscal-pela-estrutura-do-xml.md` | 14 |  |
| `ADR-0005-contas-por-convite.md` | 17 |  |
| `ADR-0006-processo-unico-api-worker-agendador.md` | 24 |  |
| `ADR-0007-canceladas-fora-das-exportacoes.md` | 14 |  |
| `ADR-0008-pdf-espelho-php.md` | 16 |  |
| `ADR_TEMPLATE.md` | 49 |  |
| `README.md` | 16 |  |

## `docs/ai/FERRAMENTAS/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `COMANDOS.md` | 67 |  |
| `INSTALACAO.md` | 82 |  |
| `LIMITACOES.md` | 23 |  |
| `MCP.md` | 55 |  |
| `README.md` | 54 |  |
| `VALIDACAO.md` | 27 |  |

## `docs/historico/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `ANALISE_CANOPUS_CONSULTAS_2026-10-06.md` | 84 |  |
| `ANALISE_DOCUMENTACAO_2026-10-06.md` | 70 |  |
| `AUDITORIA_BACKEND_2026-10-08.md` | 220 |  |
| `DEPLOY_PRODUCAO.md` | 27 |  |
| `MONITORAMENTO_RAILWAY_2026-10-06.md` | 45 |  |
| `PENDENCIAS_BACKEND_PORTAL.md` | 46 |  |
| `POS_DEPLOY_2026-10-06.md` | 55 |  |
| `README.md` | 18 |  |
| `REVISAO_TECNICA_MAPA.md` | 471 |  |
| `SEGURANCA_CERTIFICADOS_2026-10-06.md` | 62 |  |

## `docs/historico/ai-snapshot-2026-09-15/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `01_PROJECT_OVERVIEW.md` | 63 |  |
| `02_ARCHITECTURE.md` | 93 |  |
| `03_FILE_MAP.md` | 680 |  |
| `04_FUNCTION_MAP.md` | 1120 |  |
| `05_DATA_FLOW.md` | 116 |  |
| `06_DATABASE_MAP.md` | 70 |  |
| `07_API_MAP.md` | 145 |  |
| `08_BUSINESS_RULES.md` | 46 |  |
| `09_DEPENDENCY_MAP.md` | 89 |  |
| `10_RISK_REGISTER.md` | 31 |  |
| `11_BUGS_AND_TECH_DEBT.md` | 47 |  |
| `12_CHANGE_IMPACT_MAP.md` | 75 |  |
| `13_CRITICAL_FILES.md` | 42 |  |
| `14_AI_HANDOFF.md` | 106 |  |
| `15_MENTAL_MAP.md` | 81 |  |
| `16_AGENT_QUICK_START.md` | 84 |  |

## `tests/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `conftest.py` | 67 |  |
| `test_admin_volumetria_erros.py` | 123 | Painel admin: "Limpar" erros sem apagar historico e numeros da Volumetria. |
| `test_adn_data_cutoff.py` | 46 |  |
| `test_auth_account.py` | 101 |  |
| `test_certificados_contagem.py` | 26 |  |
| `test_classificacao_status_nfse.py` | 330 | Classificacao de status da NFS-e com XML reais do ADN (mascarados). |
| `test_cnpj_receita.py` | 118 |  |
| `test_cnpj_receita_cache.py` | 77 |  |
| `test_concorrencia_sqlite.py` | 438 | Regressao dos incidentes de concorrencia local (SQLite). |
| `test_conferencia_auditavel.py` | 173 | Analise fiscal auditavel: trava de retificacao, autor do login e historico. |
| `test_conferencia_nao_grava_calculados.py` | 76 | Salvar a conferencia nao grava valores calculados so para a tela. |
| `test_consulta_adn_confiavel.py` | 207 | Fase 3: consulta ao ADN sem perder documentos e sem travar a fila. |
| `test_consultas_api.py` | 905 |  |
| `test_contas_e_grupos.py` | 319 | Fase 4: contas por convite com codigo por e-mail e grupos separados. |
| `test_correcao_analise_fiscal.py` | 363 |  |
| `test_corrigir_status_fiscal.py` | 194 | Script de correcao do status fiscal gravado pela classificacao antiga. |
| `test_cors.py` | 70 |  |
| `test_danfse_integration.py` | 40 |  |
| `test_danfse_nacional_service.py` | 21 |  |
| `test_db_migration_scripts.py` | 181 |  |
| `test_db_startup.py` | 23 |  |
| `test_eventos_fora_do_indice.py` | 126 | Eventos que o indice unico do motor legado esconde. |
| `test_eventos_sync.py` | 320 | Sincronizacao de eventos por nota (POST /notas/{id}/sincronizar-eventos). |
| `test_http_security.py` | 36 |  |
| `test_incidencia_search.py` | 8 |  |
| `test_legacy_e2220.py` | 66 |  |
| `test_legacy_log_privacy.py` | 53 |  |
| `test_limites_exportacao.py` | 188 | Fase 5: nada de corte silencioso em 5.000 notas (painel, listas, ZIP, planilha). |
| `test_logs_security.py` | 43 |  |
| `test_monitor_e_operacao.py` | 193 | Monitor automatico de consultas e vigia de empresas sem consulta. |
| `test_nfse_xml_parser.py` | 286 |  |
| `test_notas_archive_service.py` | 90 |  |
| `test_notas_download_lote.py` | 484 |  |
| `test_notas_recentes.py` | 496 |  |
| `test_notas_tipo_direcao.py` | 171 |  |
| `test_operational_fields.py` | 584 |  |
| `test_paginacao_cursor.py` | 96 | Paginacao por cursor em /notas (X-Next-Cursor): continua de onde a pagina |
| `test_portal_support_endpoints.py` | 1201 |  |
| `test_prestador_pessoa_fisica.py` | 49 |  |
| `test_rbac.py` | 71 |  |
| `test_releitura_mes_anterior.py` | 158 | Releitura desde o 1o dia do mes anterior: na volta de uma parada e a pedido. |
| `test_retencoes_regras.py` | 266 |  |
| `test_security_config.py` | 74 |  |
| `test_seguranca_admin.py` | 195 | Brechas fechadas em 15/10/2026: limite de tentativas no banco, 2FA e sessao |
| `test_sincronizar_cnpjs_portal.py` | 22 |  |
| `test_storage_r2.py` | 198 |  |

## `tests/fixtures/nfse_reais/`

| Arquivo | Linhas | Descrição (docstring) |
|---|---:|---|
| `evento_e101101_cancelamento.xml` |  |  |
| `evento_e101103_solicitacao_analise_fiscal.xml` |  |  |
| `evento_e105102_cancelamento_por_substituicao.xml` |  |  |
| `evento_e105104_cancelamento_deferido.xml` |  |  |
| `evento_e203202_confirmacao_tomador.xml` |  |  |
| `evento_e203206_rejeicao_tomador.xml` |  |  |
| `nota_cstat100.xml` |  |  |
| `nota_cstat101_substituta.xml` |  |  |
| `nota_cstat102_decisao_judicial.xml` |  |  |
| `nota_cstat103_avulsa.xml` |  |  |
| `nota_cstat107_mei.xml` |  |  |
| `nota_substituta_servico_de_eventos.xml` |  |  |
