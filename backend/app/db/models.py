from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


class TimestampMixin:
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class Empresa(TimestampMixin, Base):
    __tablename__ = "empresas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    cnpj: Mapped[str] = mapped_column(String(14), nullable=False, unique=True, index=True)
    ambiente: Mapped[str] = mapped_column(String(20), nullable=False, default="producao")
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    certificados: Mapped[list["Certificado"]] = relationship(back_populates="empresa")
    processos: Mapped[list["Processo"]] = relationship(back_populates="empresa")
    jobs: Mapped[list["Job"]] = relationship(back_populates="empresa")
    notas: Mapped[list["Nota"]] = relationship(back_populates="empresa")
    eventos: Mapped[list["Evento"]] = relationship(back_populates="empresa")
    arquivos: Mapped[list["Arquivo"]] = relationship(back_populates="empresa")
    logs: Mapped[list["LogProcesso"]] = relationship(back_populates="empresa")
    locks: Mapped[list["LockProcessamento"]] = relationship(back_populates="empresa")


class Certificado(TimestampMixin, Base):
    __tablename__ = "certificados"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), nullable=False, index=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    senha_secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    thumbprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    subject_cn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    valido_de: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valido_ate: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    empresa: Mapped[Empresa] = relationship(back_populates="certificados")
    processos: Mapped[list["Processo"]] = relationship(back_populates="certificado")
    jobs: Mapped[list["Job"]] = relationship(back_populates="certificado")
    locks: Mapped[list["LockProcessamento"]] = relationship(back_populates="certificado")

    @property
    def senha_configurada(self) -> bool:
        return bool(self.senha_secret_ref)

    @property
    def possui_senha(self) -> bool:
        return bool(self.senha_secret_ref)

    @property
    def possui_storage_key(self) -> bool:
        return bool(self.storage_key and self.storage_key != "pending")

    @property
    def empresa_nome(self) -> str | None:
        return self.empresa.nome if self.empresa is not None else None

    @property
    def empresa_cnpj(self) -> str | None:
        return self.empresa.cnpj if self.empresa is not None else None

    @property
    def alias(self) -> str:
        return self.nome

    @property
    def client_name(self) -> str | None:
        return self.empresa_nome

    @property
    def file_name(self) -> str | None:
        if not self.storage_key:
            return None
        return self.storage_key.replace("\\", "/").rsplit("/", 1)[-1]

    @property
    def status(self) -> str:
        return "active" if self.ativo else "inactive"


class Processo(TimestampMixin, Base):
    __tablename__ = "processos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), nullable=False, index=True)
    certificado_id: Mapped[int | None] = mapped_column(ForeignKey("certificados.id"), nullable=True, index=True)
    tipo: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pendente", index=True)
    nsu_inicio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nsu_final: Mapped[int | None] = mapped_column(Integer, nullable=True)
    limite: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pausa: Mapped[float | None] = mapped_column(Float, nullable=True)
    gerar_pdf_espelho: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    baixar_pdf_oficial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    erro_resumo: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    empresa: Mapped[Empresa] = relationship(back_populates="processos")
    certificado: Mapped[Certificado | None] = relationship(back_populates="processos")
    jobs: Mapped[list["Job"]] = relationship(back_populates="processo")
    notas: Mapped[list["Nota"]] = relationship(back_populates="processo")
    arquivos: Mapped[list["Arquivo"]] = relationship(back_populates="processo")
    logs: Mapped[list["LogProcesso"]] = relationship(back_populates="processo")


class Job(TimestampMixin, Base):
    __tablename__ = "processos_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    processo_id: Mapped[int] = mapped_column(ForeignKey("processos.id"), nullable=False, index=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), nullable=False, index=True)
    certificado_id: Mapped[int | None] = mapped_column(ForeignKey("certificados.id"), nullable=True, index=True)
    tipo: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pendente", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locked_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    erro_resumo: Mapped[str | None] = mapped_column(Text, nullable=True)

    processo: Mapped[Processo] = relationship(back_populates="jobs")
    empresa: Mapped[Empresa] = relationship(back_populates="jobs")
    certificado: Mapped[Certificado | None] = relationship(back_populates="jobs")


