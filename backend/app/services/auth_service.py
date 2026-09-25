from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.core.security import create_access_token, hash_password, verificar_senha_tempo_constante
from backend.app.db.models import Usuario
from backend.app.repositories import usuarios_repo


class AuthError(ValueError):
    pass


def autenticar(db: Session, email: str, senha: str) -> tuple[Usuario, str]:
    usuario = usuarios_repo.get_usuario_by_email(db, email)
    # Mesma mensagem e mesmo tempo (o hash roda mesmo sem usuario) para email
    # inexistente e senha errada: nao confirma quais e-mails tem conta.
    senha_ok = verificar_senha_tempo_constante(senha, usuario.senha_hash if usuario else None)
    if usuario is None or not senha_ok or not usuario.ativo or not getattr(usuario, "email_verificado", True):
        raise AuthError("Email ou senha invalidos.")
    token = create_access_token(usuario.id, usuario.empresa_id, getattr(usuario, "token_version", 0))
    return usuario, token


def criar_usuario(
    db: Session,
    empresa_id: int,
    email: str,
    senha: str,
    nome: str | None = None,
    grupo: str = "planning_hub",
) -> Usuario:
    email_normalizado = (email or "").strip().lower()
    if usuarios_repo.get_usuario_by_email(db, email_normalizado) is not None:
        raise AuthError("Ja existe um usuario com este email.")
    return usuarios_repo.create_usuario(
        db,
        {
            "empresa_id": empresa_id,
            "email": email_normalizado,
            "senha_hash": hash_password(senha),
            "nome": nome,
            "ativo": True,
            "grupo": grupo,
            "papel": "operador",
        },
    )
