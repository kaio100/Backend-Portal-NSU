# Validação

> Executado em 15/10/2026. Saídas em arquivos temporários fora do repositório. Números são **contagens brutas, sem triagem**: nada aqui é achado confirmado.

| Ferramenta | Comando (resumo) | Saída | Resultado |
|---|---|---|---|
| uv | `uv --version` | 0 | 0.13.1 |
| Serena | cliente MCP real (ver `MCP.md`) | 0 | símbolos e referências nos dois projetos |
| Ruff | `ruff check --no-cache --exit-zero --statistics backend tests` | 0 | 639 avisos, regras padrão (o repo não tem configuração do Ruff) |
| Bandit | `bandit -r backend/app -q -f json -o <tmp>` | 1 (= tem achados) | 28 achados: 15 MEDIUM, 13 LOW; 0 erros de leitura |
| Vulture | `vulture backend/app --min-confidence 80` | 3 (= tem achados) | 18 candidatos a código morto |
| import-linter | `lint-imports --config <tmp>/importlinter-teste.ini --no-cache` (PYTHONPATH=.) | 0 | 136 arquivos, 402 dependências; contrato de teste "core não importa api": KEPT |
| Semgrep | `semgrep scan --metrics=off --config <regra local> backend/app` | 0 | 138 arquivos, 1 ocorrência da regra de teste, 0 erros. **Nativo no Windows**, sem Docker |
| ast-grep | regra `except_clause` + `Exception`; `print($$$)`; `useEffect($$$)` | 0 | 31 `except Exception`, 108 `print()` no backend; 26 `useEffect` no frontend |
| Betterleaks | `betterleaks git . --redact -f json -r <tmp>` (backend, histórico) | 1 (= tem achados) | 45 achados, segredos redigidos. Ver nota abaixo |
| OSV-Scanner | `osv-scanner scan source -L requirements.txt -L composer.lock -L <frontend>/package-lock.json` | 1 (= tem vulns) | backend: 10 pacotes / 196 avisos; PHP: `dompdf` / 6; frontend: 13 pacotes / 26 |
| Dependency Cruiser | `depcruise src --no-config --ts-config tsconfig.json -T json` (frontend) | 0 | 1050 módulos (inclui `node_modules`), 2569 dependências, 0 ciclos |
| Knip | `knip --no-progress --no-exit-code --reporter json` (frontend) | 0 | 1 arquivo, 4 dependências, 19 exports, 5 tipos possivelmente sem uso |
| Playwright | `playwright test` com `channel: msedge`, página em memória | 0 | 1 passed (6,4 s). Sem rede, sem navegador baixado |

Depois de tudo, `git status` dos dois repositórios só mostra `.serena/` como novidade (o resto já estava lá antes).

## Notas para a auditoria (não triadas)

- **Betterleaks no histórico do backend** — status: HIPOTESE até a triagem. Regras: 35 `pkcs12-file` (em `storage/certificados/` e em `data/cleanup_backup_2026070*`), 3 `generic-api-key` e 1 `generic-password` em `.env`/`.env.docker`, 1 em `data/api_stdout.log`, e 4 em testes e `.env.docker.example` (provavelmente fictícios). Hoje nenhum `.pfx`/`.p12` está rastreado; o histórico guarda os antigos. Se o repositório já foi para um remoto, isso pesa mais.
- **OSV**: o `requirements.txt` aparece duas vezes no relatório porque o OSV-Scanner também resolve as dependências transitivas (algumas versões, como `h11 0.9.0` e `urllib3 1.26.9`, podem não ser as instaladas de fato). Confirmar com `pip freeze` do ambiente real.
- **Ruff**: 639 com as regras padrão da 0.17; definir um conjunto de regras antes de tirar conclusões.
