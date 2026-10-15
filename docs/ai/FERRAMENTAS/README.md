# Ferramentas de auditoria — inventário

> Verificado em 15/10/2026 contra a máquina do Kaio (Windows 11 Pro 26200, x64). Backend `a0cfbaf4`, frontend `e4299a4` (`Frontend_Portal_NSU`).

Ferramentas open source instaladas **fora** dos repositórios para apoiar a auditoria feita pelo Claude Code. Elas apontam onde olhar; nenhuma substitui a leitura do código, e nenhum alerta é vulnerabilidade confirmada antes da triagem.

| Documento | Conteúdo |
|---|---|
| `README.md` | Este inventário e o estado de cada ferramenta |
| `INSTALACAO.md` | O que foi instalado, de onde, como e o que mudou na máquina |
| `MCP.md` | Serena no Claude Code: configuração, modo somente leitura, teste real |
| `VALIDACAO.md` | Comando, código de saída e resultado de cada validação |
| `COMANDOS.md` | Como rodar cada ferramenta na auditoria (somente leitura) |
| `LIMITACOES.md` | O que não funciona, o que ficou pendente e por quê |

## Projetos cobertos

| Projeto | Caminho | Linguagens |
|---|---|---|
| Backend (este repo) | `C:\Users\kaio.paula\Downloads\01 - Projetos\nfse_adn_limpo\nfse_adn_limpo` | Python (FastAPI), PHP (`backend/danfse`, composer) |
| Frontend | `C:\Users\kaio.paula\Downloads\01 - Projetos\frontend_integrado_pronto_rodar\frontend` | TypeScript, React 18, Vite |

## Estado

| Ferramenta | Versão | Onde roda | Projeto | Estado | Integração Claude Code |
|---|---|---|---|---|---|
| Serena | 2.0.0 | `uv tool` (Python 3.13 isolado) | backend + frontend | INSTALADO_E_VALIDADO | MCP `serena` (escopo usuário), conectado e testado |
| Ruff | 0.17.0 | `uv tool` | backend | INSTALADO_E_VALIDADO | CLI |
| Bandit | 1.9.4 | `uv tool` | backend | INSTALADO_E_VALIDADO | CLI |
| Vulture | 2.16 | `uv tool` | backend | INSTALADO_E_VALIDADO | CLI |
| import-linter | 2.15 | `uv tool` | backend | INSTALADO_E_VALIDADO | CLI |
| Semgrep | 1.181.0 | `uv tool`, nativo no Windows | backend + frontend | INSTALADO_E_VALIDADO | CLI |
| ast-grep | 0.50.0 | binário em `~\.local\bin` | backend + frontend | INSTALADO_E_VALIDADO | CLI |
| Betterleaks | 1.9.0 | binário em `~\.local\bin` | backend + frontend | INSTALADO_E_VALIDADO | CLI |
| OSV-Scanner | 2.7.0 | binário em `~\.local\bin` | backend + frontend | INSTALADO_E_VALIDADO | CLI |
| Dependency Cruiser | 18.6.0 | pasta isolada Node | frontend | INSTALADO_E_VALIDADO | CLI |
| Knip | 6.41.0 | pasta isolada Node | frontend | INSTALADO_E_VALIDADO | CLI |
| Playwright | 1.64.1 | pasta isolada Node, usa o Edge instalado | frontend | INSTALADO_E_VALIDADO (smoke local) | CLI |
| uv | 0.13.1 | binário em `~\.local\bin` | — | INSTALADO_E_VALIDADO | pré-requisito |
| Repomix | — | — | — | NAO_INSTALADO (decisão) | — |
| pgTAP | — | — | — | BLOQUEADO (sem Postgres local) | — |

Por que Repomix e pgTAP ficaram de fora: `LIMITACOES.md`.

## Equivalências

O plano original listava ferramentas só de JavaScript. Para o backend Python, usamos as equivalentes:

| Objetivo | Frontend (TS) | Backend (Python) |
|---|---|---|
| Mapa e regras de dependência | Dependency Cruiser | import-linter |
| Código e exports sem uso | Knip | Vulture |
| Qualidade | (tsc do projeto) | Ruff |
| Segurança estática | Semgrep | Semgrep + Bandit |
