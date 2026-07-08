from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.db.models import Nota, Processo


def get_nota(db: Session, nota_id: int) -> Nota | None:
    return db.get(Nota, nota_id)


def get_nota_by_chave(db: Session, empresa_id: int, chave: str) -> Nota | None:
    return (
        db.query(Nota)
        .filter(Nota.empresa_id == empresa_id)
        .filter(Nota.chave == chave)
        .first()
    )


def get_nota_by_chave_optional_empresa(
    db: Session,
    chave: str,
    empresa_id: int | None = None,
) -> Nota | None:
    query = db.query(Nota).filter(Nota.chave == chave)
    if empresa_id is not None:
        query = query.filter(Nota.empresa_id == empresa_id)
    return query.order_by(Nota.id.desc()).first()


def list_notas(
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
    limit: int = 100,
    offset: int = 0,
    sort: str = "recentes",
) -> list[Nota]:
    query = db.query(Nota)
    if empresa_id is not None:
        query = query.filter(Nota.empresa_id == empresa_id)
    if certificado_id is not None:
        query = query.join(Processo, Processo.id == Nota.processo_id).filter(Processo.certificado_id == certificado_id)
    if processo_id is not None:
        query = query.filter(Nota.processo_id == processo_id)
    effective_status = status_documento or status
    if effective_status:
        query = query.filter(Nota.status_documento == effective_status)
    if numero:
        query = query.filter(Nota.numero_nfse == numero)
    if prestador_cnpj:
        query = query.filter(Nota.prestador_cnpj == prestador_cnpj)
    if tomador_cnpj:
        query = query.filter(Nota.tomador_cnpj == tomador_cnpj)
    if chave:
        query = query.filter(Nota.chave == chave)
    if busca:
        term = f"%{busca.strip()}%"
        query = query.filter(
            or_(
                Nota.chave.ilike(term),
                Nota.numero_nfse.ilike(term),
                Nota.prestador_nome.ilike(term),
                Nota.prestador_cnpj.ilike(term),
                Nota.tomador_nome.ilike(term),
                Nota.tomador_cnpj.ilike(term),
            )
        )
    if data_inicio is not None:
        query = query.filter(Nota.data_emissao >= data_inicio)
    if data_fim is not None:
        query = query.filter(Nota.data_emissao <= data_fim)
    if competencia_inicio is not None:
        query = query.filter(Nota.competencia >= competencia_inicio)
    if competencia_fim is not None:
        query = query.filter(Nota.competencia <= competencia_fim)
    if conferencia_status:
        query = query.filter(Nota.conferencia_status == conferencia_status)
    if prioridade:
        query = query.filter(Nota.prioridade == prioridade)
    if responsavel:
        query = query.filter(Nota.responsavel.ilike(f"%{responsavel.strip()}%"))
    if status_nota_pdf:
        query = query.filter(Nota.status_nota_pdf == status_nota_pdf)
    if simples_nacional_xml:
        query = query.filter(Nota.simples_nacional_xml == simples_nacional_xml)
    if consulta_simples_api:
        query = query.filter(Nota.consulta_simples_api == consulta_simples_api)
    if status_simples_nacional:
        query = query.filter(Nota.status_simples_nacional == status_simples_nacional)
    if incidencia_iss:
        query = query.filter(Nota.incidencia_iss == incidencia_iss)
    if divergencia:
        query = query.filter(Nota.divergencia == divergencia)
    if sla_status:
        query = query.filter(Nota.sla_status == sla_status)

    safe_limit = min(max(limit, 1), 5000)
    safe_offset = max(offset, 0)
    if sort == "emissao":
        query = query.order_by(Nota.data_emissao.desc().nullslast(), Nota.importado_em.desc().nullslast(), Nota.updated_at.desc().nullslast(), Nota.id.desc())
    else:
        query = query.order_by(Nota.importado_em.desc().nullslast(), Nota.updated_at.desc().nullslast(), Nota.created_at.desc().nullslast(), Nota.id.desc())

    return list(query.offset(safe_offset).limit(safe_limit).all())


def list_notas_by_ids(db: Session, nota_ids: list[int]) -> list[Nota]:
    if not nota_ids:
        return []
    order = {nota_id: index for index, nota_id in enumerate(nota_ids)}
    notas = list(db.query(Nota).filter(Nota.id.in_(nota_ids)).all())
    return sorted(notas, key=lambda nota: order.get(int(nota.id), len(order)))


def create_nota(db: Session, data: dict) -> Nota:
    now = datetime.now(timezone.utc)
    data.setdefault("importado_em", now)
    data.setdefault("updated_at", now)
    nota = Nota(**data)
    db.add(nota)
    db.flush()
    db.refresh(nota)
    return nota


def update_nota(db: Session, nota: Nota, data: dict) -> Nota:
    now = datetime.now(timezone.utc)
    data.setdefault("importado_em", now)
    data.setdefault("updated_at", now)
    for key, value in data.items():
        setattr(nota, key, value)
    db.add(nota)
    db.flush()
    db.refresh(nota)
    return nota


def upsert_nota_by_chave(db: Session, empresa_id: int, chave: str, data: dict) -> tuple[Nota, bool]:
    nota = get_nota_by_chave(db, empresa_id, chave)
    if nota is None:
        return create_nota(db, data), True
    return update_nota(db, nota, data), False
