"""E-mail transacional pelo Resend (codigo de cadastro e de redefinicao de senha)."""

from __future__ import annotations

import html
import logging

import requests

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

_RESEND_ENDPOINT = "https://api.resend.com/emails"


class EmailServiceError(RuntimeError):
    """Nao foi possivel enviar o e-mail."""


def envio_disponivel() -> bool:
    return bool(settings.resend_enabled and settings.resend_api_key and settings.resend_from_email)


def enviar_email(*, para: str, assunto: str, html_corpo: str, texto_log_local: str | None = None) -> None:
    """Envia pelo Resend.

    Com o Resend desligado fora de producao, grava `texto_log_local` no log
    (ex.: o codigo) para testar localmente. Em producao, sem Resend, falha.
    """
    if not envio_disponivel():
        if settings.is_production:
            raise EmailServiceError("Envio de e-mail nao configurado (RESEND_ENABLED, RESEND_API_KEY, RESEND_FROM_EMAIL).")
        logger.warning("Resend desligado: e-mail para %s NAO enviado. %s", para, texto_log_local or assunto)
        return
    try:
        resposta = requests.post(
            _RESEND_ENDPOINT,
            json={"from": settings.resend_from_email, "to": [para], "subject": assunto, "html": html_corpo},
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise EmailServiceError("Falha de rede ao enviar o e-mail.") from exc
    if resposta.status_code >= 400:
        logger.error("Resend recusou o envio (%s): %s", resposta.status_code, resposta.text[:300])
        raise EmailServiceError(f"O servico de e-mail recusou o envio ({resposta.status_code}).")


def _modelo(titulo: str, paragrafo: str, codigo: str, validade_minutos: int) -> str:
    return (
        '<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#16202b">'
        f"<h2 style=\"margin:0 0 12px\">{html.escape(titulo)}</h2>"
        f"<p>{html.escape(paragrafo)}</p>"
        f'<p style="font-size:30px;font-weight:bold;letter-spacing:6px;margin:20px 0">{html.escape(codigo)}</p>'
        f"<p>O codigo vale por {validade_minutos} minutos. Se voce nao pediu isto, ignore este e-mail.</p>"
        '<p style="color:#6b7785;font-size:12px">Portal NFS-e</p></div>'
    )


def enviar_codigo_cadastro(para: str, codigo: str) -> None:
    validade = settings.codigo_email_validade_minutos
    enviar_email(
        para=para,
        assunto="Seu codigo para criar a conta no Portal NFS-e",
        html_corpo=_modelo("Confirme seu e-mail", "Use o codigo abaixo para ativar sua conta no Portal NFS-e.", codigo, validade),
        texto_log_local=f"Codigo de cadastro: {codigo}",
    )


def enviar_codigo_senha(para: str, codigo: str) -> None:
    validade = settings.codigo_email_validade_minutos
    enviar_email(
        para=para,
        assunto="Seu codigo para redefinir a senha do Portal NFS-e",
        html_corpo=_modelo("Redefinir senha", "Use o codigo abaixo para criar uma nova senha no Portal NFS-e.", codigo, validade),
        texto_log_local=f"Codigo de redefinicao de senha: {codigo}",
    )
