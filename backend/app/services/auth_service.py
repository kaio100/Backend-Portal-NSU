from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.core.security import create_access_token, hash_password, verify_password
from backend.app.db.models import Empresa, Grupo, Usuario
from backend.app.repositories import empresas_repo, usuarios_repo


class AuthError(ValueError):
    pass


DEFAULT_ACCOUNT_EMPRESA_CNPJ = "00000000000000"
DEFAULT_ACCOUNT_EMPRESA_NOME = "Conta Padrao"


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


def criar_conta(
    db: Session,
    *,
    email: str,
    senha: str,
    empresa_nome: str | None = None,
    empresa_cnpj: str | None = None,
    ambiente: str = "producao",
    nome: str | None = None,
    grupo: str = "planning_hub",
) -> tuple[Usuario, str]:
    email_normalizado = (email or "").strip().lower()
    if usuarios_repo.get_usuario_by_email(db, email_normalizado) is not None:
        raise AuthError("Ja existe um usuario com este email.")

    grupo_config = db.query(Grupo).filter(Grupo.codigo == grupo, Grupo.ativo.is_(True)).first()
    if grupo_config is None:
        raise AuthError("Grupo invalido.")
    empresa_grupo = db.query(Empresa).filter(Empresa.grupo == grupo).order_by(Empresa.id.asc()).first()
    cnpj_placeholder = f"9{int(grupo_config.id):013d}"[-14:]
    cnpj_empresa = empresa_cnpj or (empresa_grupo.cnpj if empresa_grupo else cnpj_placeholder)
    nome_empresa = (empresa_nome or grupo_config.nome or DEFAULT_ACCOUNT_EMPRESA_NOME).strip()

    empresa = empresas_repo.get_empresa_by_cnpj(db, cnpj_empresa)
    if empresa is None:
        empresa = Empresa(
            nome=nome_empresa,
            cnpj=cnpj_empresa,
            ambiente=ambiente,
            ativo=True,
            grupo=grupo,
        )
        db.add(empresa)
        db.flush()
    elif not empresa.ativo:
        empresa.ativo = True
        db.add(empresa)
        db.flush()
    if empresa.grupo != grupo:
        raise AuthError("A empresa informada pertence a outro grupo.")

    usuario = Usuario(
        empresa_id=int(empresa.id),
        email=email_normalizado,
        senha_hash=hash_password(senha),
        nome=(nome or "").strip() or None,
        ativo=True,
        grupo=grupo,
    )
    db.add(usuario)
    db.flush()
    token = create_access_token(usuario.id, usuario.empresa_id)
    db.commit()
    db.refresh(usuario)
    return usuario, token
