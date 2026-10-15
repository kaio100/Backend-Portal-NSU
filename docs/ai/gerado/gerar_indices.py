"""Gera os indices mecanicos de docs/ai/gerado a partir do codigo.

Uso, na raiz do repositorio:

    python docs/ai/gerado/gerar_indices.py

So le o codigo (ast + git ls-files) e reescreve ARQUIVOS.md, SIMBOLOS.md e
ROTAS.md nesta pasta. Rode depois de qualquer mudanca de arquivo, funcao ou
rota; nunca edite esses tres arquivos a mao.
"""

from __future__ import annotations

import ast
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
SAIDA = Path(__file__).resolve().parent
IGNORAR = ("backend/danfse/vendor/", "docs/ai/gerado/")

# Ordem importa: a primeira dependencia encontrada define o rotulo.
ROTULOS_AUTH = (
    ("require_super_admin", "admin geral"),
    ("require_admin", "admin"),
    ("require_api_key", "API key"),
    ("require_operator", "operador"),
    ("exigir_token_operacao", "token de monitoramento"),
    ("get_current_usuario", "login"),
)
VERIFICACOES_GRUPO = (
    "require_empresa_grupo",
    "require_nota_grupo",
    "require_processo_grupo",
    "require_arquivo_grupo",
    "require_certificado_grupo",
    "usuario.grupo",
    "_escopo(",
    "_resolve_certificado_ref",
    "_garantir_certificado_do_grupo",
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, check=True).stdout.strip()


def _arquivos_versionados() -> list[str]:
    return sorted(p for p in _git("ls-files").splitlines() if not p.startswith(IGNORAR))


def _cabecalho(titulo: str) -> str:
    commit = _git("rev-parse", "--short", "HEAD")
    return (
        f"# {titulo}\n\n"
        f"> Gerado por `docs/ai/gerado/gerar_indices.py` em {date.today().isoformat()} sobre o commit `{commit}`. "
        "Não editar à mão.\n\n"
    )


