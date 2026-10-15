# Limitações e pendências

> Verificado em 15/10/2026.

## Não instaladas

| Ferramenta | Estado | Motivo |
|---|---|---|
| Repomix | NAO_INSTALADO (decisão) | O backend tem `.env`, bancos em `data/*.db`, XMLs reais em `saida_adn_nfse/`, planilhas e certificados no histórico. Empacotar tudo num arquivo cria um risco de vazamento maior do que o ganho, já que o Claude Code lê o código direto e o Serena faz a navegação. Se precisar, instalar depois com uma lista de exclusão revisada. |
| pgTAP | BLOQUEADO | Não há Postgres local: os testes usam SQLite (`data/test_suite.db`), produção é o Supabase, o Docker está com o daemon parado e o WSL não tem distribuição. Rodar pgTAP no Supabase de produção está fora de questão. Requer um Postgres local (Docker ou branch do Supabase) antes. |

## Limitações conhecidas

- **Serena**: as ferramentas `mcp__serena__*` só aparecem em sessão nova do Claude Code. O Python 3.13 que ele usa é do uv, separado do 3.10 do sistema. O primeiro arquivo indexado de cada linguagem demora (sobe o language server).
- **Serena, hooks**: não instalados (alfa; o `auto-approve` liberaria edição).
- **Dependency Cruiser**: exige TypeScript < 7. A pasta isolada está fixada em `typescript@5.9.3`; não atualize sem conferir `depcruise --info`.
- **Dependency Cruiser e Knip** cobrem só o frontend. Para Python, use import-linter e Vulture.
- **Semgrep**: as regras do registry (`p/...`) precisam de internet para baixar as regras. O modo Pro/AppSec (login) não foi configurado nem é necessário.
- **OSV-Scanner**: consulta `api.osv.dev` (nome e versão dos pacotes). A resolução de dependências transitivas do `requirements.txt` pode listar versões diferentes das instaladas.
- **Betterleaks**: o modo `--validation` faria chamadas com o segredo a APIs externas. Não use. Achados em testes e `*.example` costumam ser fictícios.
- **Playwright**: validado só com página em memória. Rodar contra o app local exige subir backend e frontend localmente, e o `.env` do backend aponta para produção.
- **PATH**: terminais e VS Code abertos antes de 15/10/2026 09:10 não enxergam `~\.local\bin`. Reinicie o VS Code.
- **PHP** (`backend/danfse`): só Serena, Semgrep, ast-grep e OSV cobrem. Nenhuma ferramenta específica de PHP (ex.: PHPStan) foi instalada.
