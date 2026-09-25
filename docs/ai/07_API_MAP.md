# Mapa de APIs e integrações

Legenda: `JWT` = usuário autenticado; `ADM` = `require_admin`; `OP` = operador/admin; `KEY` = `X-API-Key`; `TEN` = objeto filtrado pelo grupo do usuário. Respostas de erro são normalmente `HTTPException` 400/401/403/404/409/422/500; os detalhes específicos estão no router citado.

## Administração e autenticação

| Método | Rota | Arquivo/função | Auth | Entrada → saída | Consumidor |
|---|---|---|---|---|---|
| POST | `/auth/local` | `auth.py::login_local` | local | credenciais → JWT local | utilitário/dev |
| POST | `/auth/login` | `auth.py::login` | público + rate limit | email/senha → token | `Login.tsx`, `api.login` |
| GET | `/auth/me` | `auth.py::me` | JWT | claims → usuário/grupo | `useAuth` |
| GET | `/auth/grupos` | `auth.py::listar_grupos` | ADM | nenhum → grupos ativos | Admin; apesar do nome, não é público |
| POST | `/auth/usuarios` | `auth.py::criar_usuario` | KEY | dados de usuário → usuário | provisionamento |
| GET | `/admin/overview` | `admin.py::overview` | ADM | nenhum → indicadores | Admin |
| GET | `/admin/acessos` | `admin.py::acessos` | ADM | filtros/paginação → acessos | Admin |
| GET | `/admin/usuarios` | `admin.py::usuarios` | ADM | filtros → usuários | Admin |
| PATCH | `/admin/usuarios/{usuario_id}` | `admin.py::atualizar_usuario` | ADM | dados/papel/ativo → usuário | Admin |
| DELETE | `/admin/usuarios/{usuario_id}` | `admin.py::excluir_usuario` | ADM | ID → 204/erro | Admin |
| GET | `/admin/grupos` | `admin.py::listar_grupos` | ADM | → grupos | Admin |
| POST | `/admin/grupos` | `admin.py::criar_grupo` | ADM | nome/código → grupo | Admin |
| PATCH | `/admin/grupos/{grupo_id}` | `admin.py::editar_grupo` | ADM | campos → grupo | Admin |
| DELETE | `/admin/grupos/{grupo_id}` | `admin.py::excluir_grupo` | ADM | ID → 204/erro | Admin |
| POST | `/admin/usuarios/{usuario_id}/redefinir-senha` | `admin.py::redefinir_senha` | ADM | nova senha → confirmação | Admin |
| GET | `/admin/erros` | `admin.py::erros` | ADM | filtros → logs/erros | Admin |
| GET | `/admin/arquivamento` | `admin.py::status_arquivamento` | ADM | → status | Admin |
| POST | `/admin/arquivamento` | `admin.py::executar_arquivamento` | ADM | ano/opções → manifesto/contagem | Admin; destrutivo |

## Empresas, certificados e infraestrutura

