from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from backend.app.schemas.consultas import ConsultaStatusResponse
from backend.app.schemas.empresas import EmpresaRead
from backend.app.schemas.processos import ProcessoRead


class CertificadoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    empresa_nome: str | None = None
    empresa_cnpj: str | None = None
    nome: str
    alias: str | None = None
    client_name: str | None = None
    file_name: str | None = None
    status: str | None = None
    storage_key: str
    thumbprint: str | None = None
    subject_cn: str | None = None
    valido_de: datetime | None = None
    valido_ate: datetime | None = None
    ativo: bool
    senha_configurada: bool = False
    possui_senha: bool = False
    possui_storage_key: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CertificadoTestRequest(BaseModel):
    senha: str


class CertificadoTestResult(BaseModel):
    ok: bool
    subject_cn: str | None = None
    thumbprint: str | None = None
    valido_de: datetime | str | None = None
    valido_ate: datetime | str | None = None
    cnpj_detectado: str | None = None
    erro: str | None = None


class CertificadoAutocadastroResponse(BaseModel):
    empresa: EmpresaRead
    certificado: CertificadoRead
    processo: ProcessoRead | None = None
    consulta_status: ConsultaStatusResponse
