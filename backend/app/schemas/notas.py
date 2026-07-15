from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NotaListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    processo_id: int | None = None
    chave: str
    numero_nfse: str | None = None
    data_emissao: date | None = None
    competencia: date | None = None
    prestador_cnpj: str | None = None
    prestador_nome: str | None = None
    tomador_cnpj: str | None = None
    tomador_nome: str | None = None
    valor_servico: Decimal | None = None
    valor_liquido: Decimal | None = None
    status_documento: str | None = None
    status_rotulo: str | None = None
    xml_storage_key: str | None = None
    pdf_oficial_storage_key: str | None = None
    pdf_espelho_storage_key: str | None = None
    importado_em: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None
    numero: str | None = None
    prestador: str | None = None
    cnpj_prestador: str | None = None
    tomador: str | None = None
    cnpj_tomador: str | None = None
    valor: Decimal | None = None
    status: str | None = None
    empresa_cnpj: str | None = None
    nota_tipo: str | None = None
    tipo_nota: str | None = None
    direcao_nota: str | None = None
    competencia_operacional: date | None = None
    competencia_original: date | None = None
    prioridade: str | None = None
    responsavel: str | None = None
    conferencia_status: str | None = None
    conferencia_observacao: str | None = None
    conferencia_atualizado_em: datetime | None = None
    conferencia_por: str | None = None
    status_nota_pdf: str | None = None
    simples_xml: str | None = None
    simples_nacional: str | None = None
    simples_nacional_xml: str | None = None
    consulta_simples_api: str | None = None
    status_simples_nacional: str | None = None
    incidencia_iss: str | None = None
    divergencia: str | None = None
    sla: dict | str | None = None
    sla_status: str | None = None
    entrada: datetime | None = None
    empresa_nome: str | None = None
    municipio: str | None = None
    codigo_servico: str | None = None
    codigo_servico_raw: str | None = None
    codigo_servico_display: str | None = None
    subitem_lc116: str | None = None
    codigo_servico_nacional: str | None = None
    descricao_servico_nacional: str | None = None
    descricao_servico_detalhada: str | None = None
    origem_base_calculo: str | None = None
    cnae: str | None = None
    valor_base: Decimal | None = None
    valor_base_calculo: Decimal | None = None
    iss: Decimal | None = None
    valor_iss: Decimal | None = None
    iss_retido: bool | None = None
    valor_iss_retido: Decimal | None = None
    irrf: Decimal | None = None
    valor_irrf: Decimal | None = None
    inss: Decimal | None = None
    valor_inss: Decimal | None = None
    csrf: Decimal | None = None
    valor_pis: Decimal | None = None
    valor_cofins: Decimal | None = None
    valor_csll: Decimal | None = None
    valor_csrf: Decimal | None = None
    valor_outras_retencoes: Decimal | None = None
    valor_deducoes: Decimal | None = None
    valor_desconto_incondicionado: Decimal | None = None
    valor_desconto_condicionado: Decimal | None = None
    valor_liquido_correto: Decimal | None = None
    valor_liquido_calculado: Decimal | None = None
    status_valor_liquido: str | None = None
    status_nota: str | None = None
    observacao_interna: str | None = Field(default=None, json_schema_extra={"readOnly": True})
    simples_nacional_api: str | None = None
    prioridade_manual: str | None = None
    status_csrf: str | None = None
    status_irrf: str | None = None
    status_inss: str | None = None
    status_iss: str | None = None
    status_base_calculo: str | None = None
    status_fila_manual: str | None = None
    status_fila: str | None = None
    status_fila_final: str | None = None
    divergencia_fila_final: bool | None = None
    divergencia_fila_label: str | None = None
    prioridade_fila: str | None = None
    entrada_fila: datetime | None = None
    sla_operacional: dict | None = None
    irrf_calculado: Decimal | None = None
    inss_calculado: Decimal | None = None
    pis_calculado: Decimal | None = None
    cofins_calculado: Decimal | None = None
    csll_calculado: Decimal | None = None
    csrf_calculado: Decimal | None = None
    iss_calculado: Decimal | None = None
    regra_irrf: str | None = None
    regra_irrf_aliquota: Decimal | None = None
    regra_pcc: str | None = None
    regra_inss: str | None = None
    regra_observacao: str | None = None
    campos_ausentes_xml: list[str] | None = None
    alertas_fiscais: str | list[str] | None = Field(default=None, json_schema_extra={"readOnly": True})

    @model_validator(mode="after")
    def preencher_aliases_frontend(self):
        self.importado_em = self.importado_em or self.updated_at or self.created_at
        self.criado_em = self.criado_em or self.created_at
        self.atualizado_em = self.atualizado_em or self.updated_at
        self.numero = self.numero or self.numero_nfse
        self.prestador = self.prestador or self.prestador_nome
        self.cnpj_prestador = self.cnpj_prestador or self.prestador_cnpj
        self.tomador = self.tomador or self.tomador_nome
        self.cnpj_tomador = self.cnpj_tomador or self.tomador_cnpj
        self.valor = self.valor or self.valor_servico
        self.status = self.status or self.status_documento
        self.valor_base_calculo = self.valor_base_calculo or self.valor_base
        self.valor_iss = self.valor_iss or self.iss
        self.valor_irrf = self.valor_irrf or self.irrf
        self.valor_inss = self.valor_inss or self.inss
        self.valor_csrf = self.valor_csrf or self.csrf
        self.status_nota = self.status_nota or self.status_documento
        self.simples_xml = self.simples_xml or self.simples_nacional_xml
        self.simples_nacional = self.simples_nacional or self.simples_xml
        self.simples_nacional_api = self.simples_nacional_api or self.consulta_simples_api
        self.prioridade = self.prioridade or self.prioridade_manual
        self.competencia_original = self.competencia_original or self.competencia
        return self


