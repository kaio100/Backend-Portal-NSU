from sqlalchemy import case, func, or_

from backend.app.db.models import Empresa, Nota
from backend.app.db.session import SessionLocal


with SessionLocal() as db:
    q = db.query(Nota, Empresa).join(Empresa, Empresa.id == Nota.empresa_id).filter(
        func.lower(func.coalesce(Nota.incidencia_iss, "")).like("%imperatriz%")
    )
    print("TOTAL_INCIDENCIA", q.count())
    print("PERIODO", q.with_entities(func.min(Nota.data_emissao), func.max(Nota.data_emissao)).one())
    print("POR_GRUPO_EMPRESA")
    for row in q.with_entities(Empresa.grupo, Empresa.id, Empresa.nome, Empresa.cnpj, func.count(Nota.id)).group_by(
        Empresa.grupo, Empresa.id, Empresa.nome, Empresa.cnpj
    ).order_by(func.count(Nota.id).desc()).all():
        print(row)
    print("POR_DIRECAO")
    direcao = case((Nota.prestador_cnpj == Empresa.cnpj, "prestada"), else_="tomada")
    for row in q.with_entities(
        direcao, func.count(Nota.id)
    ).group_by(direcao).all():
        print(row)
    print("VARIANTES")
    for row in q.with_entities(Nota.incidencia_iss, func.count(Nota.id)).group_by(Nota.incidencia_iss).order_by(func.count(Nota.id).desc()).all():
        print(row)
    print("AMOSTRAS")
    for nota, empresa in q.order_by(Nota.data_emissao.desc().nullslast()).limit(10).all():
        print({
            "id": nota.id,
            "numero": nota.numero_nfse,
            "emissao": str(nota.data_emissao),
            "empresa": empresa.nome,
            "grupo": empresa.grupo,
            "incidencia": nota.incidencia_iss,
            "municipio": nota.municipio,
            "prestador": nota.prestador_nome,
            "tomador": nota.tomador_nome,
        })
    broad = db.query(func.count(Nota.id)).filter(or_(
        func.lower(func.coalesce(Nota.incidencia_iss, "")).like("%imperatriz%"),
        func.lower(func.coalesce(Nota.municipio, "")).like("%imperatriz%"),
        func.lower(func.coalesce(Nota.prestador_nome, "")).like("%imperatriz%"),
        func.lower(func.coalesce(Nota.tomador_nome, "")).like("%imperatriz%"),
    )).scalar()
    print("TOTAL_BUSCA_AMPLA", broad)
