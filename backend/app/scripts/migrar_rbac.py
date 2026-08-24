from __future__ import annotations

import argparse
import os

from sqlalchemy import create_engine, inspect, text

from backend.app.core.config import settings


def _engine():
    database_url = os.getenv("SUPABASE_DATABASE_URL") or os.getenv("ONLINE_DATABASE_URL") or settings.database_url
    if database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return create_engine(database_url, pool_pre_ping=True)


def executar(email_admin: str, *, aplicar: bool) -> dict:
    email = (email_admin or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError("Informe um e-mail administrativo valido.")

    engine = _engine()
    columns = {column["name"] for column in inspect(engine).get_columns("usuarios")}
    with engine.connect() as conn:
        usuario = conn.execute(
            text("select id, email, ativo, is_admin from usuarios where lower(email) = :email"),
            {"email": email},
        ).mappings().one_or_none()
        if usuario is None:
            raise RuntimeError("Usuario administrativo nao encontrado.")
        if not usuario["ativo"]:
            raise RuntimeError("Usuario administrativo esta inativo.")
        plano = {
            "modo": "aplicar" if aplicar else "simular",
            "usuario_admin_id": int(usuario["id"]),
            "usuario_admin_email": usuario["email"],
            "coluna_papel_existe": "papel" in columns,
        }
        if not aplicar:
            return plano
        conn.commit()

    with engine.begin() as conn:
        conn.execute(text("set local lock_timeout = '5s'"))
        if "papel" not in columns:
            conn.execute(text("alter table usuarios add column papel varchar(20) not null default 'operador'"))
        conn.execute(text("update usuarios set papel = 'operador' where papel is null or papel not in ('admin', 'operador', 'leitura')"))
        atualizado = conn.execute(
            text("update usuarios set papel = 'admin', is_admin = true where lower(email) = :email"),
            {"email": email},
        )
        if atualizado.rowcount != 1:
            raise RuntimeError("Promocao administrativa nao atualizou exatamente um usuario.")

    with engine.connect() as conn:
        papeis = {
            papel: int(total)
            for papel, total in conn.execute(
                text("select papel, count(*) from usuarios group by papel order by papel")
            )
        }
        admins = int(conn.execute(text("select count(*) from usuarios where papel = 'admin' and is_admin = true")).scalar_one())
    return {**plano, "resultado": "concluido", "papeis": papeis, "admins_consistentes": admins}


def main() -> None:
    parser = argparse.ArgumentParser(description="Migra usuarios para RBAC e promove uma conta administrativa.")
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(executar(args.admin_email, aplicar=args.apply))


if __name__ == "__main__":
    main()
