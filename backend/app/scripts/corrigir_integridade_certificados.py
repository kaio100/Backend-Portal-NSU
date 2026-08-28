from __future__ import annotations

import argparse
import json

from backend.app.db.models import Empresa, NsuControle
from backend.app.db.session import SessionLocal


CORRECOES_CNPJ = {
    34: ("15515230470001", "51523047000170"),
    37: ("40052856500000", "52856500000123"),
    38: ("13215000514500", "50005145000153"),
}

CORRECOES_NSU = {
    16: (2500, 50),
    48: (5000, 0),
}


def executar(confirmar: bool = False) -> dict:
    relatorio = {"modo": "execucao" if confirmar else "dry_run", "cnpjs": [], "nsus": []}
    with SessionLocal() as db:
        for empresa_id, (esperado, correto) in CORRECOES_CNPJ.items():
            empresa = db.get(Empresa, empresa_id)
            if empresa is None:
                raise RuntimeError(f"Empresa {empresa_id} nao encontrada.")
            if empresa.cnpj != esperado:
                raise RuntimeError(
                    f"Empresa {empresa_id} mudou durante a auditoria: esperado={esperado}, atual={empresa.cnpj}."
                )
            if db.query(Empresa.id).filter(Empresa.cnpj == correto, Empresa.id != empresa_id).first():
                raise RuntimeError(f"CNPJ correto {correto} ja pertence a outra empresa.")
            relatorio["cnpjs"].append(
                {"empresa_id": empresa_id, "antes": empresa.cnpj, "depois": correto}
            )
            empresa.cnpj = correto
            db.add(empresa)
            for controle in db.query(NsuControle).filter(NsuControle.empresa_id == empresa_id).all():
                controle.cnpj = correto
                db.add(controle)

        for certificado_id, (esperado, correto) in CORRECOES_NSU.items():
            controle = db.query(NsuControle).filter(NsuControle.certificado_id == certificado_id).one()
            atual = int(controle.ultimo_nsu or 0)
            if atual != esperado:
                raise RuntimeError(
                    f"NSU do certificado {certificado_id} mudou durante a auditoria: esperado={esperado}, atual={atual}."
                )
            relatorio["nsus"].append(
                {
                    "certificado_id": certificado_id,
                    "empresa_id": controle.empresa_id,
                    "antes": atual,
                    "depois": correto,
                }
            )
            controle.ultimo_nsu = correto
            controle.origem = "correcao_integridade_2026_08_06"
            db.add(controle)

        if confirmar:
            db.commit()
        else:
            db.rollback()
    return relatorio


def main() -> None:
    parser = argparse.ArgumentParser(description="Corrige inconsistencias confirmadas na auditoria de certificados")
    parser.add_argument("--execute", action="store_true", help="Confirma as alteracoes; sem esta flag executa dry-run")
    args = parser.parse_args()
    print(json.dumps(executar(confirmar=args.execute), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
