from __future__ import annotations

import argparse
import json
import os

from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.db.models import Empresa, Usuario
from backend.app.db.session import SessionLocal


EMAILS = {
    "pamela.silva@planning.com.br",
    "lia.trindade@planning.com.br",
}


def exportar_selecionados() -> list[dict]:
    with SessionLocal() as source:
        origem = source.query(Usuario).filter(Usuario.email.in_(EMAILS)).order_by(Usuario.email).all()
        return [
            {
                "email": usuario.email,
                "nome": usuario.nome,
                "senha_hash": usuario.senha_hash,
                "ativo": bool(usuario.ativo),
                "grupo": usuario.grupo,
                "is_admin": bool(usuario.is_admin),
            }
            for usuario in origem
        ]


def executar(confirmar: bool = False) -> dict:
    payload_memoria = os.getenv("LOCAL_USERS_JSON")
    if payload_memoria:
        dados = json.loads(payload_memoria)
    else:
        local_url = str(dotenv_values(".env").get("DATABASE_URL") or "").strip()
        if not local_url:
            raise RuntimeError("DATABASE_URL local nao encontrada no .env e LOCAL_USERS_JSON nao foi informado.")
        source_engine = create_engine(local_url, pool_pre_ping=True)
        with Session(source_engine) as source:
            origem = source.query(Usuario).filter(Usuario.email.in_(EMAILS)).order_by(Usuario.email).all()
            dados = [
                {
                    "email": usuario.email,
                    "nome": usuario.nome,
                    "senha_hash": usuario.senha_hash,
                    "ativo": bool(usuario.ativo),
                    "grupo": usuario.grupo,
                    "is_admin": bool(usuario.is_admin),
                }
                for usuario in origem
            ]

    encontrados = {item["email"] for item in dados}
    ausentes_origem = sorted(EMAILS - encontrados)
    if ausentes_origem:
        raise RuntimeError(f"Usuarios nao encontrados localmente: {ausentes_origem}")

    relatorio = {"modo": "execucao" if confirmar else "dry_run", "criados": [], "ja_existiam": []}
    with SessionLocal() as target:
        empresa = (
            target.query(Empresa)
            .filter(Empresa.grupo == "planning_hub", Empresa.ativo.is_(True))
            .order_by(Empresa.id)
            .first()
        )
        if empresa is None:
            raise RuntimeError("Empresa-base ativa do grupo planning_hub nao encontrada.")

        for item in dados:
            existente = target.query(Usuario).filter(Usuario.email == item["email"]).first()
            if existente is not None:
                relatorio["ja_existiam"].append(
                    {"id": existente.id, "email": existente.email, "nome": existente.nome}
                )
                continue
            usuario = Usuario(
                empresa_id=empresa.id,
                email=item["email"],
                nome=item["nome"],
                senha_hash=item["senha_hash"],
                ativo=item["ativo"],
                grupo="planning_hub",
                is_admin=False,
            )
            target.add(usuario)
            target.flush()
            relatorio["criados"].append(
                {"id": usuario.id, "email": usuario.email, "nome": usuario.nome, "empresa_id": empresa.id}
            )

        if confirmar:
            target.commit()
        else:
            target.rollback()
    return relatorio


def main() -> None:
    parser = argparse.ArgumentParser(description="Promove usuarios locais selecionados para a base configurada no ambiente")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--export", action="store_true", help="Exporta somente os usuarios autorizados da base atual")
    args = parser.parse_args()
    if args.export:
        print(json.dumps(exportar_selecionados(), ensure_ascii=False))
        return
    print(json.dumps(executar(confirmar=args.execute), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
