from __future__ import annotations

import argparse
import json

from backend.app.db.models import Certificado, Empresa, Job
from backend.app.db.session import SessionLocal
from backend.app.schemas.consultas import ConsultaIniciarRequest
from backend.app.services import consultas_service


def executar(confirmar: bool = False, grupo: str = "planning_hub") -> dict:
    with SessionLocal() as db:
        ids = [
            int(certificado_id)
            for (certificado_id,) in (
                db.query(Certificado.id)
                .join(Empresa, Empresa.id == Certificado.empresa_id)
                .filter(
                    Certificado.ativo.is_(True),
                    Empresa.ativo.is_(True),
                    Empresa.grupo == grupo,
                    Certificado.storage_key.isnot(None),
                    Certificado.storage_key != "",
                    Certificado.storage_key != "pending",
                    Certificado.senha_secret_ref.isnot(None),
                )
                .order_by(Certificado.id)
                .all()
            )
        ]
        ativos_antes = int(
            db.query(Job.id)
            .join(Empresa, Empresa.id == Job.empresa_id)
            .filter(Empresa.grupo == grupo, Job.status.in_(("pendente", "rodando")))
            .count()
        )

    relatorio = {
        "modo": "execucao" if confirmar else "dry_run",
        "grupo": grupo,
        "certificados": ids,
        "certificados_total": len(ids),
        "jobs_ativos_antes": ativos_antes,
    }
    if not confirmar:
        return relatorio

    options = ConsultaIniciarRequest(
        automatico=True,
        certificado_ids=ids,
        nsu_inicio=0,
        limite=1000,
        pausa=0.6,
        gerar_pdf_espelho=True,
        baixar_pdf_oficial=True,
        forcar=True,
    )
    with SessionLocal() as db:
        resultado = consultas_service.iniciar_consultas_automaticas(db, options=options, grupo=grupo)
        relatorio["certificados_enfileirados"] = int(resultado["certificados_enfileirados"])
        relatorio["certificados_ignorados"] = int(resultado["certificados_ignorados"])
        relatorio["processos"] = [int(processo.id) for processo in resultado["processos_criados"]]
    return relatorio


def main() -> None:
    parser = argparse.ArgumentParser(description="Enfileira reprocessamento integral dos certificados ativos")
    parser.add_argument("--grupo", default="planning_hub")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    print(json.dumps(executar(confirmar=args.execute, grupo=args.grupo), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
