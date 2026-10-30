# Índice de rotas HTTP

> Gerado por `docs/ai/gerado/gerar_indices.py` em 2026-10-30 sobre o commit `92ef5454`. Não editar à mão.


110 rotas declaradas nos routers. **Acesso**: a dependência mais forte encontrada (router, decorador, parâmetro ou chamada direta). **Grupo**: o corpo da função chama um filtro por grupo (`require_*_grupo`, `usuario.grupo`, escopo do admin). É uma detecção textual: confira o código antes de concluir que uma rota é segura ou insegura.

| Rota | Método | Função | Linha | Acesso | Grupo |
|---|---|---|---:|---|---|
| `/admin/acessos` | GET | `admin.py::acessos` | 153 | admin | sim |
| `/admin/arquivamento` | GET | `admin.py::status_arquivamento` | 376 | admin | sim |
| `/admin/arquivamento` | POST | `admin.py::executar_arquivamento` | 410 | admin | sim |
| `/admin/auditoria` | GET | `admin.py::auditoria` | 423 | admin | sim |
| `/admin/erros` | GET | `admin.py::erros` | 303 | admin | sim |
| `/admin/erros/limpar` | POST | `admin.py::limpar_erros` | 344 | admin | sim |
| `/admin/grupos` | GET | `admin.py::listar_grupos` | 237 | admin | sim |
| `/admin/grupos` | POST | `admin.py::criar_grupo` | 251 | admin geral | — |
| `/admin/grupos/{grupo_id}` | DELETE | `admin.py::excluir_grupo` | 278 | admin geral | — |
| `/admin/grupos/{grupo_id}` | PATCH | `admin.py::editar_grupo` | 265 | admin geral | — |
| `/admin/overview` | GET | `admin.py::overview` | 119 | admin | sim |
| `/admin/usuarios` | GET | `admin.py::usuarios` | 173 | admin | sim |
| `/admin/usuarios/{usuario_id}` | DELETE | `admin.py::excluir_usuario` | 211 | admin | sim |
| `/admin/usuarios/{usuario_id}` | PATCH | `admin.py::atualizar_usuario` | 181 | admin | sim |
| `/admin/usuarios/{usuario_id}/2fa/reset` | POST | `admin.py::resetar_2fa_usuario` | 446 | admin geral | sim |
| `/admin/usuarios/{usuario_id}/redefinir-senha` | POST | `admin.py::redefinir_senha` | 293 | admin | sim |
| `/admin/volumetria` | GET | `admin.py::volumetria` | 370 | admin | sim |
| `/api/danfse/gerar` | POST | `danfse.py::gerar_danfse` | 16 | operador | — |
| `/arquivos/{arquivo_id}/download` | GET | `arquivos.py::download_arquivo` | 38 | login | sim |
| `/arquivos/{arquivo_id}/preview` | GET | `arquivos.py::visualizar_arquivo` | 58 | login | sim |
| `/arquivos/{arquivo_id}/view` | GET | `arquivos.py::visualizar_arquivo` | 58 | login | sim |
| `/arquivos/{arquivo_id}/visualizar` | GET | `arquivos.py::visualizar_arquivo` | 58 | login | sim |
| `/auth/2fa` | GET | `auth.py::estado_2fa` | 102 | admin | — |
| `/auth/2fa/confirmar` | POST | `auth.py::confirmar_2fa` | 122 | admin | — |
| `/auth/2fa/iniciar` | POST | `auth.py::iniciar_2fa` | 107 | admin | — |
| `/auth/admin/sessao` | POST | `auth.py::abrir_sessao_admin` | 136 | admin | — |
| `/auth/convite/{token}` | GET | `auth.py::ver_convite` | 177 | público | — |
| `/auth/convites` | GET | `auth.py::listar_convites` | 164 | operador | sim |
| `/auth/convites` | POST | `auth.py::criar_convite` | 158 | operador | — |
| `/auth/convites/{convite_id}` | DELETE | `auth.py::revogar_convite` | 169 | operador | — |
| `/auth/criar-conta` | POST | `auth.py::criar_conta` | 190 | público | — |
| `/auth/grupos` | GET | `auth.py::listar_grupos_admin` | 251 | admin | — |
| `/auth/login` | POST | `auth.py::login` | 61 | público | sim |
| `/auth/me` | GET | `auth.py::me` | 82 | login | — |
| `/auth/recuperar-senha` | POST | `auth.py::recuperar_senha` | 227 | público | — |
| `/auth/redefinir-senha` | POST | `auth.py::redefinir_senha` | 238 | público | — |
| `/auth/reenviar-codigo` | POST | `auth.py::reenviar_codigo` | 214 | público | — |
| `/auth/trocar-senha` | POST | `auth.py::trocar_senha` | 87 | login | — |
| `/auth/usuarios` | POST | `auth.py::criar_usuario` | 256 | API key | — |
| `/auth/verificar-email` | POST | `auth.py::verificar_email` | 201 | público | — |
| `/certificados` | GET | `certificados.py::list_certificados` | 320 | login | sim |
| `/certificados` | POST | `certificados.py::create_certificado_compat` | 124 | login | sim |
| `/certificados/autocadastrar` | POST | `certificados.py::autocadastrar_certificado` | 238 | login | sim |
| `/certificados/upload` | POST | `certificados.py::upload_certificado` | 199 | login | sim |
| `/certificados/vencimentos` | GET | `certificados.py::vencimentos_certificados` | 369 | login | sim |
| `/certificados/{certificado_id}` | GET | `certificados.py::get_certificado` | 379 | login | sim |
| `/certificados/{certificado_id}` | PATCH | `certificados.py::update_certificado` | 406 | admin | sim |
| `/certificados/{certificado_id}/senha` | DELETE | `certificados.py::remover_senha_certificado` | 464 | admin | sim |
| `/certificados/{certificado_id}/senha` | POST | `certificados.py::salvar_senha_certificado` | 434 | admin | sim |
| `/certificados/{certificado_id}/senha/status` | GET | `certificados.py::status_senha_certificado` | 455 | login | sim |
| `/certificados/{certificado_id}/testar` | POST | `certificados.py::testar_certificado` | 391 | admin | sim |
| `/certificados/{certificado_id}/testar-senha-salva` | POST | `certificados.py::testar_senha_salva` | 477 | admin | sim |
| `/certificados/{certificado_ref}` | DELETE | `certificados.py::delete_certificado` | 491 | admin | sim |
| `/certificados/{certificado_ref}` | PUT | `certificados.py::update_certificado_compat` | 330 | admin | sim |
| `/cnpj/status` | GET | `cnpj.py::status_base_cnpj` | 16 | login | — |
| `/cnpj/{cnpj}` | GET | `cnpj.py::consultar_cnpj` | 21 | login | — |
| `/consultas/desativar` | POST | `consultas.py::desativar_consultas` | 41 | operador | sim |
| `/consultas/iniciar` | POST | `consultas.py::iniciar_consultas` | 31 | operador | sim |
| `/consultas/releitura-mes-anterior` | POST | `consultas.py::releitura_mes_anterior` | 57 | operador | sim |
| `/consultas/status` | GET | `consultas.py::get_consultas_status` | 22 | login | sim |
| `/db/health` | GET | `db_health.py::db_health` | 11 | público | — |
| `/empresas` | GET | `empresas.py::list_empresas` | 34 | login | sim |
| `/empresas` | POST | `empresas.py::create_empresa` | 26 | admin | sim |
| `/empresas/resumo-operacional` | GET | `empresas.py::resumo_operacional_empresas` | 43 | login | sim |
| `/empresas/{empresa_id}` | DELETE | `empresas.py::delete_empresa` | 84 | admin | sim |
| `/empresas/{empresa_id}` | GET | `empresas.py::get_empresa` | 66 | login | sim |
| `/empresas/{empresa_id}` | PATCH | `empresas.py::update_empresa` | 75 | admin | sim |
| `/empresas/{empresa_id}/certificados` | GET | `certificados.py::list_certificados_empresa` | 310 | login | sim |
| `/empresas/{empresa_id}/certificados` | POST | `certificados.py::create_certificado_empresa` | 282 | login | sim |
| `/empresas/{empresa_id}/nsu` | GET | `nsu.py::get_empresa_nsu` | 68 | login | sim |
| `/eventos` | GET | `eventos.py::list_eventos` | 17 | login | sim |
| `/execucoes` | GET | `execucoes.py::list_execucoes` | 65 | login | sim |
| `/health` | GET | `health.py::health_check` | 33 | público | — |
| `/health/operacao` | GET | `health.py::health_operacao` | 47 | token de monitoramento | — |
| `/logs` | GET | `logs.py::list_logs` | 40 | login | sim |
| `/metrics` | GET | `health.py::metrics_endpoint` | 42 | token de monitoramento | — |
| `/nfse` | GET | `nfse_compat.py::list_nfse_compat` | 100 | login | sim |
| `/nfse/{nota_id}` | GET | `nfse_compat.py::get_nfse_compat` | 160 | login | sim |
| `/nfse/{nota_id}` | PUT | `nfse_compat.py::update_nfse_compat` | 169 | operador | sim |
| `/nfse/{nota_id}/documentos` | GET | `nfse_compat.py::get_nfse_documentos_compat` | 216 | login | sim |
| `/notas` | GET | `notas.py::list_notas` | 63 | login | sim |
| `/notas/chave/{chave}` | GET | `notas.py::get_nota_por_chave` | 556 | login | sim |
| `/notas/download-lote` | GET | `notas.py::download_lote_notas_get` | 434 | login | sim |
| `/notas/download-lote` | POST | `notas.py::download_lote_notas` | 419 | login | sim |
| `/notas/emitidas` | GET | `notas.py::list_notas_emitidas` | 307 | login | sim |
| `/notas/recebidas` | GET | `notas.py::list_notas_recebidas` | 363 | login | sim |
| `/notas/resumo` | GET | `notas.py::get_notas_resumo` | 526 | login | sim |
| `/notas/todas` | GET | `notas.py::list_todas_notas` | 158 | login | sim |
| `/notas/{nota_id}` | GET | `notas.py::get_nota` | 575 | login | sim |
| `/notas/{nota_id}/arquivos` | GET | `notas.py::list_arquivos_nota` | 679 | login | sim |
| `/notas/{nota_id}/conferencia` | PATCH | `notas.py::patch_conferencia_nota` | 648 | operador | sim |
| `/notas/{nota_id}/eventos` | GET | `notas.py::list_eventos_nota` | 584 | login | sim |
| `/notas/{nota_id}/historico` | GET | `notas.py::get_historico_conferencia` | 671 | login | sim |
| `/notas/{nota_id}/sincronizar-eventos` | POST | `notas.py::sincronizar_eventos_nota` | 627 | operador | sim |
| `/notas/{nota_id}/tributos-comparativo` | GET | `notas.py::get_tributos_comparativo` | 618 | login | sim |
| `/nsu/status` | GET | `nsu.py::get_nsu_status` | 79 | login | sim |
| `/processos` | GET | `processos.py::list_processos` | 44 | login | sim |
| `/processos` | POST | `processos.py::create_processo` | 36 | operador | sim |
| `/processos/{processo_id}` | GET | `processos.py::get_processo` | 70 | login | sim |
| `/processos/{processo_id}/arquivos` | GET | `processos.py::list_arquivos_processo` | 78 | login | sim |
| `/processos/{processo_id}/cancelar` | POST | `processos.py::cancelar_processo` | 138 | operador | sim |
| `/processos/{processo_id}/jobs` | GET | `processos.py::list_jobs_processo` | 152 | login | sim |
| `/processos/{processo_id}/logs` | GET | `logs.py::list_logs_processo` | 63 | login | sim |
| `/processos/{processo_id}/notas` | GET | `processos.py::list_notas_processo` | 93 | login | sim |
| `/processos/{processo_id}/summary` | GET | `processos.py::get_summary_processo` | 129 | login | sim |
| `/relatorios/conferencia` | POST | `relatorios.py::exportar_conferencia` | 34 | login | sim |
| `/storage/health` | GET | `storage.py::storage_health` | 17 | público | — |
| `/storage/list` | GET | `storage.py::storage_list` | 51 | admin | sim |
| `/storage/test-read` | GET | `storage.py::storage_test_read` | 35 | admin | sim |
| `/storage/test-write` | POST | `storage.py::storage_test_write` | 28 | admin | sim |
