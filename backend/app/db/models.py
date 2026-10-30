from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    literal_column,
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


class Grupo(TimestampMixin, Base):
    __tablename__ = "grupos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    codigo: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)


class Empresa(TimestampMixin, Base):
    __tablename__ = "empresas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(255), nullable=False)
    cnpj: Mapped[str] = mapped_column(String(14), nullable=False, unique=True, index=True)
    ambiente: Mapped[str] = mapped_column(String(20), nullable=False, default="producao")
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    grupo: Mapped[str] = mapped_column(String(40), nullable=False, default="planning_hub", index=True)

    certificados: Mapped[list["Certificado"]] = relationship(back_populates="empresa")
    processos: Mapped[list["Processo"]] = relationship(back_populates="empresa")
    jobs: Mapped[list["Job"]] = relationship(back_populates="empresa")
    notas: Mapped[list["Nota"]] = relationship(back_populates="empresa")
    eventos: Mapped[list["Evento"]] = relationship(back_populates="empresa")
    arquivos: Mapped[list["Arquivo"]] = relationship(back_populates="empresa")
    logs: Mapped[list["LogProcesso"]] = relationship(back_populates="empresa")
    locks: Mapped[list["LockProcessamento"]] = relationship(back_populates="empresa")
    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="empresa")


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
    # Legado: o download do PDF oficial do ADN foi desativado. Mantida por
    # compatibilidade com bancos existentes (NOT NULL sem default no servidor);
    # o backend sempre grava False e nao a le.
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
    __table_args__ = (Index("ix_processos_jobs_status_updated_at", "status", "updated_at"),)

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
    grupo: Mapped[str] = mapped_column(String(40), nullable=False, default="planning_hub", unique=True, index=True)


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
    ultima_reconciliacao_em: Mapped[Date | None] = mapped_column(Date, nullable=True)


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
    codigo_servico_raw: Mapped[str | None] = mapped_column(String(80), nullable=True)
    codigo_servico_display: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
    arquivada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    arquivada_em: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arquivo_backup_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    empresa: Mapped[Empresa] = relationship(back_populates="notas")
    processo: Mapped[Processo | None] = relationship(back_populates="notas")
    eventos: Mapped[list["Evento"]] = relationship(back_populates="nota")
    arquivos: Mapped[list["Arquivo"]] = relationship(back_populates="nota")


# O cursor usa COALESCE: um indice simples nas colunas nao corresponde a essa
# ordenacao. Literais com fuso explicito evitam casts dependentes do timezone.
for _sort, _colunas in (
    ("recentes", (Nota.importado_em, Nota.updated_at, Nota.id)),
    ("emissao", (Nota.data_emissao, Nota.importado_em, Nota.updated_at, Nota.id)),
):
    _expressoes = [
        coluna if coluna.key == "id" else func.coalesce(
            coluna,
            literal_column("DATE '1900-01-01'" if coluna.key == "data_emissao" else
                           "TIMESTAMPTZ '1900-01-01 00:00:00+00'"),
        )
        for coluna in _colunas
    ]
    Index(f"ix_notas_cursor_{_sort}", *_expressoes).ddl_if(dialect="postgresql")


class ConferenciaHistorico(Base):
    """Cada gravacao da analise fiscal de uma nota: quem, quando e o que mudou.

    Guarda chave e empresa porque o arquivamento apaga notas antigas (nota_id
    vira nulo) e nome/e-mail porque o usuario pode ser excluido depois.
    """

    __tablename__ = "notas_conferencia_historico"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nota_id: Mapped[int | None] = mapped_column(ForeignKey("notas.id"), nullable=True, index=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), nullable=False, index=True)
    chave: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True, index=True)
    usuario_nome: Mapped[str | None] = mapped_column(String(255), nullable=True)
    usuario_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    acao: Mapped[str] = mapped_column(String(20), nullable=False)  # "analise" ou "retificacao"
    alteracoes: Mapped[dict] = mapped_column(JSON, nullable=False)  # {campo: {"de": ..., "para": ...}}
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Evento(Base):
    __tablename__ = "eventos"
    __table_args__ = (
        # Reprocessar o mesmo XML nao pode duplicar o evento.
        Index("uq_eventos_empresa_chave_evento", "empresa_id", "chave_evento", unique=True),
    )

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


class Usuario(TimestampMixin, Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nome: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    grupo: Mapped[str] = mapped_column(String(40), nullable=False, default="planning_hub", index=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    papel: Mapped[str] = mapped_column(String(20), nullable=False, default="operador", index=True)
    # Conta criada por convite so fica ativa depois de confirmar o e-mail.
    email_verificado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # Vai no JWT; trocar ou redefinir a senha incrementa e derruba os tokens antigos.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Verificacao em duas etapas (TOTP), obrigatoria para abrir a sessao de administrador.
    # O segredo fica cifrado com SECRETS_KEY; so vale depois de confirmado com um codigo.
    totp_segredo_cifrado: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Ultimo passo de 30 s aceito: o mesmo codigo nao serve duas vezes.
    totp_ultimo_passo: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    empresa: Mapped[Empresa] = relationship(back_populates="usuarios")


class AcessoUsuario(Base):
    __tablename__ = "acessos_usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False, index=True)
    grupo: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    ip: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ConviteCadastro(TimestampMixin, Base):
    """Link de convite para criar conta num grupo (formato ja existente em producao)."""

    __tablename__ = "convites_cadastro"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    grupo: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    nome: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    max_usos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usos_atuais: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    criado_por_usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)


class VerificacaoEmailToken(Base):
    """Codigo enviado por e-mail para confirmar a conta criada por convite."""

    __tablename__ = "verificacoes_email_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    codigo_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tentativas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    convite_id: Mapped[int | None] = mapped_column(ForeignKey("convites_cadastro.id"), nullable=True)


class RedefinicaoSenhaToken(Base):
    """Codigo enviado por e-mail para redefinir a senha."""

    __tablename__ = "redefinicoes_senha_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_solicitante: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tentativas: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class TentativaAcesso(Base):
    """Uma tentativa em rota com limite (login, codigo, senha de certificado).

    Fica no banco para o limite valer entre processos e sobreviver a deploy e
    reinicio. `chave` e o hash do motivo + IP/e-mail: nao guarda dado pessoal.
    """

    __tablename__ = "tentativas_acesso"
    __table_args__ = (Index("ix_tentativas_acesso_chave_criado_em", "chave", "criado_em"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chave: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    criado_em: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class AuditoriaAdmin(Base):
    """Acao feita no painel administrativo ou tentativa de abrir a sessao de admin.

    O nome nao e "auditoria_admin": essa tabela existe em producao como sobra de
    set/2026, com outras colunas e vazia (ver 0001_baseline).
    """

    __tablename__ = "auditoria_painel_admin"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    grupo: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    acao: Mapped[str] = mapped_column(String(160), nullable=False)
    resultado: Mapped[str] = mapped_column(String(40), nullable=False)
    detalhes: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ErroVisto(Base):
    """Ate quando os erros de um grupo ja foram vistos no painel admin ("Limpar").

    Nao apaga processos nem logs (sao historico): /admin/erros so passa a mostrar
    o que aconteceu depois de visto_ate.
    """

    __tablename__ = "erros_vistos"

    grupo: Mapped[str] = mapped_column(String(40), primary_key=True)
    visto_ate: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    usuario_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

