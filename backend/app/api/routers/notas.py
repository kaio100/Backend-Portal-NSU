from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.api.deps import get_storage
from backend.app.schemas.arquivos import ArquivoRead
from backend.app.schemas.notas import (
    NotaConferenciaUpdate,
    NotaDetail,
    NotaListItem,
    NotasDownloadFiltros,
    NotasDownloadLoteRequest,
    NotasTodasResponse,
)
from backend.app.services import notas_service
from backend.app.services import notas_download_service
from backend.app.services import portal_support_service
from backend.app.services.notas_download_service import NotasDownloadLoteError
from backend.app.services.notas_service import NotaServiceError
from backend.app.services.storage_service import StorageService


router = APIRouter(prefix="/notas", tags=["notas"])


def _handle_error(exc: NotaServiceError) -> None:
    message = str(exc)
    status_code = 404 if "nao encontrada" in message else 400
    raise HTTPException(status_code=status_code, detail=message)


def _zip_response(result: notas_download_service.DownloadLoteResult) -> Response:
    return Response(
        content=result.data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            "X-Notas-Count": str(result.notas_count),
            "X-Arquivos-Count": str(result.arquivos_count),
            "X-Arquivos-Ausentes": str(result.ausentes_count),
        },
    )


def _handle_download_error(exc: NotasDownloadLoteError) -> None:
    message = str(exc)
    status_code = 404 if "Nenhuma nota encontrada" in message else 400
    raise HTTPException(status_code=status_code, detail=message)


