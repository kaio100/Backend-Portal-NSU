from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.core.security import create_access_token, hash_password, verify_password
from backend.app.db.models import Usuario
from backend.app.repositories import usuarios_repo


class AuthError(ValueError):
    pass


def autenticar(db: Session, email: str, senha: str) -> tuple[Usuario, str]:
    usuario = usuarios_repo.get_usuario_by_email(db, email)
    if usuario is None or not usuario.ativo or not verify_password(senha, usuario.senha_hash):
        # Mesma mensagem para email inexistente e senha errada: evita
        # confirmar para um atacante se o email esta cadastrado.
        raise AuthError("Email ou senha invalidos.")
    token = create_access_token(usuario.id, usuario.empresa_id)
    return usuario, token


def criar_usuario(db: Session, empresa_id: int, email: str, senha: str, nome: str | None = None) -> Usuario:
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
        },
    )
