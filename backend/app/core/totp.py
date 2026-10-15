"""Codigos de verificacao em duas etapas (TOTP, RFC 6238), compativeis com
Google Authenticator, Microsoft Authenticator, Authy e similares."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

PASSO_SEGUNDOS = 30
DIGITOS = 6


def gerar_segredo() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _chave(segredo: str) -> bytes:
    limpo = segredo.strip().replace(" ", "").upper()
    return base64.b32decode(limpo + "=" * (-len(limpo) % 8))


def codigo_do_passo(segredo: str, passo: int, digitos: int = DIGITOS) -> str:
    resumo = hmac.new(_chave(segredo), struct.pack(">Q", passo), hashlib.sha1).digest()
    deslocamento = resumo[-1] & 0x0F
    numero = (struct.unpack(">I", resumo[deslocamento : deslocamento + 4])[0] & 0x7FFFFFFF) % (10**digitos)
    return str(numero).zfill(digitos)


def passo_atual(agora: float | None = None) -> int:
    return int((time.time() if agora is None else agora) // PASSO_SEGUNDOS)


def verificar(segredo: str, codigo: str, agora: float | None = None, janela: int = 1) -> int | None:
    """Devolve o passo em que o codigo vale (aceita 30 s antes e depois) ou None."""
    informado = "".join(ch for ch in str(codigo or "") if ch.isdigit())
    if len(informado) != DIGITOS:
        return None
    atual = passo_atual(agora)
    for passo in range(atual - janela, atual + janela + 1):
        if hmac.compare_digest(codigo_do_passo(segredo, passo), informado):
            return passo
    return None


def uri_otpauth(segredo: str, conta: str, emissor: str = "Portal NFS-e") -> str:
    return (
        f"otpauth://totp/{quote(emissor)}:{quote(conta)}"
        f"?secret={segredo}&issuer={quote(emissor)}&digits={DIGITOS}&period={PASSO_SEGUNDOS}"
    )
