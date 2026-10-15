# ADR-0005 — Cadastro só por convite; papéis admin e operador

- **Status:** aceito
- **Data:** 2026-09-25 (F4, `87672e78`; migração `0003_contas_convite`)

## Contexto
O portal é interno. O frontend tinha tela de cadastro público sem rota no backend, e existia um papel "leitura" sem uso real.

## Decisão
Operador ou admin gera um link de convite para o **próprio grupo**. A pessoa cria a conta pelo link e confirma o e-mail com um código de 6 dígitos (Resend); só então fica ativa, como **operador**. "Esqueci a senha" usa o mesmo modelo de código. Só existem os papéis `admin` e `operador` (o `leitura` virou operador). Trocar ou redefinir a senha incrementa `token_version` e derruba as sessões.

## Consequências
- (+) Ninguém entra sem convite; e-mail confirmado; sessões revogáveis.
- (−) Depende do Resend em produção (sem ele, 503 no cadastro).
- (−) `usuarios.empresa_id` é obrigatório: grupo sem empresa ativa não aceita cadastro.
- (−) O código é um HMAC com `JWT_SECRET`: trocar o segredo invalida códigos pendentes.
- (−) Tokens de verificação e redefinição referenciam o usuário sem cascata: excluir usuário falha no Postgres (ARCH-006).
