"""Verificacao em duas etapas do administrador, sessao do painel e auditoria.

Para entrar no painel administrativo o admin precisa, alem do login normal,
abrir uma sessao curta com a senha e um codigo do aplicativo autenticador. O
token dessa sessao vai no cabecalho X-Admin-Token (ver deps.require_admin_sessao).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from backend.app.core import totp
from backend.app.core.security import create_admin_token, verify_password
from backend.app.db.models import AuditoriaAdmin, Usuario
from backend.app.db.session import SessionLocal
from backend.app.services.secrets_service import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)


class SegurancaAdminError(ValueError):
    def __init__(self, mensagem: str, status: int = 400):
        super().__init__(mensagem)
        self.status = status


# Sem a palavra "senha": o frontend (shared/api/http.ts, friendlyHttpMessage)
# troca qualquer erro com "senha" pela mensagem de senha de certificado.
_CREDENCIAL_INVALIDA = "Dados de acesso incorretos. Confira a sua credencial do portal e o codigo do aplicativo."


def iniciar_2fa(db: Session, usuario: Usuario, senha: str) -> dict:
    """Gera um segredo novo, ainda inativo, e devolve o link para o aplicativo.

    Pede a senha para que uma sessao esquecida aberta nao baste para trocar o 2FA.
    Com o 2FA ja ativo recusa: so com a senha, quem a descobrisse cadastraria o
    proprio celular e entraria no painel. A troca passa pelo reset do admin geral.
    """
    if not verify_password(senha, usuario.senha_hash):
        raise SegurancaAdminError(_CREDENCIAL_INVALIDA, 400)
    if usuario.totp_ativo:
        raise SegurancaAdminError(
            "A verificacao em duas etapas ja esta ativa. Para trocar o celular, peca ao administrador geral para zera-la.",
            409,
        )
    segredo = totp.gerar_segredo()
    usuario.totp_segredo_cifrado = encrypt_secret(segredo)
    usuario.totp_ativo = False
    usuario.totp_ultimo_passo = None
    db.commit()
    return {"segredo": segredo, "otpauth_uri": totp.uri_otpauth(segredo, usuario.email)}


def confirmar_2fa(db: Session, usuario: Usuario, codigo: str) -> None:
    if not usuario.totp_segredo_cifrado:
        raise SegurancaAdminError("Gere o codigo de configuracao antes de confirmar.", 409)
    passo = totp.verificar(decrypt_secret(usuario.totp_segredo_cifrado), codigo)
    if passo is None:
        raise SegurancaAdminError("Codigo invalido. Confira o horario do celular e tente de novo.", 400)
    usuario.totp_ativo = True
    usuario.totp_ultimo_passo = passo
    db.commit()


def abrir_sessao_admin(db: Session, usuario: Usuario, senha: str, codigo: str) -> tuple[str, datetime]:
    if not usuario.totp_ativo or not usuario.totp_segredo_cifrado:
        raise SegurancaAdminError("Configure a verificacao em duas etapas antes de entrar no painel.", 409)
    # 400, nunca 401: o frontend trata 401 como sessao do portal expirada e
    # desloga a pessoa, que voltava ao login a cada codigo errado (16/10).
    if not verify_password(senha, usuario.senha_hash):
        raise SegurancaAdminError(_CREDENCIAL_INVALIDA, 400)
    passo = totp.verificar(decrypt_secret(usuario.totp_segredo_cifrado), codigo)
    if passo is None:
        raise SegurancaAdminError(_CREDENCIAL_INVALIDA, 400)
    if usuario.totp_ultimo_passo is not None and passo <= usuario.totp_ultimo_passo:
        # O mesmo codigo nao abre duas sessoes (quem viu a tela nao reaproveita).
        # A senha ja conferiu, entao dizer o motivo nao ajuda quem nao a tem.
        raise SegurancaAdminError(
            "Este codigo ja foi usado. Espere o aplicativo mostrar o proximo e tente de novo.", 400
        )
    usuario.totp_ultimo_passo = passo
    db.commit()
    return create_admin_token(usuario.id, usuario.token_version)


def resetar_2fa(db: Session, usuario: Usuario) -> None:
    """Usado pelo admin geral quando alguem perde o celular."""
    usuario.totp_segredo_cifrado = None
    usuario.totp_ativo = False
    usuario.totp_ultimo_passo = None
    db.commit()


def registrar(
    usuario: Usuario | None,
    acao: str,
    resultado: str,
    ip: str | None = None,
    detalhes: dict | None = None,
) -> None:
    """Grava na auditoria com uma sessao propria: nao depende da transacao da rota
    e nunca derruba a requisicao se falhar."""
    try:
        with SessionLocal() as db:
            db.add(
                AuditoriaAdmin(
                    usuario_id=getattr(usuario, "id", None),
                    email=getattr(usuario, "email", None),
                    grupo=getattr(usuario, "grupo", None),
                    acao=acao[:160],
                    resultado=resultado[:40],
                    detalhes=json.dumps(detalhes, ensure_ascii=False, default=str)[:4000] if detalhes else None,
                    ip=(ip or None) and ip[:80],
                )
            )
            db.commit()
    except Exception:
        logger.exception("Falha ao gravar a auditoria do admin (%s).", acao)