class MonitoramentoConfig(TimestampMixin, Base):
    __tablename__ = "monitoramento_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    automatico_ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    intervalo_minutos: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    ultimo_ciclo_em: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proximo_ciclo_em: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filtros_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class NsuControle(TimestampMixin, Base):
    __tablename__ = "nsu_controle"
    __table_args__ = (
        UniqueConstraint("empresa_id", "certificado_id", name="uq_nsu_empresa_certificado"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), nullable=False, index=True)
    certificado_id: Mapped[int | None] = mapped_column(ForeignKey("certificados.id"), nullable=True, index=True)
    cnpj: Mapped[str] = mapped_column(String(14), nullable=False, index=True)
    ultimo_nsu: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    origem: Mapped[str | None] = mapped_column(String(80), nullable=True)


class Nota(TimestampMixin, Base):
    __tablename__ = "notas"
    __table_args__ = (
        UniqueConstraint("empresa_id", "chave", name="uq_notas_empresa_chave"),
        Index("ix_notas_empresa_competencia", "empresa_id", "competencia"),
        Index("ix_notas_empresa_data_emissao", "empresa_id", "data_emissao"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), nullable=False, index=True)
    processo_id: Mapped[int | None] = mapped_column(ForeignKey("processos.id"), nullable=True, index=True)
    chave: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    primeiro_nsu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ultimo_nsu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    numero_nfse: Mapped[str | None] = mapped_column(String(80), nullable=True)
    data_emissao: Mapped[Date | None] = mapped_column(Date, nullable=True)
    competencia: Mapped[Date | None] = mapped_column(Date, nullable=True)
    prestador_cnpj: Mapped[str | None] = mapped_column(String(14), nullable=True, index=True)
    prestador_nome: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tomador_cnpj: Mapped[str | None] = mapped_column(String(14), nullable=True, index=True)
    tomador_nome: Mapped[str | None] = mapped_column(String(255), nullable=True)
    valor_servico: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    valor_base: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    iss: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    irrf: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    inss: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    csrf: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    valor_liquido: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    valor_liquido_correto: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    status_valor_liquido: Mapped[str | None] = mapped_column(String(80), nullable=True)
    municipio: Mapped[str | None] = mapped_column(String(120), nullable=True)
    codigo_servico: Mapped[str | None] = mapped_column(String(80), nullable=True)
    subitem_lc116: Mapped[str | None] = mapped_column(String(20), nullable=True)
    codigo_servico_nacional: Mapped[str | None] = mapped_column(String(80), nullable=True)
    descricao_servico_nacional: Mapped[str | None] = mapped_column(Text, nullable=True)
    descricao_servico_detalhada: Mapped[str | None] = mapped_column(Text, nullable=True)
    origem_base_calculo: Mapped[str | None] = mapped_column(String(40), nullable=True)
    aliquota_iss: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    iss_retido: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    valor_iss_retido: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    valor_pis: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    valor_cofins: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    valor_csll: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    valor_csrf: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    valor_outras_retencoes: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    valor_deducoes: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    valor_desconto_incondicionado: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    valor_desconto_condicionado: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    valor_liquido_calculado: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    cnae: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status_documento: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status_rotulo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prioridade: Mapped[str | None] = mapped_column(String(40), nullable=True)
    prioridade_manual: Mapped[str | None] = mapped_column(String(40), nullable=True)
    responsavel: Mapped[str | None] = mapped_column(String(120), nullable=True)
    conferencia_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    conferencia_observacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    conferencia_atualizado_em: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conferencia_por: Mapped[str | None] = mapped_column(String(120), nullable=True)
    operator_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    operator_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status_nota_pdf: Mapped[str | None] = mapped_column(String(80), nullable=True)
    simples_xml: Mapped[str | None] = mapped_column(String(80), nullable=True)
    simples_nacional_xml: Mapped[str | None] = mapped_column(String(80), nullable=True)
    consulta_simples_api: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status_simples_nacional: Mapped[str | None] = mapped_column(String(80), nullable=True)
    incidencia_iss: Mapped[str | None] = mapped_column(String(120), nullable=True)
    divergencia: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status_fila_manual: Mapped[str | None] = mapped_column(String(40), nullable=True)
    alertas_fiscais: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_csrf: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status_irrf: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status_inss: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status_iss: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status_base_calculo: Mapped[str | None] = mapped_column(String(80), nullable=True)
    irrf_calculado: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    inss_calculado: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    pis_calculado: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    cofins_calculado: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    csll_calculado: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    csrf_calculado: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    iss_calculado: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    regra_irrf: Mapped[str | None] = mapped_column(String(20), nullable=True)
    regra_irrf_aliquota: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    regra_pcc: Mapped[str | None] = mapped_column(String(20), nullable=True)
    regra_inss: Mapped[str | None] = mapped_column(String(20), nullable=True)
    regra_observacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    sla: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sla_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entrada: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    xml_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pdf_oficial_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pdf_espelho_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    importado_em: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    empresa: Mapped[Empresa] = relationship(back_populates="notas")
    processo: Mapped[Processo | None] = relationship(back_populates="notas")
    eventos: Mapped[list["Evento"]] = relationship(back_populates="nota")
    arquivos: Mapped[list["Arquivo"]] = relationship(back_populates="nota")


