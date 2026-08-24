from __future__ import annotations

import os

from sqlalchemy import create_engine, text

from backend.app.core.config import settings


database_url = os.getenv("SUPABASE_DATABASE_URL") or os.getenv("ONLINE_DATABASE_URL") or settings.database_url
if database_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
engine = create_engine(database_url, pool_pre_ping=True)


with engine.connect() as conn:
    roles = set(
        conn.execute(
            text("select rolname from pg_roles where rolname in ('anon', 'authenticated', 'service_role')")
        ).scalars()
    )
    identidade = conn.execute(
        text(
            """
            select current_user,
                   session_user,
                   r.rolsuper,
                   r.rolbypassrls
              from pg_roles r
             where r.rolname = current_user
            """
        )
    ).mappings().one()
    privilege_columns = []
    for role in ("anon", "authenticated", "service_role"):
        if role in roles:
            privilege_columns.append(
                f"has_table_privilege('{role}', c.oid, 'select,insert,update,delete') as {role}_dml"
            )
        else:
            privilege_columns.append(f"false as {role}_dml")
    tabelas = conn.execute(
        text(
            f"""
            select c.relname as tabela,
                   c.relrowsecurity as rls,
                   pg_get_userbyid(c.relowner) as proprietario,
                   {', '.join(privilege_columns)}
              from pg_class c
              join pg_namespace n on n.oid = c.relnamespace
             where n.nspname = 'public'
               and c.relkind in ('r', 'p')
             order by c.relname
            """
        )
    ).mappings().all()
    vulneraveis = [
        row["tabela"] for row in tabelas
        if not row["rls"] and (row["anon_dml"] or row["authenticated_dml"])
    ]
    bloqueadas_sem_politica = [row["tabela"] for row in tabelas if row["rls"]]
    privilegios_padrao_publicos = conn.execute(
        text(
            """
            select pg_get_userbyid(d.defaclrole) as proprietario,
                   coalesce(n.nspname, '*') as esquema,
                   r.rolname as role,
                   x.privilege_type as privilegio
              from pg_default_acl d
              left join pg_namespace n on n.oid = d.defaclnamespace
              cross join lateral aclexplode(d.defaclacl) x
              join pg_roles r on r.oid = x.grantee
             where d.defaclobjtype = 'r'
               and n.nspname = 'public'
               and d.defaclrole = (select oid from pg_roles where rolname = current_user)
               and r.rolname in ('anon', 'authenticated')
             order by 1, 2, 3, 4
            """
        )
    ).mappings().all()
    print({
        "identidade": dict(identidade),
        "roles_disponiveis": sorted(roles),
        "vulneraveis_data_api": vulneraveis,
        "privilegios_padrao_publicos": [dict(row) for row in privilegios_padrao_publicos],
        "rls_ativas": bloqueadas_sem_politica,
        "tabelas": [dict(row) for row in tabelas],
    })
