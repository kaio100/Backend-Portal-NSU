# ADR-0001 — Equipes isoladas por grupo, com o filtro na aplicação

- **Status:** aceito
- **Data:** 2026-09-25 (implementado na F4, `87672e78`)
- **Owners:** Kaio

## Contexto
Planning Hub e Planning MA usam o mesmo portal e não devem ver as empresas, notas e usuários uma da outra. Antes da F4, o admin via todos os grupos e havia vazamentos pontuais (eventos, NSU, busca por chave).

## Decisão
Cada empresa e cada usuário tem um `grupo` (texto, tabela `grupos`). Toda rota filtra pelo grupo do usuário (`deps.require_*_grupo`, `grupo=usuario.grupo`); recurso de outro grupo responde 404. O admin administra só o próprio grupo; o admin geral (`SUPER_ADMIN_EMAILS`) vê todos. Grupo desativado bloqueia o acesso. Workers e monitor são por grupo.

## Alternativas consideradas
- **RLS no Postgres como barreira principal:** mais forte contra esquecimento, mas o backend conecta com um papel que ignora RLS e o modelo não declara políticas. Ficou como reforço opcional (scripts `aplicar_seguranca_rls`).
- **Bancos separados por equipe:** isolamento total, mas duplica operação para duas equipes pequenas.

## Consequências
- (+) Simples; uma base, um deploy.
- (−) Uma rota nova sem filtro vaza dados (FIND-L09). Serviços aceitam `grupo=None` como "todos".
- (−) `empresas.cnpj` é único globalmente: a mesma empresa não pode estar em dois grupos.

## Validação
`tests/test_contas_e_grupos.py` (usuário de um grupo não vê o outro). Falta: testes de rota com usuário de outro grupo por padrão (ARCH-016).

## Reavaliar se
Entrar uma equipe externa ou cliente final no portal (aí RLS ou separação física passa a ser obrigatória).