| Método | Rota | Arquivo/função | Auth | Entrada → saída |
|---|---|---|---|---|
| POST | `/empresas` | `empresas.py` | JWT/OP | nome, CNPJ, ambiente → Empresa |
| GET | `/empresas` | `empresas.py` | JWT | filtros/paginação → empresas TEN |
| GET | `/empresas/resumo-operacional` | `empresas.py` | JWT | filtros → resumo por empresa |
| GET/PATCH/DELETE | `/empresas/{empresa_id}` | `empresas.py` | JWT/OP/TEN | ID + body PATCH → DTO/204 |
| POST | `/certificados` | `certificados.py::create_certificado_compat` | JWT/OP | body legado → certificado |
| POST | `/certificados/upload` | `certificados.py::upload_certificado` | JWT/OP | multipart PFX/senha → metadata |
| POST | `/certificados/autocadastrar` | `certificados.py::autocadastrar_certificado` | JWT/OP | PFX/empresa → certificado |
| POST | `/empresas/{empresa_id}/certificados` | `certificados.py::create_certificado_empresa` | JWT/OP/TEN | body/multipart → certificado |
| GET | `/empresas/{empresa_id}/certificados` | `certificados.py::list_certificados_empresa` | JWT/TEN | → certificados sem segredo |
| GET | `/certificados` | `certificados.py::list_certificados` | JWT | filtros → certificados TEN |
| PUT | `/certificados/{certificado_ref}` | `certificados.py::update_certificado_compat` | JWT/OP | body legado → DTO |
| GET | `/certificados/{certificado_id}` | `certificados.py::get_certificado` | JWT/TEN | → metadata |
| POST | `/certificados/{certificado_id}/testar` | `certificados.py::testar_certificado` | JWT/TEN | → resultado conexão |
| PATCH | `/certificados/{certificado_id}` | `certificados.py::update_certificado` | JWT/OP/TEN | nome/ativo → DTO |
| POST | `/certificados/{certificado_id}/senha` | `certificados.py::salvar_senha_certificado` | JWT/OP/TEN | senha → Secret cifrado |
| GET | `/certificados/{certificado_id}/senha/status` | `certificados.py::status_senha_certificado` | JWT/TEN | → configurada |
| DELETE | `/certificados/{certificado_id}/senha` | `certificados.py::remover_senha` | JWT/OP/TEN | → removida |
| POST | `/certificados/{certificado_id}/testar-senha-salva` | `certificados.py::testar_senha_salva` | JWT/TEN | → teste |
| DELETE | `/certificados/{certificado_ref}` | `certificados.py::delete_certificado` | JWT/OP/TEN | ref → 204/erro |
| GET | `/storage/health` | `storage.py::health` | JWT/ADM | → backend/raiz |
| POST | `/storage/test-write` | `storage.py::test_write` | JWT/ADM | bytes/chave → resultado |
| GET | `/storage/test-read` | `storage.py::test_read` | JWT/ADM | chave → bytes/meta |
| GET | `/storage/list` | `storage.py::list_storage` | JWT/ADM | prefix → chaves |
| GET | `/db/health` | `db_health.py` | JWT/ADM | → conexão/tabelas |

## Consulta, NSU e execução

| Método | Rota | Arquivo/função | Auth | Entrada → saída |
|---|---|---|---|---|
| GET | `/consultas/status` | `consultas.py` | JWT | grupo/limite → monitor/processos |
| POST | `/consultas/iniciar` | `consultas.py` | JWT/OP | empresa/cert/NSU/opções → processo/job |
| POST | `/consultas/desativar` | `consultas.py` | JWT/OP | grupo/filtros → cancelamento |
| GET | `/empresas/{empresa_id}/nsu` | `nsu.py` | JWT/TEN | ID → cursor NSU |
| GET | `/nsu/status` | `nsu.py` | JWT | filtros → estados por empresa/cert |
| POST | `/processos` | `processos.py` | JWT/OP | options → Processo + Job |
| GET | `/processos` | `processos.py` | JWT | filtros/paginação → processos TEN |
| GET | `/processos/{processo_id}` | `processos.py` | JWT/TEN | → detalhe |
| GET | `/processos/{processo_id}/arquivos` | `processos.py` | JWT/TEN | → arquivos do processo |
| GET | `/processos/{processo_id}/notas` | `processos.py` | JWT/TEN | filtros → notas |
| GET | `/processos/{processo_id}/summary` | `processos.py` | JWT/TEN | → resumo |
| POST | `/processos/{processo_id}/cancelar` | `processos.py` | JWT/OP/TEN | → estado cancelado |
| GET | `/processos/{processo_id}/jobs` | `processos.py` | JWT/TEN | → jobs |
| GET | `/execucoes` | `execucoes.py` | JWT | filtros → execuções/contagens |
| GET | `/logs` | `logs.py` | JWT | filtros → logs |
| GET | `/processos/{processo_id}/logs` | `logs.py` | JWT/TEN | → logs do processo |

## Notas, eventos e arquivos