@router.get("", response_model=list[NotaListItem])
def list_notas(
    empresa_id: int | None = Query(default=None),
    certificado_id: int | None = Query(default=None),
    processo_id: int | None = Query(default=None),
    status_documento: str | None = Query(default=None),
    status: str | None = Query(default=None),
    numero: str | None = Query(default=None),
    prestador_cnpj: str | None = Query(default=None),
    cnpj_prestador: str | None = Query(default=None),
    tomador_cnpj: str | None = Query(default=None),
    cnpj_tomador: str | None = Query(default=None),
    chave: str | None = Query(default=None),
    busca: str | None = Query(default=None),
    q: str | None = Query(default=None),
    nota: str | None = Query(default=None),
    empresa: str | None = Query(default=None),
    prestador: str | None = Query(default=None),
    tomador: str | None = Query(default=None),
    data_inicial: date | None = Query(default=None),
    data_final: date | None = Query(default=None),
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    competencia_inicio: date | None = Query(default=None),
    competencia_fim: date | None = Query(default=None),
    conferencia_status: str | None = Query(default=None),
    conferencia: str | None = Query(default=None),
    prioridade: str | None = Query(default=None),
    responsavel: str | None = Query(default=None),
    status_nota_pdf: str | None = Query(default=None),
    simples_nacional_xml: str | None = Query(default=None),
    consulta_simples_api: str | None = Query(default=None),
    status_simples_nacional: str | None = Query(default=None),
    incidencia_iss: str | None = Query(default=None),
    divergencia: str | None = Query(default=None),
    sla_status: str | None = Query(default=None),
    sla: str | None = Query(default=None),
    tipo_nota: str | None = Query(default=None),
    direcao_nota: str | None = Query(default=None),
    sort: str = Query(default="recentes", pattern="^(recentes|emissao)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return notas_service.listar_notas(
            db,
            empresa_id=empresa_id,
            certificado_id=certificado_id,
            processo_id=processo_id,
            status_documento=status_documento or status,
            numero=numero,
            prestador_cnpj=prestador_cnpj or cnpj_prestador,
            tomador_cnpj=tomador_cnpj or cnpj_tomador,
            chave=chave,
            busca=busca or q or nota or empresa or prestador or tomador,
            data_inicio=data_inicio or data_inicial,
            data_fim=data_fim or data_final,
            competencia_inicio=competencia_inicio,
            competencia_fim=competencia_fim,
            conferencia_status=conferencia_status or conferencia,
            prioridade=prioridade,
            responsavel=responsavel,
            status_nota_pdf=status_nota_pdf,
            simples_nacional_xml=simples_nacional_xml,
            consulta_simples_api=consulta_simples_api,
            status_simples_nacional=status_simples_nacional,
            incidencia_iss=incidencia_iss,
            divergencia=divergencia,
            sla_status=sla_status or sla,
            tipo_nota=tipo_nota,
            direcao_nota=direcao_nota,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except NotaServiceError as exc:
        _handle_error(exc)


@router.get("/todas", response_model=NotasTodasResponse)
def list_todas_notas(
    empresa_id: int | None = Query(default=None),
    certificado_id: int | None = Query(default=None),
    processo_id: int | None = Query(default=None),
    status_documento: str | None = Query(default=None),
    status: str | None = Query(default=None),
    numero: str | None = Query(default=None),
    prestador_cnpj: str | None = Query(default=None),
    cnpj_prestador: str | None = Query(default=None),
    tomador_cnpj: str | None = Query(default=None),
    cnpj_tomador: str | None = Query(default=None),
    chave: str | None = Query(default=None),
    busca: str | None = Query(default=None),
    q: str | None = Query(default=None),
    nota: str | None = Query(default=None),
    empresa: str | None = Query(default=None),
    prestador: str | None = Query(default=None),
    tomador: str | None = Query(default=None),
    data_inicial: date | None = Query(default=None),
    data_final: date | None = Query(default=None),
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    competencia_inicio: date | None = Query(default=None),
    competencia_fim: date | None = Query(default=None),
    conferencia_status: str | None = Query(default=None),
    conferencia: str | None = Query(default=None),
    prioridade: str | None = Query(default=None),
    responsavel: str | None = Query(default=None),
    status_nota_pdf: str | None = Query(default=None),
    simples_nacional_xml: str | None = Query(default=None),
    consulta_simples_api: str | None = Query(default=None),
    status_simples_nacional: str | None = Query(default=None),
    incidencia_iss: str | None = Query(default=None),
    divergencia: str | None = Query(default=None),
    sla_status: str | None = Query(default=None),
    sla: str | None = Query(default=None),
    tipo_nota: str | None = Query(default=None),
    direcao_nota: str | None = Query(default=None),
    somente_divergentes: bool = Query(default=False),
    valor_min: Decimal | None = Query(default=None),
    valor_max: Decimal | None = Query(default=None),
    sort: str = Query(default="recentes", pattern="^(recentes|emissao)$"),
    db: Session = Depends(get_db),
):
    try:
        return notas_service.listar_todas_notas(
            db,
            empresa_id=empresa_id,
            certificado_id=certificado_id,
            processo_id=processo_id,
            status_documento=status_documento or status,
            numero=numero,
            prestador_cnpj=prestador_cnpj or cnpj_prestador,
            tomador_cnpj=tomador_cnpj or cnpj_tomador,
            chave=chave,
            busca=busca or q or nota or empresa or prestador or tomador,
            data_inicio=data_inicio or data_inicial,
            data_fim=data_fim or data_final,
            competencia_inicio=competencia_inicio,
            competencia_fim=competencia_fim,
            conferencia_status=conferencia_status or conferencia,
            prioridade=prioridade,
            responsavel=responsavel,
            status_nota_pdf=status_nota_pdf,
            simples_nacional_xml=simples_nacional_xml,
            consulta_simples_api=consulta_simples_api,
            status_simples_nacional=status_simples_nacional,
            incidencia_iss=incidencia_iss,
            divergencia=divergencia,
            sla_status=sla_status or sla,
            tipo_nota=tipo_nota,
            direcao_nota=direcao_nota,
            somente_divergentes=somente_divergentes,
            valor_min=valor_min,
            valor_max=valor_max,
            sort=sort,
        )
    except NotaServiceError as exc:
        _handle_error(exc)


def _list_notas_operacionais(
    nota_tipo: str,
    empresa_id: int,
    certificado_id: int | None,
    processo_id: int | None,
    status_documento: str | None,
    status: str | None,
    numero: str | None,
    prestador_cnpj: str | None,
    cnpj_prestador: str | None,
    tomador_cnpj: str | None,
    cnpj_tomador: str | None,
    chave: str | None,
    busca: str | None,
    data_inicial: date | None,
    data_final: date | None,
    data_inicio: date | None,
    data_fim: date | None,
    competencia_inicio: date | None,
    competencia_fim: date | None,
    somente_validas: bool,
    sort: str,
    limit: int,
    offset: int,
    db: Session,
):
    try:
        return notas_service.listar_notas_por_tipo_operacional(
            db,
            nota_tipo=nota_tipo,
            empresa_id=empresa_id,
            certificado_id=certificado_id,
            processo_id=processo_id,
            status_documento=status_documento or status,
            numero=numero,
            prestador_cnpj=prestador_cnpj or cnpj_prestador,
            tomador_cnpj=tomador_cnpj or cnpj_tomador,
            chave=chave,
            busca=busca,
            data_inicio=data_inicio or data_inicial,
            data_fim=data_fim or data_final,
            competencia_inicio=competencia_inicio,
            competencia_fim=competencia_fim,
            somente_validas=somente_validas,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except NotaServiceError as exc:
        _handle_error(exc)


@router.get("/emitidas", response_model=list[NotaListItem])
def list_notas_emitidas(
    empresa_id: int = Query(...),
    certificado_id: int | None = Query(default=None),
    processo_id: int | None = Query(default=None),
    status_documento: str | None = Query(default=None),
    status: str | None = Query(default=None),
    numero: str | None = Query(default=None),
    prestador_cnpj: str | None = Query(default=None),
    cnpj_prestador: str | None = Query(default=None),
    tomador_cnpj: str | None = Query(default=None),
    cnpj_tomador: str | None = Query(default=None),
    chave: str | None = Query(default=None),
    busca: str | None = Query(default=None),
    data_inicial: date | None = Query(default=None),
    data_final: date | None = Query(default=None),
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    competencia_inicio: date | None = Query(default=None),
    competencia_fim: date | None = Query(default=None),
    somente_validas: bool = Query(default=False),
    sort: str = Query(default="recentes", pattern="^(recentes|emissao)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return _list_notas_operacionais(
        "emitida",
        empresa_id,
        certificado_id,
        processo_id,
        status_documento,
        status,
        numero,
        prestador_cnpj,
        cnpj_prestador,
        tomador_cnpj,
        cnpj_tomador,
        chave,
        busca,
        data_inicial,
        data_final,
        data_inicio,
        data_fim,
        competencia_inicio,
        competencia_fim,
        somente_validas,
        sort,
        limit,
        offset,
        db,
    )


@router.get("/recebidas", response_model=list[NotaListItem])
def list_notas_recebidas(
    empresa_id: int = Query(...),
    certificado_id: int | None = Query(default=None),
    processo_id: int | None = Query(default=None),
    status_documento: str | None = Query(default=None),
    status: str | None = Query(default=None),
    numero: str | None = Query(default=None),
    prestador_cnpj: str | None = Query(default=None),
    cnpj_prestador: str | None = Query(default=None),
    tomador_cnpj: str | None = Query(default=None),
    cnpj_tomador: str | None = Query(default=None),
    chave: str | None = Query(default=None),
    busca: str | None = Query(default=None),
    data_inicial: date | None = Query(default=None),
    data_final: date | None = Query(default=None),
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    competencia_inicio: date | None = Query(default=None),
    competencia_fim: date | None = Query(default=None),
    somente_validas: bool = Query(default=False),
    sort: str = Query(default="recentes", pattern="^(recentes|emissao)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return _list_notas_operacionais(
        "recebida",
        empresa_id,
        certificado_id,
        processo_id,
        status_documento,
        status,
        numero,
        prestador_cnpj,
        cnpj_prestador,
        tomador_cnpj,
        cnpj_tomador,
        chave,
        busca,
        data_inicial,
        data_final,
        data_inicio,
        data_fim,
        competencia_inicio,
        competencia_fim,
        somente_validas,
        sort,
        limit,
        offset,
        db,
    )


@router.post("/download-lote")
def download_lote_notas(
    payload: NotasDownloadLoteRequest,
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    try:
        result = notas_download_service.gerar_zip_notas(db, storage, payload)
    except NotasDownloadLoteError as exc:
        _handle_download_error(exc)

    return _zip_response(result)


@router.get("/download-lote")
def download_lote_notas_get(
    nota_ids: list[int] | None = Query(default=None),
    empresa_id: int | None = Query(default=None),
    certificado_id: int | None = Query(default=None),
    processo_id: int | None = Query(default=None),
    status_documento: str | None = Query(default=None),
    status: str | None = Query(default=None),
    numero: str | None = Query(default=None),
    prestador_cnpj: str | None = Query(default=None),
    cnpj_prestador: str | None = Query(default=None),
    tomador_cnpj: str | None = Query(default=None),
    cnpj_tomador: str | None = Query(default=None),
    chave: str | None = Query(default=None),
    busca: str | None = Query(default=None),
    data_inicial: date | None = Query(default=None),
    data_final: date | None = Query(default=None),
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    competencia_inicio: date | None = Query(default=None),
    competencia_fim: date | None = Query(default=None),
    tipo_nota: str | None = Query(default=None),
    direcao_nota: str | None = Query(default=None),
    incluir_xml: bool = Query(default=True),
    incluir_pdf: bool = Query(default=True),
    preferir_pdf_original: bool = Query(default=True),
    sort: str = Query(default="recentes", pattern="^(recentes|emissao)$"),
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    payload = NotasDownloadLoteRequest(
        filtros=NotasDownloadFiltros(
            empresa_id=empresa_id,
            certificado_id=certificado_id,
            processo_id=processo_id,
            status_documento=status_documento or status,
            numero=numero,
            prestador_cnpj=prestador_cnpj or cnpj_prestador,
            tomador_cnpj=tomador_cnpj or cnpj_tomador,
            chave=chave,
            busca=busca,
            data_inicio=data_inicio or data_inicial,
            data_fim=data_fim or data_final,
            competencia_inicio=competencia_inicio,
            competencia_fim=competencia_fim,
            tipo_nota=tipo_nota,
            direcao_nota=direcao_nota,
            sort=sort,
        ),
        nota_ids=nota_ids,
        incluir_xml=incluir_xml,
        incluir_pdf=incluir_pdf,
        preferir_pdf_original=preferir_pdf_original,
    )
    try:
        result = notas_download_service.gerar_zip_notas(db, storage, payload)
    except NotasDownloadLoteError as exc:
        _handle_download_error(exc)
    return _zip_response(result)


@router.get("/resumo")
def get_notas_resumo(
    empresa_id: int | None = Query(default=None),
    processo_id: int | None = Query(default=None),
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    competencia_inicio: date | None = Query(default=None),
    competencia_fim: date | None = Query(default=None),
    tipo_nota: str | None = Query(default=None),
    direcao_nota: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return notas_service.resumo_notas_operacional(
            db,
            empresa_id=empresa_id,
            processo_id=processo_id,
            data_inicio=data_inicio,
            data_fim=data_fim,
            competencia_inicio=competencia_inicio,
            competencia_fim=competencia_fim,
            tipo_nota=tipo_nota,
            direcao_nota=direcao_nota,
        )
    except NotaServiceError as exc:
        _handle_error(exc)


@router.get("/chave/{chave}", response_model=NotaDetail)
def get_nota_por_chave(
    chave: str,
    empresa_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return notas_service.obter_nota_por_chave(db, chave, empresa_id=empresa_id)
    except NotaServiceError as exc:
        _handle_error(exc)


@router.get("/{nota_id}", response_model=NotaDetail)
def get_nota(nota_id: int, db: Session = Depends(get_db)):
    try:
        return notas_service.obter_nota(db, nota_id)
    except NotaServiceError as exc:
        _handle_error(exc)


@router.get("/{nota_id}/eventos")
def list_eventos_nota(nota_id: int, db: Session = Depends(get_db)):
    try:
        return portal_support_service.listar_eventos_nota(db, nota_id)
    except NotaServiceError as exc:
        _handle_error(exc)


@router.get("/{nota_id}/tributos-comparativo")
def get_tributos_comparativo(nota_id: int, db: Session = Depends(get_db)):
    try:
        return portal_support_service.comparar_tributos_nota(db, nota_id)
    except NotaServiceError as exc:
        _handle_error(exc)


@router.patch("/{nota_id}/conferencia", response_model=NotaDetail)
def patch_conferencia_nota(
    nota_id: int,
    payload: NotaConferenciaUpdate,
    x_usuario_nome: str | None = Header(default=None, alias="X-Usuario-Nome"),
    x_responsavel: str | None = Header(default=None, alias="X-Responsavel"),
    db: Session = Depends(get_db),
):
    try:
        if not payload.responsavel:
            payload.responsavel = (x_responsavel or x_usuario_nome or "").strip() or None
        nota = notas_service.atualizar_conferencia(db, nota_id, payload)
        db.commit()
        db.refresh(nota)
        return nota
    except NotaServiceError as exc:
        db.rollback()
        _handle_error(exc)


@router.get("/{nota_id}/arquivos")
def list_arquivos_nota(
    nota_id: int,
    detalhado: bool = Query(default=False),
    envelope: bool = Query(default=False),
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    try:
        if detalhado or envelope:
            return portal_support_service.listar_documentos_nota(db, nota_id, storage)
        return [
            ArquivoRead.model_validate(arquivo).model_dump(mode="json")
            for arquivo in notas_service.listar_arquivos_nota(db, nota_id)
        ]
    except NotaServiceError as exc:
        _handle_error(exc)
