# Serena via MCP no Claude Code

> Verificado em 15/10/2026. Serena 2.0.0, Claude Code 2.1.268.

## Configuração

Servidor `serena`, escopo de usuário (`~\.claude.json`), transporte stdio:

```text
C:\Users\kaio.paula\.local\bin\serena.exe start-mcp-server --context=claude-code --agent-interface tools --project-from-cwd
```

- **Caminho absoluto**: o VS Code só enxerga o PATH novo depois de reiniciar; o caminho absoluto evita depender disso.
- **`--agent-interface tools`**: o padrão do Serena 2 é `REPL` (só `serena_repl` + `initial_instructions`). Com `tools`, cada operação é uma ferramenta MCP separada, o que deixa as permissões do Claude Code legíveis.
- **Projetos registrados**: `nfse-backend` (Python + PHP; 184 + 67 arquivos indexados) e `nfse-frontend` (TypeScript; 184 arquivos).
- O Codex não foi configurado (a auditoria será feita pelo Claude Code). Para ele: `serena setup codex`.
- Hooks do Serena para o Claude Code (alfa) **não** foram instalados. O hook `auto-approve` aprovaria ferramentas de edição sem perguntar.

## Somente leitura, em duas camadas

1. `read_only: true` em `.serena/project.yml` dos dois projetos.
2. `excluded_tools` em `~\.serena\serena_config.yml`: `create_text_file`, `execute_shell_command`, `insert_after_symbol`, `insert_before_symbol`, `rename_symbol`, `replace_content`, `replace_in_files`, `replace_symbol_body`, `safe_delete_symbol`.

A segunda camada é necessária porque, antes de ativar um projeto, o `read_only` do projeto ainda não vale (no teste, 23 ferramentas apareciam, incluindo as de edição).

As ferramentas de memória do Serena (`write_memory`, `edit_memory`…) continuam ativas; escrevem só em `.serena/memories/`.

## Como o projeto é escolhido

| Onde o VS Code / Claude Code está aberto | Comportamento |
|---|---|
| Raiz do repo do backend ou do frontend | Projeto ativado na hora; 9 ferramentas de leitura |
| Pasta de fora (`...\01 - Projetos\nfse_adn_limpo`) | Nenhum projeto ativo; o agente chama `activate_project` com `nfse-backend` ou `nfse-frontend`. 16 ferramentas, nenhuma edita código |

A pasta de fora serve para auditar backend e frontend na mesma sessão.

## Teste real (não só configuração)

Cliente MCP stdio próprio (`mcp` 1.x do ambiente do Serena), sobe o servidor e chama as ferramentas:

| Projeto | Arquivo | Chamada | Resultado |
|---|---|---|---|
| backend | `backend/app/main.py` | `get_symbols_overview` | 13 funções, 2 constantes, 3 variáveis |
| backend | `backend/app/main.py` | `find_symbol("_worker_groups")` | linhas 66–70 |
| backend | `backend/app/main.py` | `find_referencing_symbols("_worker_groups")` | usos em `_supervisionar_grupos` (l.129) e `lifespan` (l.190) |
| frontend | `src/components/conferencia/conferenciaUtils.ts` | `get_symbols_overview` | 7 funções |
| frontend | idem | `find_referencing_symbols("notaNumero")` | import em `ConferenciaDrawer.tsx` |

`claude mcp get serena` → `Status: ✔ Connected`.

**Pendente**: as ferramentas `mcp__serena__*` só aparecem numa **sessão nova** do Claude Code (reinicie o VS Code ou abra uma conversa nova). Esta validação usou um cliente MCP próprio, não a sessão do Claude Code.

## Outras ferramentas e MCP

Nenhuma das demais tem um servidor MCP oficial que valha a pena aqui. Todas são usadas como CLI pelo Claude Code (ver `COMANDOS.md`). A configuração do Codex (`node_repl`, `rea`) ficou intacta.