def _linhas(caminho: Path) -> int:
    try:
        return len(caminho.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return 0


def _docstring(arvore: ast.AST) -> str:
    texto = ast.get_docstring(arvore) or ""
    return texto.strip().splitlines()[0] if texto.strip() else ""


def _arvore(caminho: Path) -> ast.Module | None:
    try:
        return ast.parse(caminho.read_text(encoding="utf-8"), filename=str(caminho))
    except (SyntaxError, UnicodeDecodeError):
        return None


def gerar_arquivos(arquivos: list[str]) -> str:
    por_pasta: dict[str, list[str]] = defaultdict(list)
    for relativo in arquivos:
        por_pasta[str(Path(relativo).parent).replace("\\", "/")].append(relativo)
    partes = [_cabecalho("Índice de arquivos versionados"),
              f"{len(arquivos)} arquivos (fora `backend/danfse/vendor/`, que é instalado pelo Composer).\n"]
    for pasta in sorted(por_pasta):
        partes.append(f"\n## `{pasta}/`\n\n| Arquivo | Linhas | Descrição (docstring) |\n|---|---:|---|")
        for relativo in por_pasta[pasta]:
            caminho = RAIZ / relativo
            descricao = ""
            if relativo.endswith(".py"):
                arvore = _arvore(caminho)
                descricao = _docstring(arvore) if arvore else "(não analisável)"
            texto = relativo.endswith((".py", ".php", ".md", ".txt", ".ini", ".yml", ".json", ".toml"))
            linhas = _linhas(caminho) if texto else ""
            partes.append(f"| `{Path(relativo).name}` | {linhas} | {descricao.replace('|', '/')} |")
    return "\n".join(partes) + "\n"


def gerar_simbolos(arquivos: list[str]) -> str:
    partes = [_cabecalho("Índice de símbolos Python"),
              "Classes e funções de nível de módulo, com os métodos das classes. "
              "Para o comportamento, leia o código; este índice só localiza.\n"]
    total = 0
    for relativo in arquivos:
        if not relativo.endswith(".py") or not (relativo.startswith("backend/") or "/" not in relativo):
            continue
        arvore = _arvore(RAIZ / relativo)
        if arvore is None:
            continue
        itens = []
        for no in arvore.body:
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                itens.append(f"`{no.name}` :{no.lineno}")
            elif isinstance(no, ast.ClassDef):
                metodos = [m.name for m in no.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
                extra = f" ({', '.join(metodos)})" if metodos else ""
                itens.append(f"**`{no.name}`** :{no.lineno}{extra}")
        if itens:
            total += len(itens)
            partes.append(f"- `{relativo}`: " + " · ".join(itens))
    partes.insert(1, f"{total} símbolos de nível de módulo.\n")
    return "\n".join(partes) + "\n"


def _nome_chamado(no: ast.AST) -> str:
    if isinstance(no, ast.Call):
        return _nome_chamado(no.func)
    if isinstance(no, ast.Name):
        return no.id
    if isinstance(no, ast.Attribute):
        return no.attr
    return ""


def _depends(no: ast.AST) -> list[str]:
    """Nomes passados a Depends(...) dentro de qualquer expressao."""
    nomes = []
    for filho in ast.walk(no):
        if isinstance(filho, ast.Call) and _nome_chamado(filho.func) == "Depends" and filho.args:
            nomes.append(_nome_chamado(filho.args[0]))
    return nomes


def _kw(call: ast.Call, nome: str) -> ast.AST | None:
    return next((k.value for k in call.keywords if k.arg == nome), None)


def gerar_rotas() -> str:
    pasta = RAIZ / "backend" / "app" / "api" / "routers"
    linhas = []
    for caminho in sorted(pasta.glob("*.py")):
        fonte = caminho.read_text(encoding="utf-8")
        arvore = ast.parse(fonte)
        routers: dict[str, tuple[str, list[str]]] = {}
        for no in arvore.body:
            if isinstance(no, ast.Assign) and isinstance(no.value, ast.Call) and _nome_chamado(no.value.func) == "APIRouter":
                prefixo = _kw(no.value, "prefix")
                deps = _kw(no.value, "dependencies")
                for alvo in no.targets:
                    if isinstance(alvo, ast.Name):
                        routers[alvo.id] = (
                            prefixo.value if isinstance(prefixo, ast.Constant) else "",
                            _depends(deps) if deps is not None else [],
                        )
        for no in arvore.body:
            if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            corpo = ast.get_source_segment(fonte, no) or ""
            for dec in no.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                metodo = dec.func.attr.upper()
                alvo = dec.func.value.id if isinstance(dec.func.value, ast.Name) else ""
                if metodo not in {"GET", "POST", "PUT", "PATCH", "DELETE"} or alvo not in routers:
                    continue
                prefixo, deps_router = routers[alvo]
                caminho_rota = dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else ""
                deps_dec = _depends(_kw(dec, "dependencies")) if _kw(dec, "dependencies") is not None else []
                deps_args = [d for arg in no.args.defaults + no.args.kw_defaults if arg is not None for d in _depends(arg)]
                chamadas = [n for n, _ in ROTULOS_AUTH if f"{n}(usuario)" in corpo]
                todas = set(deps_router + deps_dec + deps_args + chamadas)
                auth = next((rotulo for nome, rotulo in ROTULOS_AUTH if nome in todas), "público")
                grupo = "sim" if any(v in corpo for v in VERIFICACOES_GRUPO) else "—"
                linhas.append((
                    prefixo + caminho_rota or "/", metodo, f"{caminho.name}::{no.name}", no.lineno, auth, grupo,
                ))
    linhas.sort(key=lambda item: (item[0], item[1]))
    partes = [
        _cabecalho("Índice de rotas HTTP"),
        f"{len(linhas)} rotas declaradas nos routers. **Acesso**: a dependência mais forte encontrada "
        "(router, decorador, parâmetro ou chamada direta). **Grupo**: o corpo da função chama um filtro "
        "por grupo (`require_*_grupo`, `usuario.grupo`, escopo do admin). É uma detecção textual: "
        "confira o código antes de concluir que uma rota é segura ou insegura.\n",
        "| Rota | Método | Função | Linha | Acesso | Grupo |",
        "|---|---|---|---:|---|---|",
    ]
    partes += [f"| `{r}` | {m} | `{f}` | {l} | {a} | {g} |" for r, m, f, l, a, g in linhas]
    return "\n".join(partes) + "\n"


def main() -> None:
    arquivos = _arquivos_versionados()
    (SAIDA / "ARQUIVOS.md").write_text(gerar_arquivos(arquivos), encoding="utf-8")
    (SAIDA / "SIMBOLOS.md").write_text(gerar_simbolos(arquivos), encoding="utf-8")
    (SAIDA / "ROTAS.md").write_text(gerar_rotas(), encoding="utf-8")
    print("Indices gerados em", SAIDA)


if __name__ == "__main__":
    main()
