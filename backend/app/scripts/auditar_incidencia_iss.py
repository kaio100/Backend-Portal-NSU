from sqlalchemy import text

from backend.app.db.session import SessionLocal


with SessionLocal() as db:
    summary = db.execute(text("""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE incidencia_iss IS NULL OR btrim(incidencia_iss) = '') AS vazias,
               count(*) FILTER (WHERE btrim(coalesce(incidencia_iss, '')) ~ '^[0-9]+$') AS numericas,
               count(DISTINCT nullif(btrim(incidencia_iss), '')) AS distintos
        FROM notas
    """)).mappings().one()
    print(dict(summary))
    print("TOP")
    rows = db.execute(text("""
        SELECT coalesce(nullif(btrim(incidencia_iss), ''), '(vazio)') AS incidencia,
               count(*) AS quantidade
        FROM notas
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 30
    """)).mappings()
    for row in rows:
        print(dict(row))
