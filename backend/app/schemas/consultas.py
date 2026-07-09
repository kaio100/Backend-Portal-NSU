from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from backend.app.core.config import settings
from backend.app.schemas.processos import ProcessoRead


class ConsultaIniciarRequest(BaseModel):
    automatico: bool = True
    intervalo_minutos: int = Field(default=15, ge=1)
    empresa_ids: list[int] | None = None
    certificado_ids: list[int] | None = None
    nsu_inicio: int | None = Field(default=None, ge=0)
    limite: int = Field(default_factory=lambda: settings.consultas_default_limite, ge=1)
    pausa: float = Field(default_factory=lambda: settings.consultas_default_pausa, ge=0)
    gerar_pdf_espelho: bool = True
    baixar_pdf_oficial: bool = True
    forcar: bool = False

    @field_validator("empresa_ids", "certificado_ids")
    @classmethod
    def limpar_ids(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        ids = sorted({int(item) for item in value if int(item) > 0})
        return ids or None


class ConsultaWorkerStatus(BaseModel):
    enabled: bool
    dry_run: bool
    sleep: float


class ConsultaTotaisStatus(BaseModel):
    pendentes: int
    rodando: int
    finalizados: int
    erros: int
    cancelados: int


class ConsultaStatusResponse(BaseModel):
    consultando: bool
    automatico_ativo: bool
    mensagem: str
    worker: ConsultaWorkerStatus
    totais: ConsultaTotaisStatus
    processos_rodando: list[ProcessoRead]
    processos_pendentes: list[ProcessoRead]


class ConsultaDesativarRequest(BaseModel):
    cancelar_pendentes: bool = True
    cancelar_rodando: bool = True
