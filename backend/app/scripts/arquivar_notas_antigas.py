from __future__ import annotations

import argparse
import json

from backend.app.db.session import SessionLocal, init_db
from backend.app.services.notas_archive_service import arquivar_notas_anos_anteriores
from backend.app.services.storage_service import get_storage_service


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup e arquivamento reversivel de notas antigas")
    parser.add_argument("--ano", type=int, default=2026, help="Ano mantido nas telas operacionais")
    parser.add_argument("--executar", action="store_true", help="Sem esta opcao apenas mostra o que seria arquivado")
    args = parser.parse_args()
    init_db()
    with SessionLocal() as db:
        resultado = arquivar_notas_anos_anteriores(
            db,
            get_storage_service(),
            ano_operacional=args.ano,
            executar=args.executar,
        )
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
