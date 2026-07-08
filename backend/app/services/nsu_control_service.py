from __future__ import annotations

import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.db.models import Empresa, Nota, NsuControle


def only_digits(value: str | None) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def maior_nsu_importado(db: Session, empresa_id: int) -> int:
    value = (
        db.query(func.max(Nota.ultimo_nsu))
        .filter(Nota.empresa_id == empresa_id)
        .filter(Nota.ultimo_nsu.isnot(None))
        .scalar()
    )
    return int(value or 0)


def obter_ultimo_nsu(
    db: Session,
    empresa_id: int,
    certificado_id: int | None = None,
) -> int:
    row = (
        db.query(NsuControle)
        .filter(NsuControle.empresa_id == empresa_id)
        .filter(NsuControle.certificado_id == certificado_id)
        .first()
    )
    central = int(row.ultimo_nsu or 0) if row else 0
    return max(central, maior_nsu_importado(db, empresa_id))


def atualizar_ultimo_nsu(
    db: Session,
    empresa_id: int,
    certificado_id: int | None,
    cnpj: str,
    ultimo_nsu: int | None,
    origem: str,
) -> NsuControle | None:
    if ultimo_nsu is None:
        return None
    nsu = int(ultimo_nsu or 0)
    if nsu < 0:
        nsu = 0
    cnpj_digits = only_digits(cnpj)
    if not cnpj_digits:
        empresa = db.get(Empresa, empresa_id)
        cnpj_digits = only_digits(empresa.cnpj if empresa else "")
    if not cnpj_digits:
        return None

    row = (
        db.query(NsuControle)
        .filter(NsuControle.empresa_id == empresa_id)
        .filter(NsuControle.certificado_id == certificado_id)
        .first()
    )
    if row is None:
        row = NsuControle(
            empresa_id=empresa_id,
            certificado_id=certificado_id,
            cnpj=cnpj_digits,
            ultimo_nsu=nsu,
            origem=origem,
        )
        db.add(row)
        db.flush()
        db.refresh(row)
        return row

    if nsu >= int(row.ultimo_nsu or 0):
        row.ultimo_nsu = nsu
        row.origem = origem
        row.cnpj = cnpj_digits
        db.add(row)
        db.flush()
        db.refresh(row)
    return row


def sincronizar_com_notas(
    db: Session,
    empresa_id: int,
    certificado_id: int | None,
    cnpj: str,
    origem: str = "notas",
) -> int:
    nsu = maior_nsu_importado(db, empresa_id)
    atualizar_ultimo_nsu(db, empresa_id, certificado_id, cnpj, nsu, origem=origem)
    return nsu
