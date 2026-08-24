from __future__ import annotations

from backend.app.core.config import settings
from backend.app.db.session import migrate_db


def main() -> None:
    dialect = settings.database_url.split(":", 1)[0]
    print(f"Aplicando migracoes no banco ({dialect})...")
    migrate_db()
    print("Migracoes aplicadas com sucesso.")


if __name__ == "__main__":
    main()
