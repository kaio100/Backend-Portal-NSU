# API e integrações

> Verificado contra os routers em 08/10/2026, commit `a0cfbaf4`. A lista completa (102 rotas, com acesso e filtro de grupo) está em `gerado/ROTAS.md`, gerada do código. Este arquivo explica as regras que a tabela não mostra.

## Convenções

- **Autenticação:** `Authorization: Bearer <JWT>` (`deps.get_current_usuario`). `X-API-Key` só para servidor-servidor (`POST /auth/usuarios`). `/metrics` e `/health/operacao` exigem `METRICS_TOKEN` e respondem 404 em produção quando ele está vazio.
- **Papéis:** `require_operator` aceita qualquer usuário válido (só há `admin` e `operador`); `require_admin` = admin do grupo; `require_super_admin` = e-mail em `SUPER_ADMIN_EMAILS`.
- **Grupo:** recurso de outro grupo responde **404** ("Recurso nao encontrado."), nunca 403, para não revelar que existe.
- **Erros:** `HTTPException` com `detail` em português. O status costuma ser escolhido pelo texto da mensagem (`"nao encontrad" → 404`, `"ja existe" → 409`). Mudar a mensagem de um service pode mudar o status HTTP.
- **Docs OpenAPI:** `/docs`, `/redoc` e `/openapi.json` só fora de produção.
- **CORS:** `CORS_ORIGINS` (ou `BACKEND_CORS_ORIGINS`/`FRONTEND_URL`) + `https://frontend-portal-nsu.vercel.app` fixo; expõe `Content-Disposition` para o nome dos downloads.
- **Cabeçalhos de segurança:** nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`; em produção também HSTS e `Content-Security-Policy: default-src 'none'`.
- **Compatibilidade:** há aliases de parâmetros (`status`/`status_documento`, `data_inicial`/`data_inicio`, `cnpj_prestador`/`prestador_cnpj`…) e rotas antigas (`/nfse*`, `POST /certificados`, `PUT|DELETE /certificados/{ref}` por id ou nome, `/arquivos/{id}/view|preview|visualizar`). Não remova sem conferir o frontend.

## Grupos de rotas

### Autenticação e contas (`routers/auth.py`)
Públicas, com limite gravado no banco (vale entre réplicas e sobrevive a deploy): `login` (8 em 5 min por IP + e-mail, 20 em 15 min por conta, 60 em 15 min por IP), `convite/{token}`, `criar-conta`, `verificar-email`, `reenviar-codigo` (3 em 15 min), `recuperar-senha`, `redefinir-senha`. Respostas de "código enviado" são iguais exista ou não o e-mail. Com login: `me`, `trocar-senha`, `convites` (criar, listar e revogar no próprio grupo). `GET /auth/grupos` exige admin, apesar do prefixo `/auth`.

Verificação em duas etapas do admin (TOTP): `GET /auth/2fa`, `POST /auth/2fa/iniciar` (senha → segredo e link `otpauth://`; com o 2FA já ativo responde 409 e a troca de celular passa pelo reset do admin geral), `POST /auth/2fa/confirmar` (código). `POST /auth/admin/sessao` (senha + código) devolve `admin_token`, válido por `ADMIN_SESSAO_MINUTOS`; o mesmo código não abre duas sessões (400 com "Este código já foi usado..."). Senha ou código errado também é 400, nunca 401: o frontend trata 401 como sessão do portal expirada e desloga. Tentativas e resultados vão para a auditoria.

### Administração (`routers/admin.py`, router inteiro exige admin **e** a sessão do painel)
Além do JWT, toda rota `/admin` exige o cabeçalho `X-Admin-Token` (sessão de `POST /auth/admin/sessao`); sem ele ou vencido: 403 com `detail = "admin_sessao_necessaria"`, e o frontend pede senha + código de novo. `ADMIN_2FA_OBRIGATORIO=false` desliga essa exigência. Toda alteração (POST/PATCH/DELETE) fica em `auditoria_painel_admin` (`GET /admin/auditoria`). `POST /admin/usuarios/{id}/2fa/reset`: admin geral zera o 2FA de quem perdeu o celular. `GET /admin/volumetria?dias=7..366`: números agregados no banco para os gráficos (escopo do grupo; comparação entre grupos só para o admin geral). `POST /admin/erros/limpar`: marca os erros até agora como vistos (do grupo do admin; de todos para o admin geral), sem apagar nada.
Visão, acessos, usuários (editar, excluir, redefinir senha), erros e arquivamento, sempre no escopo do grupo do admin (`_escopo`), ou de todos para o admin geral. Criar, editar e excluir grupo e mover usuário de grupo: só admin geral. O arquivamento roda em `BackgroundTasks`, com estado num dicionário de módulo compartilhado entre grupos (ARCH-011).

