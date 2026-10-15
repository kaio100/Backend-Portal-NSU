"""Zera a verificacao em duas etapas de um administrador que perdeu o celular.

Sem --aplicar so mostra o que faria. Depois de aplicar, a pessoa entra no
portal, abre o painel e cadastra o aplicativo autenticador de novo. Pelo
painel, o admin geral faz o mesmo em Usuarios (POST /admin/usuarios/{id}/2fa/reset).

    python -m backend.app.scripts.resetar_2fa_admin --email pessoa@empresa.com.br
    python -m backend.app.scripts.resetar_2fa_admin --email pessoa@empresa.com.br --aplicar
"""

from __future__ import annotations

import argparse

from backend.app.db.models import Usuario
from backend.app.db.session import SessionLocal
from backend.app.services import admin_seguranca_service


def executar(email: str, aplicar: bool) -> str:
    with SessionLocal() as db:
        usuario = db.query(Usuario).filter(Usuario.email == email.strip().lower()).first()
        if usuario is None:
            return f"Usuario {email} nao encontrado."
        situacao = "ativo" if usuario.totp_ativo else "nao configurado"
        if not aplicar:
            return f"[simulacao] {usuario.email}: 2FA {situacao}. Rode com --aplicar para zerar."
        admin_seguranca_service.resetar_2fa(db, usuario)
    admin_seguranca_service.registrar(None, f"script resetar_2fa {email}", "ok")
    return f"{email}: 2FA zerado. A pessoa precisa configurar de novo ao abrir o painel."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--aplicar", action="store_true", help="Grava a alteracao (sem isso, so simula).")
    args = parser.parse_args()
    print(executar(args.email, args.aplicar))


if __name__ == "__main__":
    main()
