"""Promove uma conta ja existente a administrador (papel admin).

Sem --aplicar so mostra o que faria. Nao mexe na senha, no grupo nem no 2FA.
Para ser admin geral (todos os grupos), o e-mail tambem precisa estar em
SUPER_ADMIN_EMAILS nas variaveis do servico; o script avisa quando nao esta.
Depois de aplicar, a pessoa abre /admin e cadastra o aplicativo autenticador.

    python -m backend.app.scripts.promover_admin --email pessoa@empresa.com.br
    python -m backend.app.scripts.promover_admin --email pessoa@empresa.com.br --aplicar
"""

from __future__ import annotations

import argparse

from backend.app.core.config import settings
from backend.app.db.models import Usuario
from backend.app.db.session import SessionLocal
from backend.app.services import admin_seguranca_service


def executar(email: str, aplicar: bool) -> str:
    email = email.strip().lower()
    with SessionLocal() as db:
        usuario = db.query(Usuario).filter(Usuario.email == email).first()
        if usuario is None:
            return f"Usuario {email} nao encontrado. A conta precisa existir (entrar pelo convite) antes de virar admin."
        avisos = []
        if not usuario.ativo:
            avisos.append("conta inativa: o login continua bloqueado")
        if not usuario.email_verificado:
            avisos.append("e-mail nao verificado: o login continua bloqueado")
        if email not in settings.super_admin_email_set:
            avisos.append("fora de SUPER_ADMIN_EMAILS: sera admin so do grupo " + repr(usuario.grupo))
        situacao = (
            f"{usuario.email} (grupo {usuario.grupo}): papel {usuario.papel}, is_admin={bool(usuario.is_admin)}, "
            f"2FA {'ativo' if usuario.totp_ativo else 'nao configurado'}"
        )
        if avisos:
            situacao += "\n  Atencao: " + "; ".join(avisos) + "."
        if usuario.papel == "admin" and usuario.is_admin:
            return f"{situacao}\nJa e admin; nada a fazer."
        if not aplicar:
            return f"[simulacao] {situacao}\nRode com --aplicar para tornar admin."
        usuario.papel = "admin"
        usuario.is_admin = True
        db.commit()
    admin_seguranca_service.registrar(None, f"script promover_admin {email}", "ok")
    return f"{situacao}\n{email}: agora e admin. Ao abrir /admin, configura o aplicativo autenticador."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--aplicar", action="store_true", help="Grava a alteracao (sem isso, so simula).")
    args = parser.parse_args()
    print(executar(args.email, args.aplicar))


if __name__ == "__main__":
    main()
