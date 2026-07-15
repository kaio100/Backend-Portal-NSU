from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, get_storage
from backend.app.schemas.notas import NotaConferenciaUpdate
from backend.app.services import notas_service, portal_support_service
from backend.app.services.notas_service import NotaServiceError
from backend.app.services.storage_service import StorageService


router = APIRouter(prefix="/nfse", tags=["nfse-compat"])


def _handle_error(exc: NotaServiceError) -> None:
    message = str(exc)
    status_code = 404 if "nao encontrada" in message else 400
    raise HTTPException(status_code=status_code, detail=message)


def _as_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _nota_compat_dict(nota) -> dict:
    processo = getattr(nota, "processo", None)
    certificado = getattr(processo, "certificado", None) if processo is not None else None
    empresa = getattr(nota, "empresa", None)
    cert_alias = getattr(certificado, "nome", None) or getattr(empresa, "nome", None) or ""
    status_fila = getattr(nota, "status_fila_final", None) or getattr(nota, "status_fila", None)
    status_documento = getattr(nota, "status_documento", None)
    valor_servico = getattr(nota, "valor_servico", None)
    return {
        "id": nota.id,
        "empresa_id": nota.empresa_id,
        "processo_id": nota.processo_id,
        "chave": nota.chave,
        "numero": nota.numero_nfse,
        "numero_nfse": nota.numero_nfse,
        "numero_nota": nota.numero_nfse,
        "cert_alias": cert_alias,
        "certificado": cert_alias,
        "client_name": getattr(empresa, "nome", None),
        "empresa": getattr(empresa, "nome", None),
        "empresa_nome": getattr(empresa, "nome", None),
        "prestador": nota.prestador_nome,
        "prestador_nome": nota.prestador_nome,
        "cnpj_prestador": nota.prestador_cnpj,
        "prestador_cnpj": nota.prestador_cnpj,
        "tomador": nota.tomador_nome,
        "tomador_nome": nota.tomador_nome,
        "cnpj_tomador": nota.tomador_cnpj,
        "tomador_cnpj": nota.tomador_cnpj,
        "competencia": nota.competencia,
        "data_emissao": nota.data_emissao,
        "data_entrada": nota.importado_em or nota.created_at,
        "importado_em": nota.importado_em,
        "created_at": nota.created_at,
        "updated_at": nota.updated_at,
        "valor": valor_servico,
        "valor_total": valor_servico,
        "valor_servico": valor_servico,
        "valor_liquido": nota.valor_liquido,
        "status": status_fila or status_documento,
        "status_nota": status_documento,
        "status_documento": status_documento,
        "status_rotulo": nota.status_rotulo,
        "queue_status": status_fila,
        "status_fila": getattr(nota, "status_fila", None),
        "status_fila_final": getattr(nota, "status_fila_final", None),
        "divergencia": getattr(nota, "divergencia", None),
        "divergencia_fila_final": getattr(nota, "divergencia_fila_final", None),
        "divergencia_fila_label": getattr(nota, "divergencia_fila_label", None),
        "prioridade": getattr(nota, "prioridade", None) or getattr(nota, "prioridade_fila", None),
        "prioridade_fila": getattr(nota, "prioridade_fila", None),
        "responsavel": getattr(nota, "responsavel", None),
        "conferencia_status": getattr(nota, "conferencia_status", None),
        "simples_nacional": getattr(nota, "simples_xml", None) or getattr(nota, "simples_nacional_xml", None),
        "status_simples_nacional": getattr(nota, "status_simples_nacional", None),
        "incidencia_iss": getattr(nota, "incidencia_iss", None),
        "municipio": getattr(nota, "municipio", None),
        "codigo_servico": getattr(nota, "codigo_servico", None),
        "tipo_nota": getattr(nota, "tipo_nota", None),
        "direcao_nota": getattr(nota, "direcao_nota", None),
        "sla": getattr(nota, "sla", None) or getattr(nota, "sla_operacional", None),
    }


