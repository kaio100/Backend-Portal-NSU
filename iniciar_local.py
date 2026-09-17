"""Executa consultas reais com persistencia exclusivamente local.

Banco SQLite em data/local_test.db e arquivos em storage/. As consultas ao ADN
sao reais e exigem certificado cadastrado. O R2 nao e usado aqui: XML e PDF
ficam no disco desta maquina.
"""
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def configure():
    os.chdir(ROOT)
    os.environ.update({
        "ENVIRONMENT": "production",
        "DATABASE_URL": "sqlite:///./data/local_test.db",
        "STORAGE_BACKEND": "local",
        "STORAGE_ROOT": str(ROOT / "storage"),
        "WORKER_TEMP_DIR": str(ROOT / "data/tmp_worker"),
        "WORKER_DRY_RUN": "false",
        "API_WORKER_ENABLED": "true",
        "EMBEDDED_SCHEDULER_ENABLED": "true",
        "CORS_ORIGINS": "http://localhost:5173,http://127.0.0.1:5173",
        "INVERTEXTO_ENABLED": "false",
        "ALERT_WEBHOOK_URL": "",
        "DANFSE_LIBRARY_ROOT": str(ROOT / "backend/danfse"),
    })
    # ENVIRONMENT=production acima faz o backend exigir API_KEY, JWT_SECRET e
    # SECRETS_KEY. Sem um .env com as tres, o import de settings falha antes do
    # uvicorn subir. Falhar aqui deixa a causa explicita.
    faltando = [nome for nome in ("API_KEY", "JWT_SECRET", "SECRETS_KEY") if not _do_env(nome)]
    if faltando:
        raise RuntimeError(
            "Faltam no .env: " + ", ".join(faltando)
            + ". Copie o .env.example e gere as chaves (veja os comentarios do arquivo)."
        )

    from backend.app.core.php_runtime import configurar_php

    configurar_php()


def _do_env(nome: str) -> str:
    """Le a variavel do ambiente ou do .env, sem depender de settings."""
    valor = os.environ.get(nome, "").strip()
    if valor:
        return valor
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return ""
    for linha in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        linha = linha.strip()
        if linha.startswith(f"{nome}="):
            return linha.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


if __name__ == "__main__":
    configure()
    import uvicorn
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=8000)
