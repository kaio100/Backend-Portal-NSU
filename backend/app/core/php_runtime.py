"""Localiza o PHP e habilita as extensoes exigidas pelo DANFSe oficial.

No Linux do container as extensoes ja vem habilitadas pelo pacote do sistema.
No Windows o PHP do winget sobe sem php.ini, e a biblioteca oficial falha com
"Call to undefined function ... mime_content_type()". Esta configuracao ficava
apenas em iniciar_local.py, entao qualquer outro ponto de entrada (uvicorn
direto, scripts de manutencao, reconciliacao) gerava PDF quebrado.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXTENSOES = ("openssl", "curl", "fileinfo", "gd", "mbstring")


class PhpRuntimeError(RuntimeError):
    pass


def localizar_php() -> str:
    php = shutil.which("php")
    if php:
        return php
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        packages = Path(local_appdata) / "Microsoft/WinGet/Packages"
        encontrado = next((str(p) for p in packages.glob("PHP.PHP.*/php.exe")), None)
        if encontrado:
            return encontrado
    raise PhpRuntimeError("PHP nao encontrado. Instale com GD, mbstring, fileinfo e XML.")


def configurar_php(exigir_vendor: bool = True) -> str:
    """Aponta DANFSE_PHP_BINARY e, no Windows, gera um php.ini com as extensoes.

    Retorna o caminho do binario. Idempotente: pode ser chamada varias vezes.
    """
    if exigir_vendor and not (ROOT / "backend/danfse/vendor/autoload.php").is_file():
        raise PhpRuntimeError("Execute 'composer install' em backend/danfse.")

    php_path = Path(localizar_php()).resolve()
    os.environ["DANFSE_PHP_BINARY"] = str(php_path)

    ext_dir = php_path.parent / "ext"
    if os.name != "nt" or not ext_dir.is_dir():
        # Fora do Windows as extensoes vem habilitadas pelo pacote do sistema.
        return str(php_path)

    runtime = ROOT / ".runlogs"
    runtime.mkdir(exist_ok=True)
    ini = runtime / "php-local.ini"
    ini.write_text(
        '[PHP]\nextension_dir="' + str(ext_dir) + '"\n'
        + "\n".join("extension=" + nome for nome in EXTENSOES),
        encoding="utf-8",
    )
    os.environ["PHPRC"] = str(ini)
    return str(php_path)