class NotaDetail(NotaListItem):
    pass


class NotasTodasResponse(BaseModel):
    items: list[NotaListItem]
    total: int


class NotaConferenciaUpdate(BaseModel):
    conferencia_status: str
    conferencia_observacao: str | None = None
    observacao: str | None = None
    observacao_interna: str | None = None
    responsavel: str | None = None
    prioridade: str | None = None
    prioridade_manual: str | None = None
    status_fila_manual: str | None = None
    divergencia: str | None = None
    valor_liquido_correto: Decimal | None = None
    alertas_fiscais: str | list[str] | None = None
    atualizado_por: str | None = None
    atualizado_em: datetime | None = None
    operator_name: str | None = None
    operator_id: str | None = None
    device_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def bloquear_campos_somente_sistema(cls, data):
        if isinstance(data, dict):
            bloqueados = [
                campo
                for campo in ("observacao_interna", "alertas_fiscais")
                if campo in data
            ]
            if bloqueados:
                raise ValueError(
                    "observacao_interna e alertas_fiscais sao campos somente leitura, preenchidos apenas pelo sistema."
                )
        return data

    @model_validator(mode="after")
    def normalizar(self):
        status = (self.conferencia_status or "").strip().lower()
        allowed = {"pendente", "ok", "corrigir", "observacao"}
        if status not in allowed:
            raise ValueError("conferencia_status invalido.")
        self.conferencia_status = status
        # "Observacao interna" e "Alertas fiscais" sao somente leitura: quem
        # decide o que vai neles e o sistema (analise fiscal automatica),
        # nao o usuario. Por isso `observacao_interna` nao entra mais na
        # composicao de `conferencia_observacao` — so o campo "Observacao"
        # (comentario livre do revisor) pode alterar esse valor.
        self.conferencia_observacao = (self.conferencia_observacao or self.observacao or "").strip() or None
        self.observacao = (self.observacao or "").strip() or None
        self.observacao_interna = None
        self.responsavel = (self.responsavel or "").strip() or None
        self.prioridade = (self.prioridade or "").strip() or None
        self.prioridade_manual = (self.prioridade_manual or "").strip() or None
        self.status_fila_manual = (self.status_fila_manual or "").strip() or None
        self.divergencia = (self.divergencia or "").strip() or None
        # Alertas fiscais so podem vir da analise automatica (calcular_retencoes_esperadas),
        # nunca de um payload de usuario — mesmo que alguem chame a API direto.
        self.alertas_fiscais = None
        self.atualizado_por = (self.atualizado_por or "").strip() or None
        self.operator_name = (self.operator_name or "").strip() or None
        self.operator_id = (self.operator_id or "").strip() or None
        self.device_id = (self.device_id or "").strip() or None
        return self


