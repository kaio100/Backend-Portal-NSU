from __future__ import annotations

import argparse
import os
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from backend.app.core.config import settings


database_url = os.getenv("SUPABASE_DATABASE_URL") or os.getenv("ONLINE_DATABASE_URL") or settings.database_url
if database_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
engine = create_engine(database_url, pool_pre_ping=True)


TABELAS_PROTEGIDAS = (
    "acessos_usuarios",
    "arquivos",
    "certificados",
    "cnpj_cache",
    "empresas",
    "eventos",
    "grupos",
    "locks_processamento",
    "logs_processos",
    "monitoramento_config",
    "notas",
    "nsu_controle",
    "processos",
    "processos_jobs",
    "secrets",
    "usuarios",
)


def _identificador(nome: str) -> str:
    if nome not in TABELAS_PROTEGIDAS:
        raise ValueError(f"Tabela fora da lista permitida: {nome}")
    return f'public."{nome}"'


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ativa RLS e bloqueia acesso Data API nas tabelas internas do portal."
    )
    parser.add_argument("--apply", action="store_true", help="Aplica as alteracoes; sem a opcao apenas simula.")
    parser.add_argument(
        "--lock-report",
        action="store_true",
        help="Mostra sessoes que mantem locks nas tabelas pendentes, sem exibir o SQL executado.",
    )
    parser.add_argument(
        "--terminate-stale-locks",
        action="store_true",
        help="Encerra apenas sessoes idle in transaction ha mais de 60s que bloqueiam tabelas pendentes.",
    )
    args = parser.parse_args()

    with engine.connect() as conn:
        usuario = conn.execute(text("select current_user")).scalar_one()
        bypass = conn.execute(
            text("select rolbypassrls from pg_roles where rolname = current_user")
        ).scalar_one()
        existentes = set(
            conn.execute(
                text(
                    """
                    select c.relname
                      from pg_class c
                      join pg_namespace n on n.oid = c.relnamespace
                     where n.nspname = 'public' and c.relkind in ('r', 'p')
                    """
                )
            ).scalars()
        )
        roles = set(
            conn.execute(
                text("select rolname from pg_roles where rolname in ('anon', 'authenticated')")
            ).scalars()
        )
        estados = {
            row.relname: bool(row.relrowsecurity)
            for row in conn.execute(
                text(
                    """
                    select c.relname, c.relrowsecurity
                      from pg_class c
                      join pg_namespace n on n.oid = c.relnamespace
                     where n.nspname = 'public' and c.relkind in ('r', 'p')
                    """
                )
            )
        }
        alvos = [nome for nome in TABELAS_PROTEGIDAS if nome in existentes and not estados.get(nome, False)]
        ja_protegidas = [nome for nome in TABELAS_PROTEGIDAS if estados.get(nome, False)]
        ausentes = sorted(set(TABELAS_PROTEGIDAS) - existentes)
        print(
            {
                "modo": "APLICAR" if args.apply else "SIMULAR",
                "usuario_backend": usuario,
                "backend_bypass_rls": bool(bypass),
                "tabelas_proteger": alvos,
                "tabelas_ja_protegidas": ja_protegidas,
                "tabelas_ausentes": ausentes,
                "roles_data_api": sorted(roles),
            }
        )
        if args.lock_report and alvos:
            locks = conn.execute(
                text(
                    """
                    select c.relname as tabela,
                           l.mode,
                           l.granted,
                           a.pid,
                           a.application_name,
                           a.state,
                           now() - a.xact_start as idade_transacao
                      from pg_locks l
                      join pg_class c on c.oid = l.relation
                      join pg_namespace n on n.oid = c.relnamespace
                      join pg_stat_activity a on a.pid = l.pid
                     where n.nspname = 'public'
                       and c.relname = any(:tabelas)
                     order by c.relname, l.granted desc, a.xact_start nulls last
                    """
                ),
                {"tabelas": alvos},
            ).mappings().all()
            print({"locks": [dict(row) for row in locks]})
        if args.terminate_stale_locks:
            if not args.apply:
                raise RuntimeError("--terminate-stale-locks exige --apply.")
            encerradas = conn.execute(
                text(
                    """
                    select distinct pg_terminate_backend(a.pid) as encerrada, a.pid
                      from pg_locks l
                      join pg_class c on c.oid = l.relation
                      join pg_namespace n on n.oid = c.relnamespace
                      join pg_stat_activity a on a.pid = l.pid
                     where n.nspname = 'public'
                       and c.relname = any(:tabelas)
                       and a.pid <> pg_backend_pid()
                       and a.state = 'idle in transaction'
                       and a.xact_start < now() - interval '60 seconds'
                    """
                ),
                {"tabelas": alvos},
            ).mappings().all()
            print({"sessoes_obsoletas_encerradas": [dict(row) for row in encerradas]})
            conn.commit()
        if not args.apply:
            return
        if not bypass:
            raise RuntimeError("A conexao do backend nao possui BYPASSRLS; aplicacao cancelada.")
        if ausentes:
            raise RuntimeError(f"Estrutura inesperada; tabelas ausentes: {ausentes}")

        conn.commit()

    protegidas: list[str] = []
    bloqueadas: list[str] = []
    for nome in alvos:
        tabela = _identificador(nome)
        # Revogar os grants primeiro fecha imediatamente a Data API e exige
        # um lock mais leve. O ENABLE RLS fica em uma transacao separada,
        # pois pode aguardar leitores ativos em tabelas muito movimentadas.
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout = '3s'"))
            for role in sorted(roles):
                conn.execute(text(f"REVOKE ALL PRIVILEGES ON TABLE {tabela} FROM {role}"))
        for tentativa in range(1, 11):
            try:
                with engine.begin() as conn:
                    conn.execute(text("SET LOCAL lock_timeout = '3s'"))
                    conn.execute(text(f"ALTER TABLE {tabela} ENABLE ROW LEVEL SECURITY"))
                protegidas.append(nome)
                print({"tabela": nome, "status": "protegida", "tentativa": tentativa})
                break
            except OperationalError:
                if tentativa == 10:
                    bloqueadas.append(nome)
                    print({"tabela": nome, "status": "lock_timeout", "tentativas": tentativa})
                    break
                time.sleep(1.0)

    if roles:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL PRIVILEGES ON TABLES FROM "
                + ", ".join(sorted(roles))
            ))

    print({
        "resultado": "concluido" if not bloqueadas else "parcial_por_lock",
        "tabelas_protegidas": len(protegidas),
        "tabelas_bloqueadas": bloqueadas,
    })
    if bloqueadas:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
