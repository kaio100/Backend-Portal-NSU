"""Exporta o contrato da API (OpenAPI) para o frontend gerar os tipos TypeScript.

So le as rotas: nao conecta no banco nem no storage. Rode de uma pasta sem o
.env de producao ou com variaveis de teste, por exemplo:

    python -m backend.app.scripts.exportar_openapi ../frontend/openapi/backend.json

No frontend: npm run gerar:tipos
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    from backend.app.main import app

    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OpenAPI gravado em {destino}")


if __name__ == "__main__":
    main()
