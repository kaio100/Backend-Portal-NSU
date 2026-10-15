# Instalação

> Executado em 15/10/2026 pelo Claude Code, com permissão de usuário comum (sem administrador).

## Ambiente encontrado

| Item | Valor |
|---|---|
| SO | Windows 11 Pro 10.0.26200, x86_64 |
| Disco C: | 238 GB, 50 GB livres |
| Python do sistema | 3.10.11 (mantido; nada foi instalado nele) |
| Node / npm | 24.12.0 / 11.7.0 (mantidos) |
| Git | 2.52.0 |
| Docker | 29.1.2 instalado, **daemon parado** |
| WSL | sem distribuição instalada |
| winget | ausente no PATH |
| uv | ausente → instalado |
| Edge / Chrome | presentes (usados pelo Playwright) |
| MCP no Claude Code | conectores claude.ai (Docs, Vercel, Canva, Supabase, Railway, Google Drive) |
| MCP no Codex (`~\.codex\config.toml`) | `node_repl`, `rea`. **Não alterado** |

## Origem e verificação

| Ferramenta | Origem | Verificação |
|---|---|---|
| uv 0.13.1 | GitHub `astral-sh/uv`, release `uv-x86_64-pc-windows-msvc.zip` | SHA256 conferido com o `.sha256` do release |
| Betterleaks 1.9.0 | GitHub `betterleaks/betterleaks`, `betterleaks_1.9.0_windows_x64.zip` | SHA256 conferido com o `checksums.txt` |
| OSV-Scanner 2.7.0 | GitHub `google/osv-scanner`, `osv-scanner_windows_amd64.exe` | SHA256 conferido com o `osv-scanner_SHA256SUMS` |
| ast-grep 0.50.0 | GitHub `ast-grep/ast-grep`, `app-x86_64-pc-windows-msvc.zip` | SHA256 conferido com o digest da API do GitHub (o release não publica arquivo de checksum) |
| Serena, Ruff, Bandit, Vulture, import-linter, Semgrep | PyPI via `uv tool install` | ambiente virtual isolado por ferramenta |
| dependency-cruiser, knip, typescript 5.9.3, @playwright/test | npm, `--ignore-scripts` | pasta isolada fora dos repositórios |

Nenhum script remoto de instalação (`curl | sh`, `irm | iex`) foi executado.

## Comandos executados

```text
# binários (baixados para a scratchpad, conferidos, copiados)
copiar uv.exe uvx.exe uvw.exe betterleaks.exe ast-grep.exe sg.exe osv-scanner.exe -> C:\Users\kaio.paula\.local\bin
[Environment]::SetEnvironmentVariable('Path', "$p;C:\Users\kaio.paula\.local\bin", 'User')

# Serena
uv tool install -p 3.13 serena-agent
serena init
serena setup claude-code          # = claude mcp add --scope user serena -- serena start-mcp-server ...
serena project create <backend>  --name nfse-backend  --ls python --ls php --index
serena project create <frontend> --name nfse-frontend --ls typescript --index
claude mcp remove serena -s user
claude mcp add --scope user serena -- C:\Users\kaio.paula\.local\bin\serena.exe start-mcp-server --context=claude-code --agent-interface tools --project-from-cwd

# Python
uv tool install ruff | bandit | vulture | import-linter | semgrep

# Node (pasta isolada)
cd C:\Users\kaio.paula\.local\share\audit-tools\node
npm install --ignore-scripts dependency-cruiser knip typescript @playwright/test
npm install --ignore-scripts typescript@5.9.3     # dependency-cruiser exige typescript < 7
```

## O que mudou na máquina

| Onde | Mudança |
|---|---|
| `C:\Users\kaio.paula\.local\bin` | novos executáveis (uv, ast-grep, betterleaks, osv-scanner e os atalhos do `uv tool`) |
| PATH do usuário | `C:\Users\kaio.paula\.local\bin` adicionado. Vale para terminais e VS Code abertos depois da mudança |
| `C:\Users\kaio.paula\AppData\Roaming\uv\` | ambientes do `uv tool` e Python 3.13 gerenciado pelo uv |
| `C:\Users\kaio.paula\.local\share\audit-tools\node` | `package.json` e `node_modules` das ferramentas Node; `smoke/` com o teste do Playwright |
| `C:\Users\kaio.paula\.serena\serena_config.yml` | criado pelo `serena init`; editado (`excluded_tools`, dashboard não abre sozinho). Cópia: `serena_config.yml.bak-2026-10-15` |
| `C:\Users\kaio.paula\.claude.json` | servidor MCP `serena` no escopo de usuário |
| Backend e frontend: `.serena/` | `project.yml` (`read_only: true`), `memories/`, cache LSP (ignorado pelo `.serena/.gitignore`) |

Nada mudou em `requirements.txt`, `package.json`, `package-lock.json`, `composer.lock`, código, banco ou deploy. Nenhum commit ou push.

## Como desfazer

```text
claude mcp remove serena -s user
uv tool uninstall serena-agent ruff bandit vulture import-linter semgrep
apagar C:\Users\kaio.paula\.local\share\audit-tools
apagar os .exe de C:\Users\kaio.paula\.local\bin e tirar a pasta do PATH do usuário
apagar .serena/ nos dois repositórios e C:\Users\kaio.paula\.serena
```
