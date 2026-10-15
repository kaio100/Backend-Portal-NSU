# Comandos para a auditoria

> Todos só leem. Nenhum usa `--fix`, `--rewrite`, `-U` ou similar. Grave os relatórios **fora** do repositório (ex.: `$env:TEMP\auditoria\`).

Variáveis usadas abaixo (PowerShell):

```powershell
$B   = "C:\Users\kaio.paula\Downloads\01 - Projetos\nfse_adn_limpo\nfse_adn_limpo"
$F   = "C:\Users\kaio.paula\Downloads\01 - Projetos\frontend_integrado_pronto_rodar\frontend"
$N   = "C:\Users\kaio.paula\.local\share\audit-tools\node\node_modules\.bin"
$OUT = "$env:TEMP\auditoria"; New-Item -ItemType Directory -Force $OUT | Out-Null
```

## Serena (MCP)

Sessão nova do Claude Code. Na pasta de fora: `activate_project nfse-backend` (ou `nfse-frontend`). Ferramentas: `get_symbols_overview`, `find_symbol`, `find_referencing_symbols`, `find_declaration`, `find_implementations`, `get_diagnostics_for_file`.

## Backend (Python)

```powershell
cd $B
ruff check --no-cache --exit-zero --output-format json backend tests > $OUT\ruff.json
bandit -r backend/app -f json -o $OUT\bandit.json
vulture backend/app --min-confidence 60 > $OUT\vulture.txt
$env:PYTHONPATH="."; lint-imports --config <arquivo .ini fora do repo> --no-cache
```

Contratos do import-linter que valem a pena escrever (num `.ini` fora do repo): `core`/`db` não importam `api`; `repositories` não importam `services`; `api` não importa `worker`.

## Os dois projetos

```powershell
# Semgrep: sem telemetria; regras do registry baixam só as regras, o código não sai da máquina
semgrep scan --metrics=off --disable-version-check --config p/python --config p/fastapi --config p/secrets $B --json -o $OUT\semgrep-backend.json
semgrep scan --metrics=off --disable-version-check --config p/typescript --config p/react $F --json -o $OUT\semgrep-frontend.json

# Betterleaks: SEMPRE --redact; NUNCA --validation (consulta APIs externas com o segredo)
betterleaks git $B --redact -f json -r $OUT\leaks-backend-git.json
betterleaks dir $B --redact -f json -r $OUT\leaks-backend-dir.json
betterleaks git $F --redact -f json -r $OUT\leaks-frontend-git.json

# OSV-Scanner: envia nome+versão dos pacotes para api.osv.dev (não envia código)
osv-scanner scan source -L $B\requirements.txt -L $B\backend\danfse\composer.lock -L $F\package-lock.json --format json --output-file $OUT\osv.json

# ast-grep: só run/scan, sem -U/--rewrite
ast-grep run -p 'print($$$)' -l python $B\backend\app
ast-grep run -p 'dangerouslySetInnerHTML={$X}' -l tsx $F\src
```

## Frontend (TypeScript)

```powershell
cd $F
& $N\depcruise.cmd src --no-config --ts-config tsconfig.json --exclude "^node_modules" -T json -f $OUT\depcruise.json
& $N\depcruise.cmd src --no-config --ts-config tsconfig.json --exclude "^node_modules" -T dot -f $OUT\depcruise.dot   # grafo
& $N\knip.cmd --no-progress --no-exit-code --reporter json > $OUT\knip.json
```

## Playwright

Testes ficam fora do repo, em `C:\Users\kaio.paula\.local\share\audit-tools\node\smoke\` (ou outra pasta). Use `channel: 'msedge'` (sem baixar navegadores) e **só** `http://localhost` com `python iniciar_local.py` / `npm run dev`. Nunca a URL de produção, e lembre que o `.env` local do backend aponta para o banco de produção (ver `00_LEIA_PRIMEIRO.md`, regra 10).

## Regras de leitura dos resultados

- Todo alerta é HIPOTESE até ser lido no código.
- Knip e Vulture: "sem uso" pode ser import dinâmico, rota registrada por string ou script. Nunca apagar com base só neles.
- Nenhum relatório com conteúdo de segredo entra no repositório.