class Evento(Base):
    __tablename__ = "eventos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), nullable=False, index=True)
    nota_id: Mapped[int | None] = mapped_column(ForeignKey("notas.id"), nullable=True, index=True)
    chave_evento: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    chave_afetada: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    tipo_evento: Mapped[str | None] = mapped_column(String(80), nullable=True)
    descricao: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_evento: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    xml_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    nsu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    empresa: Mapped[Empresa] = relationship(back_populates="eventos")
    nota: Mapped[Nota | None] = relationship(back_populates="eventos")


class Arquivo(TimestampMixin, Base):
    __tablename__ = "arquivos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), nullable=False, index=True)
    nota_id: Mapped[int | None] = mapped_column(ForeignKey("notas.id"), nullable=True, index=True)
    processo_id: Mapped[int | None] = mapped_column(ForeignKey("processos.id"), nullable=True, index=True)
    tipo: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    storage_backend: Mapped[str] = mapped_column(String(50), nullable=False)
    storage_bucket: Mapped[str | None] = mapped_column(String(120), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tamanho_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    empresa: Mapped[Empresa] = relationship(back_populates="arquivos")
    nota: Mapped[Nota | None] = relationship(back_populates="arquivos")
    processo: Mapped[Processo | None] = relationship(back_populates="arquivos")


class LogProcesso(Base):
    __tablename__ = "logs_processos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    processo_id: Mapped[int] = mapped_column(ForeignKey("processos.id"), nullable=False, index=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    mensagem: Mapped[str] = mapped_column(Text, nullable=False)
    contexto_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    processo: Mapped[Processo] = relationship(back_populates="logs")
    empresa: Mapped[Empresa] = relationship(back_populates="logs")


class LockProcessamento(TimestampMixin, Base):
    __tablename__ = "locks_processamento"
    __table_args__ = (
        UniqueConstraint("empresa_id", "certificado_id", name="uq_locks_empresa_certificado"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), nullable=False, index=True)
    certificado_id: Mapped[int] = mapped_column(ForeignKey("certificados.id"), nullable=False, index=True)
    locked_by: Mapped[str] = mapped_column(String(128), nullable=False)
    locked_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    empresa: Mapped[Empresa] = relationship(back_populates="locks")
    certificado: Mapped[Certificado] = relationship(back_populates="locks")


class CnpjCache(Base):
    __tablename__ = "cnpj_cache"

    cnpj: Mapped[str] = mapped_column(String(14), primary_key=True)
    fonte: Mapped[str] = mapped_column(String(80), primary_key=True, default="Invertexto")
    consulta_simples_api: Mapped[str | None] = mapped_column(String(80), nullable=True)
    codigo_cnae: Mapped[str | None] = mapped_column(String(30), nullable=True)
    descricao_cnae: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_consulta: Mapped[str | None] = mapped_column(String(80), nullable=True)
    json_resposta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_consulta: Mapped[Date | None] = mapped_column(Date, nullable=True)
    data_expiracao: Mapped[Date | None] = mapped_column(Date, nullable=True, index=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    simples_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    json_completo: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Secret(TimestampMixin, Base):
    __tablename__ = "secrets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ref: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    tipo: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