| Método | Rota | Arquivo/função | Auth | Entrada → saída |
|---|---|---|---|---|
| GET | `/notas` | `notas.py::list_notas` | JWT | filtros, `limit/offset` → `NotaListItem[]` |
| GET | `/notas/todas` | `notas.py::list_todas_notas` | JWT | filtros → todas as direções |
| GET | `/notas/emitidas` | `notas.py::list_notas_emitidas` | JWT | filtros → emitidas |
| GET | `/notas/recebidas` | `notas.py::list_notas_recebidas` | JWT | filtros → recebidas |
| POST | `/notas/download-lote` | `notas.py::download_lote_notas` | JWT | `NotasDownloadLoteRequest` → ZIP |
| GET | `/notas/download-lote` | `notas.py::download_lote_notas_get` | JWT | query filters → ZIP |
| GET | `/notas/resumo` | `notas.py::get_notas_resumo` | JWT | filtros → contagens/valores |
| GET | `/notas/chave/{chave}` | `notas.py::get_nota_por_chave` | JWT/TEN | chave → detalhe |
| GET | `/notas/{nota_id}` | `notas.py::get_nota` | JWT/TEN | ID → detalhe |
| GET | `/notas/{nota_id}/eventos` | `notas.py::list_eventos_nota` | JWT/TEN | → eventos |
| GET | `/notas/{nota_id}/tributos-comparativo` | `notas.py::get_tributos_comparativo` | JWT/TEN | → informado/calculado |
| PATCH | `/notas/{nota_id}/conferencia` | `notas.py::patch_conferencia_nota` | JWT/OP/TEN | status/obs/retificar → nota |
| GET | `/notas/{nota_id}/arquivos` | `notas.py::list_arquivos_nota` | JWT/TEN | → arquivos |
| GET | `/eventos` | `eventos.py` | JWT | filtros/nota → eventos TEN |
| GET | `/arquivos/{arquivo_id}/download` | `arquivos.py::download_arquivo` | JWT/TEN | ID → FileResponse |
| GET | `/arquivos/{arquivo_id}/view` | `arquivos.py::visualizar_arquivo` | JWT/TEN | → inline arquivo |
| GET | `/arquivos/{arquivo_id}/preview` | `arquivos.py::visualizar_arquivo` | JWT/TEN | alias inline |
| GET | `/arquivos/{arquivo_id}/visualizar` | `arquivos.py::visualizar_arquivo` | JWT/TEN | alias inline |
| GET | `/nfse` | `nfse_compat.py` | JWT | contrato legado → lista compatível |
| GET | `/nfse/{nota_id}` | `nfse_compat.py` | JWT/TEN | → detalhe legado |
| PUT | `/nfse/{nota_id}` | `nfse_compat.py` | JWT/OP/TEN | body legado → nota |
| GET | `/nfse/{nota_id}/documentos` | `nfse_compat.py` | JWT/TEN | → documentos |

## Relatório, CNPJ, saúde e DANFSe

| Método | Rota | Arquivo/função | Auth | Entrada → saída |
|---|---|---|---|---|
| POST | `/relatorios/conferencia` | `relatorios.py::exportar_conferencia` | JWT | filtros → XLSX |
| GET | `/cnpj/status` | `cnpj.py::status_cnpj` | JWT | → provider/cache |
| GET | `/cnpj/{cnpj}` | `cnpj.py::consultar_cnpj` | JWT | CNPJ → dados/cache |
| GET | `/health` | `health.py` | público | → liveness |
| GET | `/metrics` | `health.py` | público/config | → contadores Prometheus |
| POST | `/api/danfse/gerar` | `danfse.py::gerar_danfse` | JWT | multipart XML (até limite) → PDF |

## Integrações externas e chamadas não-HTTP

- ADN/NFS-e Nacional: `adn_nfse_downloader.py`, requests com certificado PKCS#12, NSU e endpoints definidos no legado. Falhas de rede/certificado viram erro do `Job` e log.
- Receita/Invertexto: `cnpj_enrichment_service.py`, `cnpj_cache_service.py` e `portal_support_service.py`; cacheia payload/status/expiração e pode operar desabilitado.
- Cloudflare R2: `storage_service.py` via boto3 quando `STORAGE_BACKEND=r2`; local usa `STORAGE_ROOT`.
- PHP/Composer: `danfse_service.py` chama `backend/danfse/generate.php` em subprocesso, com timeout.
- Webhook opcional: `backend/app/core/observability.py` envia eventos JSON com timeout de 3s.

## Consumidores frontend e divergências contratuais

`src/lib/api.ts` é a matriz de consumo: cada método monta rota, query, body e headers. A página `CriarConta` chama `POST /auth/criar-conta`, mas o backend deste snapshot não registra essa rota (bug de integração confirmado). O método `listarGruposPublicos` chama `GET /auth/grupos`, porém o backend exige admin. Antes de alterar um caminho, pesquise em `api.ts`, hooks e componentes para atualizar tratamento de erro, invalidação React Query e download.
