# Segurança

> Código verificado em 08/10/2026, commit `a0cfbaf4`. Os itens marcados "(06/10)" vêm da análise `../historico/SEGURANCA_CERTIFICADOS_2026-10-06.md`, que consultou o banco e o storage de produção; não foram refeitos em 08/10.

## Ativos

| Ativo | Onde | Proteção |
|---|---|---|
| Certificados A1 (PFX) dos clientes | R2, `certificados/{cnpj}/{id}/{arquivo}` | Só a senha interna do PKCS#12; sem cifra adicional da aplicação (06/10) |
| Senhas dos PFX | `secrets.encrypted_value` | Fernet/MultiFernet com `SECRETS_KEY` (várias chaves; a primeira cifra) |
| Documentos fiscais (XML/PDF) | R2 + `notas` | Acesso por grupo na aplicação |
| Contas | `usuarios` | PBKDF2-SHA256, 600 mil iterações; `token_version` |
| Segredos de runtime | Variáveis do Railway | `API_KEY`, `JWT_SECRET`, `SECRETS_KEY`, `DATABASE_URL`, `R2_*`, `RESEND_API_KEY`, `INVERTEXTO_TOKEN`, `METRICS_TOKEN` |

## Fronteiras de confiança

1. Navegador → API: JWT Bearer; CORS restrito; respostas sem senha.
2. API/worker → Postgres: um papel com `rolbypassrls=true` (06/10). O isolamento entre grupos é **só da aplicação** (FIND-L09).
3. Worker → ADN: mTLS com o PFX da empresa, gravado em arquivo temporário (`WORKER_TEMP_DIR`) e apagado no `finally`; verificação TLS ligada.
4. API → PHP: subprocesso com o XML enviado pelo usuário; herda o ambiente inteiro (ARCH-015).
5. Público → `/auth/*`: limite de tentativas gravado no banco, por IP real (último `X-Forwarded-For` quando a conexão vem de proxy interno), por conta e por IP + e-mail.
6. Admin → `/admin/*`: além do JWT de admin, sessão própria de 30 min (`X-Admin-Token`) aberta com senha + código TOTP.

## Controles confirmados no código (08/10)

- Validação de produção: `API_KEY` e `JWT_SECRET` com ≥ 32 caracteres, `SECRETS_KEY` Fernet válida, Resend completo se ligado (`config.validate_production_secrets`).
- Login com tempo constante; mesma mensagem para e-mail inexistente e senha errada; códigos de e-mail com HMAC, 15 min, 5 tentativas.
- Token do portal com 12 h (padrão de `JWT_EXPIRE_MINUTES`); token com `escopo` (sessão do painel admin) não serve como token do portal.
- Painel admin: 2FA obrigatório (TOTP, segredo cifrado com `SECRETS_KEY`, janela de ±30 s, código não reaproveitável), sessão de `ADMIN_SESSAO_MINUTOS` só na aba (sessionStorage) e auditoria de toda alteração e de toda tentativa de entrada (`auditoria_painel_admin`). Perda do celular: admin geral zera pelo painel ou `scripts/resetar_2fa_admin --aplicar`.
- `token_version` derruba sessões ao trocar ou redefinir senha; usuário inativo, não verificado ou de grupo desativado é bloqueado a cada request.
- Recurso de outro grupo → 404; admin limitado ao próprio grupo; ações entre grupos só para o admin geral.
- Docs/OpenAPI desligados em produção; HSTS e CSP em produção; `nosniff`, `DENY`, `no-referrer`.
- Chaves de storage normalizadas (sem `..`, sem caminho absoluto, dentro da raiz).
- Download genérico bloqueia arquivo do tipo certificado (06/10); schemas não devolvem senha.
- Logs de processo sanitizados na leitura (`logs_service.sanitizar_*`); parâmetros da consulta ADN omitidos do log.
- dompdf com `isRemoteEnabled = false`; o XML é validado (raiz NFS-e, tamanho) antes do PHP.
- XML de terceiros lido com `defusedxml` (sem entidades nem DTD externos) no Python.
- RLS ativa em `certificados`, `secrets` e `usuarios`, com SELECT negado a `anon`/`authenticated` (06/10).

## Pendências

| Prioridade | Item | Origem | Ação |
|---|---|---|---|
| Crítica | `SECRETS_KEY` e credenciais R2 atuais encontradas no histórico do Git | 06/10 (FIND-L10) | Restringir acesso ao repositório; nova credencial R2 com escopo mínimo e revogação da antiga; nova `SECRETS_KEY` na frente, `rotacionar_segredos --aplicar`, retirar a antiga; conferir revogação de credenciais antigas de banco/JWT/API; limpar o histórico com preparação. **Status da rotação não reconferido em 08/10** |
| Alta | PFX sem cifra adicional | 06/10 | Cifra autenticada do arquivo com chave separada; bucket ou credencial exclusivos para certificados |
| Alta | Operador substitui certificado pelo autocadastro; edição exige admin | 06/10 + ARCH-007 | Decidir a política (ADR) e registrar autor e resultado da troca |
| Média | Papel do banco com `rolbypassrls` | 06/10 | Papel de runtime com permissão mínima; migração com papel separado |
| Média | `DATABASE_URL` sem `sslmode` explícito | 06/10 | `sslmode=verify-full` após teste |
| Média | Container roda como root; PFX temporário sem permissão restrita | 06/10 | `USER` não-root no Dockerfile; `chmod 600` / diretório privado |
| Baixa | Subprocesso PHP herda segredos | ARCH-015 | Ambiente mínimo (`PATH`, `COMPOSER_HOME`) |
| Baixa | Autocadastro revela que o CNPJ existe em outro grupo | ARCH-007 | Mensagem neutra |
| Baixa | `/storage/list` lista o bucket inteiro e filtra por substring de CNPJ (chave de NFS-e contém o CNPJ do emitente) | código | Listar por prefixo do grupo |
| Validação | Acesso público do R2 (`r2.dev`, domínio próprio) e visibilidade do repositório GitHub | 06/10 | Conferir nos painéis Cloudflare e GitHub |

## Regras para quem mexe no código

- Nunca logue senha, PFX, token ou `DATABASE_URL`. Use `logs_service.sanitizar_contexto` para contexto de processo.
- Rota nova: decida o papel (`require_admin`/`require_operator`) e o filtro de grupo antes de escrever o corpo; teste o 404 entre grupos com um usuário de outro grupo (não o admin automático do `conftest`).
- O `.env` local aponta para produção. Scripts de `backend/app/scripts/` que escrevem têm modo de simulação: rode sem `--aplicar`/`--executar` primeiro.
- Trocar `JWT_SECRET` derruba todos os logins e invalida códigos de e-mail pendentes. Trocar `SECRETS_KEY` sem recifrar torna as senhas ilegíveis e os certificados somem da fila.