### Empresas e certificados
Criar, editar e desativar empresa: admin. **Enviar certificado** (`POST /certificados`, `/upload`, `/autocadastrar`, `/empresas/{id}/certificados`): qualquer usuário logado. Editar, excluir, salvar ou testar senha: admin (ARCH-007). O autocadastro lê o CNPJ do certificado, cria a empresa se não existir (no grupo do usuário), reaproveita o certificado ativo da mesma empresa (thumbprint, CN ou único ativo) e, por padrão, enfileira a consulta sem restringir o monitor (REG-039). Tentativas de senha: 5 em 5 min por IP + certificado.

### Consultas e execução
`GET /consultas/status` (fila, totais, escopo do monitor), `POST /consultas/iniciar` (automático: grava o monitor e enfileira; avulso: só enfileira), `POST /consultas/desativar` (desliga e cancela), `POST /consultas/releitura-mes-anterior` (REG-040). `/processos*` (criar, listar, cancelar, jobs, notas, resumo), `/execucoes`, `/logs`, `/nsu/status`, `/empresas/{id}/nsu`.

### Notas, eventos e arquivos
`GET /notas` (lista paginada, até 500), `/notas/todas`, `/emitidas`, `/recebidas`, `/resumo`, `/chave/{chave}`, `/{id}` + `eventos`, `arquivos`, `historico`, `tributos-comparativo`; `PATCH /{id}/conferencia` (REG-022); `POST /{id}/sincronizar-eventos` (consulta os eventos da nota no ADN com o certificado da empresa). `POST|GET /notas/download-lote` → ZIP síncrono (cabeçalhos `X-Notas-Count`, `X-Arquivos-Count`, `X-Arquivos-Ausentes`). `POST /relatorios/conferencia` → XLSX. `/eventos` exige empresa ou nota do grupo.
`GET /notas` pagina por cursor: a resposta traz `X-Next-Cursor` quando a página veio cheia, e a próxima chamada manda `cursor=<valor>` (o `offset` passa a ser ignorado). A ordem é a mesma de antes (nulos por último). Cursor de outra ordenação ou inválido: 422.

`GET /notas` e `/notas/todas` são as rotas mais pesadas: de 8 a 15 s com o worker rodando em 08/10 (ARCH-002).

### Utilitários
`GET /cnpj/{cnpj}` (base local da Receita + cache), `POST /api/danfse/gerar` (operador; XML ≤ 5 MB; PHP com timeout de 60 s), `/storage/health|test-write|test-read|list` (os três últimos só admin; `list` percorre o bucket inteiro e filtra por CNPJ e grupo no Python).

### Saúde
`GET /health` (estático: não reflete worker nem agendador), `/db/health` (`SELECT 1`), `/storage/health` (só informa o backend). `/health/operacao` (vigia: fila parada, falhas por hora, empresas sem consulta) e `/metrics` (contadores em memória, formato Prometheus) com token.

## Integrações externas

| Sistema | Como | Onde | Falha |
|---|---|---|---|
| ADN NFS-e | `requests_pkcs12` com mTLS e o PFX da empresa; `GET {base}/DFe/{nsu}?cnpjConsulta=&lote=true`; eventos por chave | `adn_nfse_downloader.py`, `eventos_sync_service.py` | Timeout de 240 s; 5 tentativas em 429/502/503/504 e erro de rede; `ValueError` (certificado ou senha) não repete; **HTTP 400 é tratado como resposta normal** (ARCH-013) |
| Cloudflare R2 | `boto3` S3, `signature_version=s3v4`, retries adaptativos | `storage_service.R2StorageService` | Cliente novo a cada `get_storage_service()` (ARCH-014) |
| Resend | `POST api.resend.com/emails`, timeout de 15 s | `email_service.py` | Em produção sem Resend configurado o cadastro falha com 503 |
| PHP DANFSe | `subprocess.run([php, generate.php, xml, pdf, carimbo?])`, timeout | `danfse_service.py` | Herda o ambiente inteiro (ARCH-015) |
| Invertexto | HTTP, limite por minuto, cache em `cnpj_cache` | `cnpj_enrichment_service.py` | Opcional (`INVERTEXTO_ENABLED`); falha não derruba o job |
| Webhook de alerta | `urllib` POST JSON, timeout de 3 s | `observability.alert_failure` | `ALERT_WEBHOOK_URL` não configurado em produção |

## Consumidor

O único consumidor é o frontend `Frontend-Portal-NSU` (`src/lib/api.ts`). O contrato frontend × backend não foi reauditado em 08/10 (fica para a análise do frontend).