class NotasDownloadFiltros(BaseModel):
    empresa_id: int | None = None
    certificado_id: int | None = None
    processo_id: int | None = None
    status: str | None = None
    status_documento: str | None = None
    numero: str | None = None
    chave: str | None = None
    cnpj_prestador: str | None = None
    prestador_cnpj: str | None = None
    cnpj_tomador: str | None = None
    tomador_cnpj: str | None = None
    data_inicial: date | None = None
    data_final: date | None = None
    data_inicio: date | None = None
    data_fim: date | None = None
    competencia_inicio: date | None = None
    competencia_fim: date | None = None
    conferencia_status: str | None = None
    conferencia: str | None = None
    prioridade: str | None = None
    responsavel: str | None = None
    status_nota_pdf: str | None = None
    simples_nacional_xml: str | None = None
    consulta_simples_api: str | None = None
    status_simples_nacional: str | None = None
    incidencia_iss: str | None = None
    divergencia: str | None = None
    sla_status: str | None = None
    sla: str | None = None
    tipo_nota: str | None = None
    direcao_nota: str | None = None
    somente_divergentes: bool = False
    valor_min: Decimal | None = None
    valor_max: Decimal | None = None
    busca: str | None = None
    sort: str = "recentes"

    @model_validator(mode="after")
    def normalizar_aliases(self):
        self.status_documento = self.status_documento or self.status
        self.prestador_cnpj = self.prestador_cnpj or self.cnpj_prestador
        self.tomador_cnpj = self.tomador_cnpj or self.cnpj_tomador
        self.data_inicio = self.data_inicio or self.data_inicial
        self.data_fim = self.data_fim or self.data_final
        self.conferencia_status = self.conferencia_status or self.conferencia
        self.sla_status = self.sla_status or self.sla
        if self.tipo_nota:
            self.tipo_nota = self.tipo_nota.strip().lower()
        if self.direcao_nota:
            self.direcao_nota = self.direcao_nota.strip().lower()
        self.sort = self.sort if self.sort in {"recentes", "emissao"} else "recentes"
        return self


class NotasDownloadLoteRequest(BaseModel):
    filtros: NotasDownloadFiltros = Field(default_factory=NotasDownloadFiltros)
    nota_ids: list[int] | None = None
    incluir_xml: bool = True
    incluir_pdf: bool = True
    preferir_pdf_original: bool = True

    @model_validator(mode="after")
    def limpar_nota_ids(self):
        if self.nota_ids is not None:
            seen: set[int] = set()
            cleaned: list[int] = []
            for raw_id in self.nota_ids:
                nota_id = int(raw_id)
                if nota_id > 0 and nota_id not in seen:
                    seen.add(nota_id)
                    cleaned.append(nota_id)
            self.nota_ids = cleaned or None
        return self


class NotaArquivoResumo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nota_id: int | None = None
    tipo: str
    filename: str | None = None
    content_type: str | None = None
    tamanho_bytes: int | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    storage_key: str | None = None
    created_at: datetime | None = None

    @model_validator(mode="after")
    def normalizar_saida(self):
        normalized = (self.tipo or "").lower()
        if normalized == "xml":
            self.tipo = "XML"
        elif normalized in {"pdf_oficial", "pdf_original", "oficial"}:
            self.tipo = "PDF_ORIGINAL"
        elif normalized in {"pdf_espelho", "espelho"}:
            self.tipo = "PDF_ESPELHO"
        self.filename = self.filename or PurePosixPath((self.storage_key or "").replace("\\", "/")).name
        self.size_bytes = self.size_bytes if self.size_bytes is not None else self.tamanho_bytes
        return self
