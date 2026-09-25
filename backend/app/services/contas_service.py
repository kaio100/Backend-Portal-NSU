"""Contas por convite, confirmacao de e-mail e redefinicao de senha por codigo.

Regras (decididas em 2026-09-25):
- So operador e admin geram convite, sempre para o proprio grupo.
- Quem entra por convite e operador e so fica ativo depois de confirmar o
  e-mail com o codigo enviado pelo Resend.
- Esqueci minha senha: codigo por e-mail; trocar a senha derruba as sessoes.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.security import create_access_token, hash_password
from backend.app.db.models import (
    AcessoUsuario,
    ConviteCadastro,
    Empresa,
    RedefinicaoSenhaToken,
    Usuario,
    VerificacaoEmailToken,
)
from backend.app.services import email_service

MAX_TENTATIVAS_CODIGO = 5


class ContaError(ValueError):
    """Erro de negocio com mensagem para o usuario; `status` sugere o HTTP."""

    def __init__(self, mensagem: str, status: int = 400):
        super().__init__(mensagem)
        self.status = status


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _aware(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo is not None else valor.replace(tzinfo=timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_codigo(codigo: str) -> str:
    # HMAC com a chave do servidor: um codigo de 6 digitos tem so 1 milhao de
    # possibilidades, e um hash simples seria quebrado na hora se a tabela
    # vazasse.
    chave = (settings.jwt_secret or "").encode("utf-8")
    return hmac.new(chave, codigo.encode("utf-8"), hashlib.sha256).hexdigest()


def _novo_codigo() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def _normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


# ---------------------------------------------------------------- convites


def criar_convite(db: Session, usuario: Usuario, nome: str | None, validade_dias: int, max_usos: int) -> dict:
    token = secrets.token_urlsafe(32)
    convite = ConviteCadastro(
        token_hash=_hash_token(token),
        grupo=usuario.grupo,
        nome=(nome or "").strip()[:120] or None,
        ativo=True,
        max_usos=max_usos,
        usos_atuais=0,
        expires_at=_agora() + timedelta(days=validade_dias),
        criado_por_usuario_id=usuario.id,
    )
    db.add(convite)
    db.commit()
    db.refresh(convite)
    base = (settings.frontend_base_url or "").rstrip("/")
    return {
        **_convite_dict(convite),
        "token": token,
        "link": f"{base}/criar-conta?convite={token}" if base else None,
    }


def _convite_dict(convite: ConviteCadastro) -> dict:
    return {
        "id": convite.id,
        "grupo": convite.grupo,
        "nome": convite.nome,
        "ativo": convite.ativo,
        "max_usos": convite.max_usos,
        "usos_atuais": convite.usos_atuais,
        "expires_at": _aware(convite.expires_at),
        "criado_por_usuario_id": convite.criado_por_usuario_id,
        "created_at": convite.created_at,
    }


def listar_convites(db: Session, grupo: str) -> list[dict]:
    convites = (
        db.query(ConviteCadastro)
        .filter(ConviteCadastro.grupo == grupo)
        .order_by(ConviteCadastro.created_at.desc(), ConviteCadastro.id.desc())
        .all()
    )
    return [_convite_dict(convite) for convite in convites]


def revogar_convite(db: Session, convite_id: int, usuario: Usuario, admin: bool) -> dict:
    convite = db.get(ConviteCadastro, convite_id)
    if convite is None or convite.grupo != usuario.grupo:
        raise ContaError("Convite nao encontrado.", 404)
    if not admin and convite.criado_por_usuario_id != usuario.id:
        raise ContaError("So quem criou o convite ou um admin do grupo pode revoga-lo.", 403)
    convite.ativo = False
    db.commit()
    return _convite_dict(convite)


def _convite_valido(db: Session, token: str) -> ConviteCadastro:
    convite = (
        db.query(ConviteCadastro).filter(ConviteCadastro.token_hash == _hash_token(token or "")).first()
        if token
        else None
    )
    if convite is None or not convite.ativo:
        raise ContaError("Convite invalido ou revogado.", 404)
    expira = _aware(convite.expires_at)
    if expira is not None and expira <= _agora():
        raise ContaError("Convite expirado. Peca um novo link.", 410)
    if convite.max_usos is not None and convite.usos_atuais >= convite.max_usos:
        raise ContaError("Este convite ja foi usado.", 410)
    return convite


def info_convite(db: Session, token: str) -> dict:
    convite = _convite_valido(db, token)
    return {"grupo": convite.grupo, "nome": convite.nome, "expires_at": _aware(convite.expires_at)}


# ---------------------------------------------------------------- cadastro


def criar_conta(db: Session, token_convite: str, nome: str, email: str, senha: str) -> None:
    convite = _convite_valido(db, token_convite)
    email = _normalizar_email(email)
    existente = db.query(Usuario).filter(Usuario.email == email).first()
    if existente is not None and (existente.email_verificado or existente.grupo != convite.grupo):
        raise ContaError("Ja existe uma conta com este e-mail.", 409)

    if existente is None:
        # usuarios.empresa_id e obrigatorio; o acesso e pelo grupo.
        empresa = (
            db.query(Empresa)
            .filter(Empresa.grupo == convite.grupo, Empresa.ativo.is_(True))
            .order_by(Empresa.id.asc())
            .first()
        )
        if empresa is None:
            raise ContaError("O grupo do convite ainda nao tem empresas cadastradas.", 409)
        usuario = Usuario(
            empresa_id=empresa.id,
            email=email,
            senha_hash=hash_password(senha),
            nome=nome.strip(),
            ativo=False,
            grupo=convite.grupo,
            is_admin=False,
            papel="operador",
            email_verificado=False,
            token_version=0,
        )
        db.add(usuario)
        db.flush()
    else:
        # Cadastro pendente do mesmo grupo: refaz com os dados novos.
        usuario = existente
        usuario.nome = nome.strip()
        usuario.senha_hash = hash_password(senha)

    _enviar_codigo_verificacao(db, usuario, convite.id)


def _enviar_codigo_verificacao(db: Session, usuario: Usuario, convite_id: int | None) -> None:
    agora = _agora()
    (
        db.query(VerificacaoEmailToken)
        .filter(VerificacaoEmailToken.usuario_id == usuario.id, VerificacaoEmailToken.used_at.is_(None))
        .update({VerificacaoEmailToken.used_at: agora}, synchronize_session=False)
    )
    codigo = _novo_codigo()
    db.add(
        VerificacaoEmailToken(
            usuario_id=usuario.id,
            token_hash=_hash_token(secrets.token_urlsafe(32)),
            codigo_hash=_hash_codigo(codigo),
            tentativas=0,
            expires_at=agora + timedelta(minutes=settings.codigo_email_validade_minutos),
            convite_id=convite_id,
        )
    )
    try:
        email_service.enviar_codigo_cadastro(usuario.email, codigo)
    except email_service.EmailServiceError as exc:
        db.rollback()
        raise ContaError(f"Nao foi possivel enviar o codigo: {exc}", 503) from exc
    db.commit()


def reenviar_codigo(db: Session, email: str) -> None:
    usuario = db.query(Usuario).filter(Usuario.email == _normalizar_email(email)).first()
    if usuario is None or usuario.email_verificado:
        return  # resposta igual para nao revelar se o e-mail existe
    ultimo = (
        db.query(VerificacaoEmailToken)
        .filter(VerificacaoEmailToken.usuario_id == usuario.id)
        .order_by(VerificacaoEmailToken.id.desc())
        .first()
    )
    _enviar_codigo_verificacao(db, usuario, ultimo.convite_id if ultimo else None)


def verificar_email(db: Session, email: str, codigo: str, ip: str, user_agent: str | None) -> tuple[Usuario, str]:
    erro = ContaError("Codigo invalido ou expirado.")
    usuario = db.query(Usuario).filter(Usuario.email == _normalizar_email(email)).first()
    if usuario is None or usuario.email_verificado:
        raise erro
    token = (
        db.query(VerificacaoEmailToken)
        .filter(VerificacaoEmailToken.usuario_id == usuario.id, VerificacaoEmailToken.used_at.is_(None))
        .order_by(VerificacaoEmailToken.id.desc())
        .first()
    )
    if token is None or _aware(token.expires_at) <= _agora() or token.tentativas >= MAX_TENTATIVAS_CODIGO:
        raise erro
    if not hmac.compare_digest(token.codigo_hash, _hash_codigo((codigo or "").strip())):
        token.tentativas += 1
        db.commit()
        raise erro

    if token.convite_id is not None:
        convite = db.get(ConviteCadastro, token.convite_id)
        if convite is not None:
            if convite.max_usos is not None and convite.usos_atuais >= convite.max_usos:
                raise ContaError("Este convite ja foi usado por outra conta.", 410)
            convite.usos_atuais += 1
    token.used_at = _agora()
    usuario.email_verificado = True
    usuario.ativo = True
    db.add(AcessoUsuario(usuario_id=usuario.id, grupo=usuario.grupo, ip=ip, user_agent=user_agent))
    db.commit()
    db.refresh(usuario)
    return usuario, create_access_token(usuario.id, usuario.empresa_id, usuario.token_version)


# ---------------------------------------------------------------- senha


def solicitar_redefinicao(db: Session, email: str, ip: str) -> None:
    usuario = db.query(Usuario).filter(Usuario.email == _normalizar_email(email)).first()
    if usuario is None or not usuario.ativo or not usuario.email_verificado:
        return  # resposta igual para nao revelar se o e-mail existe
    agora = _agora()
    (
        db.query(RedefinicaoSenhaToken)
        .filter(RedefinicaoSenhaToken.usuario_id == usuario.id, RedefinicaoSenhaToken.used_at.is_(None))
        .update({RedefinicaoSenhaToken.used_at: agora}, synchronize_session=False)
    )
    codigo = _novo_codigo()
    db.add(
        RedefinicaoSenhaToken(
            usuario_id=usuario.id,
            token_hash=_hash_codigo(codigo),
            expires_at=agora + timedelta(minutes=settings.codigo_email_validade_minutos),
            ip_solicitante=ip[:80] if ip else None,
            tentativas=0,
        )
    )
    try:
        email_service.enviar_codigo_senha(usuario.email, codigo)
    except email_service.EmailServiceError as exc:
        db.rollback()
        raise ContaError(f"Nao foi possivel enviar o codigo: {exc}", 503) from exc
    db.commit()


def redefinir_senha(db: Session, email: str, codigo: str, nova_senha: str) -> None:
    erro = ContaError("Codigo invalido ou expirado.")
    usuario = db.query(Usuario).filter(Usuario.email == _normalizar_email(email)).first()
    if usuario is None:
        raise erro
    token = (
        db.query(RedefinicaoSenhaToken)
        .filter(RedefinicaoSenhaToken.usuario_id == usuario.id, RedefinicaoSenhaToken.used_at.is_(None))
        .order_by(RedefinicaoSenhaToken.id.desc())
        .first()
    )
    if token is None or _aware(token.expires_at) <= _agora() or (token.tentativas or 0) >= MAX_TENTATIVAS_CODIGO:
        raise erro
    if not hmac.compare_digest(token.token_hash, _hash_codigo((codigo or "").strip())):
        token.tentativas = (token.tentativas or 0) + 1
        db.commit()
        raise erro
    token.used_at = _agora()
    trocar_senha(db, usuario, nova_senha)


def trocar_senha(db: Session, usuario: Usuario, nova_senha: str) -> None:
    """Grava a senha nova e derruba todas as sessoes abertas."""
    usuario.senha_hash = hash_password(nova_senha)
    usuario.token_version = int(usuario.token_version or 0) + 1
    db.commit()