@router.get("")
def list_nfse_compat(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    cert_alias: str | None = Query(default=None),
    status: str | None = Query(default=None),
    municipio: str | None = Query(default=None),
    cnpj_cpf: str | None = Query(default=None),
    competencia: date | None = Query(default=None),
    codigo_servico: str | None = Query(default=None),
    busca: str | None = Query(default=None),
    somente_divergentes: bool = Query(default=False),
    empresa_id: int | None = Query(default=None),
    processo_id: int | None = Query(default=None),
    tipo_nota: str | None = Query(default=None),
    direcao_nota: str | None = Query(default=None),
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    valor_min: Decimal | None = Query(default=None),
    valor_max: Decimal | None = Query(default=None),
    db: Session = Depends(get_db),
):
    limit = _as_int(page_size, 50, 1, 500)
    offset = (_as_int(page, 1, 1, 100000) - 1) * limit
    search = busca or cert_alias or municipio or codigo_servico
    if cnpj_cpf:
        search = cnpj_cpf
    try:
        notas = notas_service.listar_notas(
            db,
            empresa_id=empresa_id,
            processo_id=processo_id,
            status_documento=status,
            busca=search,
            competencia_inicio=competencia,
            competencia_fim=competencia,
            data_inicio=data_inicio,
            data_fim=data_fim,
            tipo_nota=tipo_nota,
            direcao_nota=direcao_nota,
            limit=limit,
            offset=offset,
        )
        items = [_nota_compat_dict(nota) for nota in notas]
        if somente_divergentes:
            items = [item for item in items if item.get("divergencia_fila_final") or "diverg" in str(item.get("status") or "").lower()]
        if valor_min is not None:
            items = [item for item in items if Decimal(str(item.get("valor_total") or 0)) >= valor_min]
        if valor_max is not None:
            items = [item for item in items if Decimal(str(item.get("valor_total") or 0)) <= valor_max]
        total = offset + len(items) + (1 if len(notas) == limit else 0)
        return {"items": items, "total": total, "page": page, "page_size": limit}
    except NotaServiceError as exc:
        _handle_error(exc)


@router.get("/{nota_id}")
def get_nfse_compat(nota_id: int, db: Session = Depends(get_db)):
    try:
        return _nota_compat_dict(notas_service.obter_nota(db, nota_id))
    except NotaServiceError as exc:
        _handle_error(exc)


@router.put("/{nota_id}")
async def update_nfse_compat(nota_id: int, request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    campos_somente_sistema = {"observacao_interna", "alertas_fiscais"}
    campos_bloqueados = sorted(campo for campo in campos_somente_sistema if campo in payload)
    if campos_bloqueados:
        raise HTTPException(
            status_code=422,
            detail="observacao_interna e alertas_fiscais sao campos somente leitura, preenchidos apenas pelo sistema.",
        )
    status = str(payload.get("conferencia_status") or payload.get("status_fila_manual") or payload.get("status") or "pendente")
    try:
        nota_atual = notas_service.obter_nota(db, nota_id)
        conferencia_observacao = payload.get("observacao") if "observacao" in payload else nota_atual.conferencia_observacao
        nota = notas_service.atualizar_conferencia(
            db,
            nota_id,
            NotaConferenciaUpdate(
                conferencia_status=status if status in {"pendente", "ok", "corrigir", "observacao"} else "pendente",
                conferencia_observacao=conferencia_observacao,
                responsavel=payload.get("responsavel"),
                prioridade_manual=payload.get("prioridade_manual") or payload.get("prioridade"),
                status_fila_manual=payload.get("status_fila_manual") or payload.get("status"),
                divergencia=payload.get("divergencia"),
            ),
        )
        db.commit()
        db.refresh(nota)
        return _nota_compat_dict(nota)
    except NotaServiceError as exc:
        db.rollback()
        _handle_error(exc)


@router.get("/{nota_id}/documentos")
def get_nfse_documentos_compat(
    nota_id: int,
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    try:
        return portal_support_service.listar_documentos_nota(db, nota_id, storage)
    except NotaServiceError as exc:
        _handle_error(exc)
