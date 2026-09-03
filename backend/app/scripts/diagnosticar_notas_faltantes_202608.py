from datetime import date
from decimal import Decimal

from backend.app.db.models import Empresa, Nota
from backend.app.db.session import SessionLocal


TARGETS = [
    ("202615", "62069724000149", "TERESINA", "18000.00", "2026-07-20"),
    ("7", "62949869000134", "BELEM", "4060.00", "2026-07-09"),
    ("373", "26377160000148", "BELEM", "750.00", "2026-07-09"),
    ("48", "32292684000139", "TERESINA", "3000.00", "2026-07-23"),
    ("49", "32292684000139", "TERESINA", "3500.00", "2026-07-23"),
    ("226367", "12130171000114", "CANOPUS", "399.90", "2026-08-03"),
    ("19624", "03878483000110", "FORTALEZA", "1400.00", "2026-08-05"),
    ("19626", "03878483000110", "FORTALEZA", "1400.00", "2026-08-05"),
    ("19625", "03878483000110", "FORTALEZA", "1400.00", "2026-08-05"),
    ("53408191", "03506307000157", "CANOPUS", "61941.00", "2026-07-30"),
    ("476", "11162624000121", "CANOPUS", "110816.00", "2026-08-10"),
    ("719", "18158901000171", "TERESINA", "3000.00", "2026-08-05"),
    ("94", "54124601000135", "TERESINA", "20209.00", "2026-08-06"),
    ("6", "57738024000160", "TERESINA", "500.00", "2026-08-10"),
    ("180", "57536986000105", "BELEM", "11909.20", "2026-08-11"),
    ("6", "64706826000153", "BELEM", "7199.06", "2026-08-10"),
    ("662", "08624044000102", "BELEM", "13526.20", "2026-08-10"),
    ("41", "30720207000100", "BELEM", "12969.20", "2026-08-11"),
    ("1259", "52270198000127", "SOL II", "19546.70", "2026-08-05"),
    ("1254", "52270198000127", "SOL I", "30883.99", "2026-08-04"),
    ("21304", "27360683000106", "FORTALEZA", "960.00", "2026-08-03"),
    ("30005", "37459079000123", "CANOPUS", "427.90", "2026-07-24"),
    ("251", "49976294000180", "SOL I", "5066.00", "2026-08-10"),
    ("203", "59664505000101", "SOL I", "4676.00", "2026-08-10"),
    ("51", "64864371000150", "SOL II", "5220.00", "2026-08-10"),
    ("2116", "12152373000167", "SOL II", "10640.00", "2026-08-07"),
    ("222", "62540680000193", "BOSQUE II", "5026.00", "2026-08-07"),
    ("223", "62540680000193", "BOSQUE II", "5026.00", "2026-08-07"),
    ("224", "62540680000193", "BOSQUE II", "5026.00", "2026-08-07"),
    ("225", "62540680000193", "SOL I", "5146.00", "2026-08-10"),
    ("226", "62540680000193", "FORTALEZA", "11112.00", "2026-08-10"),
]


def norm_number(value):
    text = str(value or "").strip()
    return text.lstrip("0") or "0"


with SessionLocal() as db:
    cnpjs = sorted({item[1] for item in TARGETS})
    records = (
        db.query(Nota, Empresa)
        .join(Empresa, Empresa.id == Nota.empresa_id)
        .filter(Nota.prestador_cnpj.in_(cnpjs))
        .filter(Nota.data_emissao >= date(2026, 7, 1), Nota.data_emissao <= date(2026, 8, 17))
        .all()
    )
    by_cnpj = {}
    for nota, empresa in records:
        by_cnpj.setdefault(nota.prestador_cnpj, []).append((nota, empresa))

    found = 0
    missing = 0
    print("RESULTADOS")
    for number, cnpj, label, amount_text, issue_text in TARGETS:
        amount = Decimal(amount_text)
        issue = date.fromisoformat(issue_text)
        candidates = by_cnpj.get(cnpj, [])
        exact = [
            (n, e) for n, e in candidates
            if norm_number(n.numero_nfse) == norm_number(number)
            and n.data_emissao == issue
            and abs(Decimal(str(n.valor_servico or 0)) - amount) <= Decimal("0.01")
        ]
        same_number = [(n, e) for n, e in candidates if norm_number(n.numero_nfse) == norm_number(number)]
        same_date_amount = [
            (n, e) for n, e in candidates
            if n.data_emissao == issue and abs(Decimal(str(n.valor_servico or 0)) - amount) <= Decimal("0.01")
        ]
        selected = exact or same_number or same_date_amount
        status = "EXATA" if exact else "DIVERGENTE" if selected else "AUSENTE"
        found += status != "AUSENTE"
        missing += status == "AUSENTE"
        print({
            "solicitada": number,
            "cnpj": cnpj,
            "destino": label,
            "emissao": issue_text,
            "valor": amount_text,
            "status": status,
            "candidatos_prestador_periodo": len(candidates),
            "encontradas": [
                {
                    "id": n.id,
                    "numero": n.numero_nfse,
                    "emissao": str(n.data_emissao),
                    "valor": str(n.valor_servico),
                    "empresa_id": e.id,
                    "empresa": e.nome,
                    "empresa_cnpj": e.cnpj,
                    "status_documento": n.status_documento,
                    "primeiro_nsu": n.primeiro_nsu,
                    "ultimo_nsu": n.ultimo_nsu,
                    "chave": n.chave,
                    "xml": n.xml_storage_key,
                }
                for n, e in selected[:5]
            ],
        })
    print({"resumo": {"total": len(TARGETS), "localizadas_exata_ou_divergente": found, "ausentes": missing}})
