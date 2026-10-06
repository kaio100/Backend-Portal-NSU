"""Recifra as senhas de certificado com a chave nova de SECRETS_KEY.

Passo a passo para trocar a chave sem perder as senhas gravadas:

1. Gere uma chave nova:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
2. Coloque-a na FRENTE da antiga:  SECRETS_KEY=<nova>,<antiga>  e publique.
3. Rode este script (simula) e depois com --aplicar.
4. Com "falhas": 0, remova a chave antiga:  SECRETS_KEY=<nova>.

Sem --aplicar apenas confere se todos os segredos abrem com as chaves atuais.
"""

from __future__ import annotations

import argparse
import json

from backend.app.db.models import Secret
from backend.app.db.session import SessionLocal, init_db
from backend.app.services import secrets_service


def executar(aplicar: bool = False) -> dict:
    init_db()
    resumo = {"modo": "aplicacao" if aplicar else "simulacao", "segredos": 0, "recifrados": 0, "falhas": 0, "refs_com_falha": []}
    with SessionLocal() as db:
        for segredo in db.query(Secret).order_by(Secret.id.asc()).all():
            resumo["segredos"] += 1
            try:
                novo = secrets_service.recifrar(segredo.encrypted_value)
            except secrets_service.SecretsServiceError:
                resumo["falhas"] += 1
                resumo["refs_com_falha"].append(segredo.ref)
                continue
            if aplicar:
                segredo.encrypted_value = novo
            resumo["recifrados"] += 1
        if aplicar:
            db.commit()
    return resumo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--aplicar", action="store_true", help="Grava os segredos recifrados; sem esta opcao apenas confere.")
    args = parser.parse_args(argv)
    resumo = executar(aplicar=args.aplicar)
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    return 1 if resumo["falhas"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
