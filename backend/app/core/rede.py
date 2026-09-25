"""IP de quem fez a requisicao, mesmo atras do proxy do Railway."""

from __future__ import annotations

import ipaddress

from starlette.requests import Request

# Enderecos de proxies internos (Railway usa 100.64.0.0/10). So quando a
# conexao vem de um deles o X-Forwarded-For e considerado.
_REDES_PROXY = tuple(
    ipaddress.ip_network(rede)
    for rede in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "127.0.0.0/8", "::1/128", "fc00::/7")
)


def ip_cliente(request: Request) -> str:
    """IP real do usuario.

    Atras do proxy, request.client.host e o IP do proxy: o limite de
    tentativas de login contava todo mundo junto (em producao, todos os
    acessos saiam como 100.64.x.x). Usa o ultimo endereco do X-Forwarded-For,
    o que o proxy acrescentou; os anteriores vem do cliente e podem ser
    forjados.
    """
    direto = request.client.host if request.client else ""
    try:
        endereco = ipaddress.ip_address(direto)
    except ValueError:
        return direto or "desconhecido"
    if any(endereco in rede for rede in _REDES_PROXY):
        partes = [parte.strip() for parte in request.headers.get("x-forwarded-for", "").split(",") if parte.strip()]
        if partes:
            return partes[-1]
    return direto
