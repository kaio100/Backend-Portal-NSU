from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import re

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Arquivo, Empresa, Nota
from backend.app.repositories import arquivos_repo, empresas_repo, notas_repo
from backend.app.services import cnpj_cache_service
from backend.app.services.operational_fields_service import aplicar_campos_operacionais


class NotaServiceError(RuntimeError):
    pass


def _only_digits(value: str | None) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _previous_month(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _competencia_operacional(
    nota: Nota,
    nota_tipo: str,
    competencia_fim: date | None = None,
) -> date | None:
    competencia = nota.competencia or nota.data_emissao
    if competencia is None:
        return None
    if nota_tipo == "recebida" and competencia_fim is not None:
        dia_corte = max(0, int(settings.notas_recebidas_dia_corte_mes_anterior or 0))
        next_month = _next_month(competencia_fim)
        limite_extra = date(next_month.year, next_month.month, dia_corte) if dia_corte else competencia_fim
        if competencia > competencia_fim and competencia <= limite_extra:
            return _month_start(competencia_fim)
    return _month_start(competencia)


def _classificar_nota(nota: Nota, empresa_cnpj: str) -> str:
    return classificar_direcao_nota(nota, empresa_cnpj)


def normalizar_tipo_nota(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    if text in {"tomada", "tomado", "recebida", "recebido"}:
        return "tomada"
    if text in {"prestada", "prestado", "emitida", "emitido"}:
        return "prestada"
    if text in {"indefinida", "indefinido"}:
        return "indefinida"
    if text in {"inconsistente", "inconsistentes"}:
        return "inconsistente"
    raise NotaServiceError("tipo_nota invalido.")


def normalizar_direcao_nota(value: str | None) -> str | None:
    text = (value or "").strip().lower()
    if not text:
        return None
    if text in {"recebida", "recebido", "tomada", "tomado"}:
        return "recebida"
    if text in {"emitida", "emitido", "prestada", "prestado"}:
        return "emitida"
    if text in {"indefinida", "indefinido"}:
        return "indefinida"
    if text in {"inconsistente", "inconsistentes"}:
        return "inconsistente"
    raise NotaServiceError("direcao_nota invalida.")


def tipo_para_direcao(tipo_nota: str | None) -> str | None:
    tipo = normalizar_tipo_nota(tipo_nota)
    if tipo == "tomada":
        return "recebida"
    if tipo == "prestada":
        return "emitida"
    return tipo


def direcao_para_tipo(direcao_nota: str | None) -> str | None:
    direcao = normalizar_direcao_nota(direcao_nota)
    if direcao == "recebida":
        return "tomada"
    if direcao == "emitida":
        return "prestada"
    return direcao


def classificar_direcao_nota(nota: Nota, empresa_cnpj: str | None) -> str:
    cnpj = _only_digits(empresa_cnpj)
    prestador = _only_digits(nota.prestador_cnpj)
    tomador = _only_digits(nota.tomador_cnpj)
    if not cnpj:
        return "indefinida"
    prestador_match = bool(prestador and prestador == cnpj)
    tomador_match = bool(tomador and tomador == cnpj)
    if prestador_match and tomador_match:
        return "inconsistente"
    if tomador_match:
        return "recebida"
    if prestador_match:
        return "emitida"
    return "indefinida"


def classificar_tipo_nota(nota: Nota, empresa_cnpj: str | None) -> str:
    direcao = classificar_direcao_nota(nota, empresa_cnpj)
    return direcao_para_tipo(direcao) or "indefinida"


def _empresa_cnpj_nota(nota: Nota) -> str:
    empresa = getattr(nota, "empresa", None)
    if empresa is not None:
        return _only_digits(empresa.cnpj)
    return _only_digits(getattr(nota, "empresa_cnpj", None))


def _anotar_classificacao(
    nota: Nota,
    empresa_cnpj: str,
    competencia_fim: date | None = None,
) -> Nota:
    nota_tipo = _classificar_nota(nota, empresa_cnpj)
    setattr(nota, "empresa_cnpj", _only_digits(empresa_cnpj))
    setattr(nota, "nota_tipo", nota_tipo)
    setattr(nota, "direcao_nota", nota_tipo)
    setattr(nota, "tipo_nota", direcao_para_tipo(nota_tipo))
    setattr(nota, "competencia_original", nota.competencia)
    setattr(nota, "competencia_operacional", _competencia_operacional(nota, nota_tipo, competencia_fim))
    return nota


def _empresa_ou_erro(db: Session, empresa_id: int) -> Empresa:
    empresa = empresas_repo.get_empresa(db, empresa_id)
    if empresa is None:
        raise NotaServiceError("Empresa nao encontrada.")
    return empresa


def _canonical_tipo_arquivo(tipo: str | None) -> str:
    normalized = (tipo or "").lower()
    if normalized == "xml":
        return "XML"
    if normalized in {"pdf_original", "pdf_oficial", "oficial"}:
        return "PDF_ORIGINAL"
    if normalized in {"pdf_espelho", "espelho"}:
        return "PDF_ESPELHO"
    return tipo or ""


def _selecionar_arquivos_visiveis(arquivos: list[Arquivo]) -> list[Arquivo]:
    por_tipo: dict[str, list[Arquivo]] = {"XML": [], "PDF_ORIGINAL": [], "PDF_ESPELHO": []}
    for arquivo in arquivos:
        tipo = _canonical_tipo_arquivo(arquivo.tipo)
        if tipo in por_tipo:
            por_tipo[tipo].append(arquivo)

    selecionados: list[Arquivo] = []
    if por_tipo["XML"]:
        selecionados.append(por_tipo["XML"][0])
    if por_tipo["PDF_ORIGINAL"]:
        selecionados.append(por_tipo["PDF_ORIGINAL"][0])
    elif por_tipo["PDF_ESPELHO"]:
        selecionados.append(por_tipo["PDF_ESPELHO"][0])
    return selecionados


def _cnpj_contraparte(nota: Nota, direcao_nota: str) -> str | None:
    """CNPJ da outra parte na transacao (nao o CNPJ da propria empresa),
    usado para consultar o cache de Simples Nacional dessa contraparte."""
    if direcao_nota == "emitida":
        return _only_digits(nota.tomador_cnpj) or None
    if direcao_nota == "recebida":
        return _only_digits(nota.prestador_cnpj) or None
    return _only_digits(nota.prestador_cnpj) or _only_digits(nota.tomador_cnpj) or None


def _consultas_simples_api_lote(db: Session, notas: list[Nota]) -> dict[int, str | None]:
    """Resolve consulta_simples_api por nota a partir do cache de CNPJ ja
    consultado (sem chamada externa), em lote para evitar N+1."""
    empresa_cnpj_cache: dict[int | None, str] = {}
    cnpj_por_nota: dict[int, str] = {}
    for nota in notas:
        empresa_id = getattr(nota, "empresa_id", None)
        if empresa_id not in empresa_cnpj_cache:
            empresa_cnpj_cache[empresa_id] = _empresa_cnpj_nota(nota)
        direcao = classificar_direcao_nota(nota, empresa_cnpj_cache[empresa_id])
        cnpj = _cnpj_contraparte(nota, direcao)
        if cnpj:
            cnpj_por_nota[int(nota.id)] = cnpj

    cnpjs = set(cnpj_por_nota.values())
    if not cnpjs:
        return {}
    caches = cnpj_cache_service.get_caches_validos(db, cnpjs)

    resultado: dict[int, str | None] = {}
    for nota_id, cnpj in cnpj_por_nota.items():
        cache = caches.get(cnpj)
        if not cache:
            continue
        valor = cache.get("consulta_simples_api")
        if valor and valor != "Não disponível":
            resultado[nota_id] = valor
    return resultado


def _anotar_detalhe_frontend(nota: Nota, consulta_simples_api: str | None = None) -> Nota:
    empresa = getattr(nota, "empresa", None)
    if empresa is not None:
        setattr(nota, "empresa_nome", empresa.nome)
        setattr(nota, "empresa_cnpj", _only_digits(empresa.cnpj))
    empresa_cnpj = _empresa_cnpj_nota(nota)
    direcao_nota = classificar_direcao_nota(nota, empresa_cnpj)
    tipo_nota = direcao_para_tipo(direcao_nota)
    setattr(nota, "nota_tipo", direcao_nota)
    setattr(nota, "direcao_nota", direcao_nota)
    setattr(nota, "tipo_nota", tipo_nota)
    setattr(nota, "status_nota", nota.status_documento)
    setattr(nota, "simples_nacional_api", nota.status_simples_nacional)
    missing: list[str] = []
    for field, label in (
        ("numero_nfse", "numero"),
        ("chave", "chave"),
        ("prestador_cnpj", "cnpj_prestador"),
        ("tomador_cnpj", "cnpj_tomador"),
        ("valor_servico", "valor_servico"),
    ):
        if getattr(nota, field, None) in {None, ""}:
            missing.append(label)
    setattr(nota, "campos_ausentes_xml", missing)
    alertas: list[str] = []
    if nota.divergencia:
        alertas.append(str(nota.divergencia))
    if getattr(nota, "alertas_fiscais", None):
        alertas.append(str(nota.alertas_fiscais))
    if missing:
        alertas.append("Campos obrigatorios ausentes no XML")
    if not getattr(nota, "alertas_fiscais", None):
        setattr(nota, "alertas_fiscais", "\n".join(alertas) or None)
    return aplicar_campos_operacionais(nota, consulta_simples_api=consulta_simples_api)


def listar_notas(
    db: Session,
    empresa_id: int | None = None,
    certificado_id: int | None = None,
    processo_id: int | None = None,
    status_documento: str | None = None,
    status: str | None = None,
    numero: str | None = None,
    prestador_cnpj: str | None = None,
    tomador_cnpj: str | None = None,
    chave: str | None = None,
    busca: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    competencia_inicio: date | None = None,
    competencia_fim: date | None = None,
    conferencia_status: str | None = None,
    prioridade: str | None = None,
    responsavel: str | None = None,
    status_nota_pdf: str | None = None,
    simples_nacional_xml: str | None = None,
    consulta_simples_api: str | None = None,
    status_simples_nacional: str | None = None,
    incidencia_iss: str | None = None,
    divergencia: str | None = None,
    sla_status: str | None = None,
    tipo_nota: str | None = None,
    direcao_nota: str | None = None,
    limit: int = 100,
    offset: int = 0,
    sort: str = "recentes",
) -> list[Nota]:
    filtro_tipo = normalizar_tipo_nota(tipo_nota)
    filtro_direcao = normalizar_direcao_nota(direcao_nota)
    if filtro_tipo and filtro_direcao and tipo_para_direcao(filtro_tipo) != filtro_direcao:
        return []
    classificar = bool(filtro_tipo or filtro_direcao)
    repo_limit = 5000 if classificar else limit
    repo_offset = 0 if classificar else offset

    notas = notas_repo.list_notas(
        db,
        empresa_id=empresa_id,
        certificado_id=certificado_id,
        processo_id=processo_id,
        status_documento=status_documento,
        status=status,
        numero=numero,
        prestador_cnpj=_only_digits(prestador_cnpj) or None,
        tomador_cnpj=_only_digits(tomador_cnpj) or None,
        chave=chave,
        busca=busca,
        data_inicio=data_inicio,
        data_fim=data_fim,
        competencia_inicio=competencia_inicio,
        competencia_fim=competencia_fim,
        conferencia_status=conferencia_status,
        prioridade=prioridade,
        responsavel=responsavel,
        status_nota_pdf=status_nota_pdf,
        simples_nacional_xml=simples_nacional_xml,
        consulta_simples_api=consulta_simples_api,
        status_simples_nacional=status_simples_nacional,
        incidencia_iss=incidencia_iss,
        divergencia=divergencia,
        sla_status=sla_status,
        limit=repo_limit,
        offset=repo_offset,
        sort=sort,
    )
    mapa_consulta_simples = _consultas_simples_api_lote(db, notas)
    anotadas = [_anotar_detalhe_frontend(nota, mapa_consulta_simples.get(int(nota.id))) for nota in notas]
    if classificar:
        anotadas = [
            nota for nota in anotadas
            if (filtro_tipo is None or getattr(nota, "tipo_nota", None) == filtro_tipo)
            and (filtro_direcao is None or getattr(nota, "direcao_nota", None) == filtro_direcao)
        ]
        safe_limit = min(max(limit, 1), 5000)
        safe_offset = max(offset, 0)
        return anotadas[safe_offset : safe_offset + safe_limit]
    return anotadas


def listar_todas_notas(
    db: Session,
    empresa_id: int | None = None,
    certificado_id: int | None = None,
    processo_id: int | None = None,
    status_documento: str | None = None,
    status: str | None = None,
    numero: str | None = None,
    prestador_cnpj: str | None = None,
    tomador_cnpj: str | None = None,
    chave: str | None = None,
    busca: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    competencia_inicio: date | None = None,
    competencia_fim: date | None = None,
    conferencia_status: str | None = None,
    prioridade: str | None = None,
    responsavel: str | None = None,
    status_nota_pdf: str | None = None,
    simples_nacional_xml: str | None = None,
    consulta_simples_api: str | None = None,
    status_simples_nacional: str | None = None,
    incidencia_iss: str | None = None,
    divergencia: str | None = None,
    sla_status: str | None = None,
    tipo_nota: str | None = None,
    direcao_nota: str | None = None,
    somente_divergentes: bool = False,
    valor_min: Decimal | None = None,
    valor_max: Decimal | None = None,
    sort: str = "recentes",
) -> dict:
    filtro_tipo = normalizar_tipo_nota(tipo_nota)
    filtro_direcao = normalizar_direcao_nota(direcao_nota)
    if filtro_tipo and filtro_direcao and tipo_para_direcao(filtro_tipo) != filtro_direcao:
        return {"items": [], "total": 0}

    batch_size = 5000
    offset = 0
    items: list[Nota] = []
    while True:
        batch = listar_notas(
            db,
            empresa_id=empresa_id,
            certificado_id=certificado_id,
            processo_id=processo_id,
            status_documento=status_documento,
            status=status,
            numero=numero,
            prestador_cnpj=prestador_cnpj,
            tomador_cnpj=tomador_cnpj,
            chave=chave,
            busca=busca,
            data_inicio=data_inicio,
            data_fim=data_fim,
            competencia_inicio=competencia_inicio,
            competencia_fim=competencia_fim,
            conferencia_status=conferencia_status,
            prioridade=prioridade,
            responsavel=responsavel,
            status_nota_pdf=status_nota_pdf,
            simples_nacional_xml=simples_nacional_xml,
            consulta_simples_api=consulta_simples_api,
            status_simples_nacional=status_simples_nacional,
            incidencia_iss=incidencia_iss,
            divergencia=divergencia,
            sla_status=sla_status,
            tipo_nota=None,
            direcao_nota=None,
            limit=batch_size,
            offset=offset,
            sort=sort,
        )
        items.extend(batch)
        if len(batch) < batch_size:
            break
        offset += batch_size

    items = _filtrar_notas_calculadas(
        items,
        tipo_nota=filtro_tipo,
        direcao_nota=filtro_direcao,
        somente_divergentes=somente_divergentes,
        valor_min=valor_min,
        valor_max=valor_max,
    )
    return {"items": items, "total": len(items)}


def _filtrar_notas_calculadas(
    notas: list[Nota],
    tipo_nota: str | None = None,
    direcao_nota: str | None = None,
    somente_divergentes: bool = False,
    valor_min: Decimal | None = None,
    valor_max: Decimal | None = None,
) -> list[Nota]:
    filtradas = list(notas)
    if tipo_nota is not None:
        filtradas = [nota for nota in filtradas if getattr(nota, "tipo_nota", None) == tipo_nota]
    if direcao_nota is not None:
        filtradas = [nota for nota in filtradas if getattr(nota, "direcao_nota", None) == direcao_nota]
    if somente_divergentes:
        filtradas = [nota for nota in filtradas if getattr(nota, "divergencia_fila_final", False)]
    if valor_min is not None:
        filtradas = [nota for nota in filtradas if Decimal(str(nota.valor_servico or 0)) >= Decimal(str(valor_min))]
    if valor_max is not None:
        filtradas = [nota for nota in filtradas if Decimal(str(nota.valor_servico or 0)) <= Decimal(str(valor_max))]
    return filtradas


def resumo_notas_operacional(
    db: Session,
    empresa_id: int | None = None,
    processo_id: int | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    competencia_inicio: date | None = None,
    competencia_fim: date | None = None,
    tipo_nota: str | None = None,
    direcao_nota: str | None = None,
) -> dict:
    notas = listar_notas(
        db,
        empresa_id=empresa_id,
        processo_id=processo_id,
        data_inicio=data_inicio,
        data_fim=data_fim,
        competencia_inicio=competencia_inicio,
        competencia_fim=competencia_fim,
        tipo_nota=tipo_nota,
        direcao_nota=direcao_nota,
        limit=5000,
        offset=0,
    )
    total = len(notas)
    divergentes = sum(1 for nota in notas if getattr(nota, "divergencia_fila_final", False))
    corretas = sum(1 for nota in notas if getattr(nota, "status_fila_final", None) == "correta")
    pendentes = sum(1 for nota in notas if getattr(nota, "status_fila_final", None) == "pendente")
    canceladas = sum(1 for nota in notas if getattr(nota, "status_fila_final", None) == "cancelada")
    substituidas = sum(1 for nota in notas if getattr(nota, "status_fila_final", None) == "substituida")
    return {
        "total": total,
        "corretas": corretas,
        "divergentes": divergentes,
        "pendentes": pendentes,
        "canceladas": canceladas,
        "substituidas": substituidas,
    }


def listar_notas_por_tipo_operacional(
    db: Session,
    nota_tipo: str,
    empresa_id: int,
    certificado_id: int | None = None,
    processo_id: int | None = None,
    status_documento: str | None = None,
    status: str | None = None,
    numero: str | None = None,
    prestador_cnpj: str | None = None,
    tomador_cnpj: str | None = None,
    chave: str | None = None,
    busca: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    competencia_inicio: date | None = None,
    competencia_fim: date | None = None,
    somente_validas: bool = False,
    limit: int = 100,
    offset: int = 0,
    sort: str = "recentes",
) -> list[Nota]:
    if nota_tipo not in {"emitida", "recebida"}:
        raise NotaServiceError("Tipo de nota invalido.")
    empresa = _empresa_ou_erro(db, empresa_id)
    empresa_cnpj = _only_digits(empresa.cnpj)
    if not empresa_cnpj:
        raise NotaServiceError("Empresa sem CNPJ configurado.")

    effective_status = status_documento or status
    if somente_validas and not effective_status:
        effective_status = "autorizada"

    query_competencia_inicio = competencia_inicio
    query_competencia_fim = competencia_fim
    if nota_tipo == "recebida" and competencia_inicio is not None:
        query_competencia_inicio = _previous_month(competencia_inicio)
    if nota_tipo == "recebida" and competencia_fim is not None:
        dia_corte = max(0, int(settings.notas_recebidas_dia_corte_mes_anterior or 0))
        if dia_corte:
            next_month = _next_month(competencia_fim)
            query_competencia_fim = date(next_month.year, next_month.month, dia_corte)

    notas = notas_repo.list_notas(
        db,
        empresa_id=empresa_id,
        certificado_id=certificado_id,
        processo_id=processo_id,
        status_documento=effective_status,
        numero=numero,
        prestador_cnpj=_only_digits(prestador_cnpj) or None,
        tomador_cnpj=_only_digits(tomador_cnpj) or None,
        chave=chave,
        busca=busca,
        data_inicio=data_inicio,
        data_fim=data_fim,
        competencia_inicio=query_competencia_inicio,
        competencia_fim=query_competencia_fim,
        limit=5000,
        offset=0,
        sort=sort,
    )

    classificadas = [
        _anotar_classificacao(nota, empresa_cnpj, competencia_fim)
        for nota in notas
        if _classificar_nota(nota, empresa_cnpj) == nota_tipo
    ]
    if competencia_inicio is not None:
        classificadas = [
            nota for nota in classificadas
            if getattr(nota, "competencia_operacional", None) is not None
            and getattr(nota, "competencia_operacional") >= _month_start(competencia_inicio)
        ]
    if competencia_fim is not None:
        classificadas = [
            nota for nota in classificadas
            if getattr(nota, "competencia_operacional", None) is not None
            and getattr(nota, "competencia_operacional") <= _month_start(competencia_fim)
        ]

    if sort == "emissao":
        classificadas.sort(
            key=lambda nota: (
                nota.data_emissao or date.min,
                nota.importado_em or nota.updated_at or nota.created_at,
                nota.id,
            ),
            reverse=True,
        )
    else:
        classificadas.sort(
            key=lambda nota: (
                nota.importado_em or nota.updated_at or nota.created_at,
                nota.id,
            ),
            reverse=True,
        )

    safe_limit = min(max(limit, 1), 500)
    safe_offset = max(offset, 0)
    return classificadas[safe_offset : safe_offset + safe_limit]


def obter_nota(db: Session, nota_id: int) -> Nota:
    nota = notas_repo.get_nota(db, nota_id)
    if nota is None:
        raise NotaServiceError("Nota nao encontrada.")
    consulta_simples_api = _consultas_simples_api_lote(db, [nota]).get(int(nota.id))
    return _anotar_detalhe_frontend(nota, consulta_simples_api)


def obter_nota_por_chave(db: Session, chave: str, empresa_id: int | None = None) -> Nota:
    nota = notas_repo.get_nota_by_chave_optional_empresa(db, chave, empresa_id=empresa_id)
    if nota is None:
        raise NotaServiceError("Nota nao encontrada.")
    consulta_simples_api = _consultas_simples_api_lote(db, [nota]).get(int(nota.id))
    return _anotar_detalhe_frontend(nota, consulta_simples_api)


def atualizar_conferencia(db: Session, nota_id: int, payload) -> Nota:
    nota = obter_nota(db, nota_id)
    responsavel = payload.responsavel or nota.responsavel or payload.operator_name
    atualizado_por = payload.atualizado_por or payload.operator_name or payload.responsavel
    data = {
        "conferencia_status": payload.conferencia_status,
        "conferencia_observacao": payload.conferencia_observacao,
        "conferencia_atualizado_em": payload.atualizado_em or datetime.now(timezone.utc),
        "conferencia_por": atualizado_por or nota.conferencia_por,
        "operator_name": payload.operator_name,
        "operator_id": payload.operator_id,
        "device_id": payload.device_id,
        "responsavel": responsavel,
    }
    prioridade = payload.prioridade or payload.prioridade_manual
    if prioridade:
        data["prioridade"] = prioridade
    if payload.prioridade_manual:
        data["prioridade_manual"] = payload.prioridade_manual
    # `calcular_status_fila` prioriza `status_fila_manual` sobre o recalculo
    # automatico (baseado em alertas_fiscais/status_*). Sem isto, marcar uma
    # nota como conferida ("ok") nao tirava ela do status "divergente" na
    # fila, mesmo com a conferencia humana dizendo que estava correta.
    status_fila_manual_explicito = getattr(payload, "status_fila_manual", None)
    status_fila_da_conferencia = {"ok": "correta", "corrigir": "divergente"}.get(payload.conferencia_status)
    if status_fila_manual_explicito:
        data["status_fila_manual"] = status_fila_manual_explicito
    elif status_fila_da_conferencia:
        data["status_fila_manual"] = status_fila_da_conferencia
    elif payload.conferencia_status == "pendente":
        # Reabre a nota: volta a deixar o status da fila ser recalculado
        # automaticamente em vez de manter uma decisao manual anterior.
        data["status_fila_manual"] = None
    if payload.divergencia:
        data["divergencia"] = payload.divergencia
    if payload.valor_liquido_correto is not None:
        data["valor_liquido_correto"] = payload.valor_liquido_correto
        try:
            liquido = float(nota.valor_liquido) if nota.valor_liquido is not None else None
            correto = float(payload.valor_liquido_correto)
            data["status_valor_liquido"] = "ok" if liquido is not None and abs(liquido - correto) < 0.01 else "divergente"
        except Exception:
            data["status_valor_liquido"] = None
    # `alertas_fiscais` nunca vem do payload de conferencia — e sempre
    # recalculado pela analise fiscal automatica, nunca editado por usuario.
    notas_repo.update_nota(db, nota, data)
    # Os campos derivados (status_fila_final, divergencia_fila_final, sla, etc.)
    # foram calculados em `obter_nota` acima, ANTES desta atualizacao. Sem
    # reanotar aqui, a resposta do PATCH devolvia o status antigo (ex.:
    # "divergente") mesmo depois da conferencia humana marcar a nota como OK.
    return obter_nota(db, nota_id)


def listar_arquivos_nota(db: Session, nota_id: int) -> list[Arquivo]:
    obter_nota(db, nota_id)
    return _selecionar_arquivos_visiveis(arquivos_repo.list_arquivos_by_nota(db, nota_id))
