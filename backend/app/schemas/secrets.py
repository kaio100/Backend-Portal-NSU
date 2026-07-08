from __future__ import annotations

from pydantic import BaseModel


class SecretSetRequest(BaseModel):
    senha: str
    testar_antes: bool = True


class SecretStatusResponse(BaseModel):
    certificado_id: int
    senha_configurada: bool
