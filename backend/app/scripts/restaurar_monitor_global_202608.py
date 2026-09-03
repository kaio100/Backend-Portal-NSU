from __future__ import annotations

import argparse

from backend.app.db.models import Certificado, Empresa, MonitoramentoConfig, NsuControle
from backend.app.db.session import SessionLocal
from backend.app.schemas.consultas import ConsultaIniciarRequest


GRUPO = "planning_hub"
CERTIFICADOS_RECONCILIAR = [10, 11, 15, 42, 64, 74, 75]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        config = db.query(MonitoramentoConfig).filter(MonitoramentoConfig.grupo == GRUPO).one()
        elegiveis = (
            db.query(Certificado.id)
            .join(Empresa, Empresa.id == Certificado.empresa_id)
            .filter(
                Empresa.grupo == GRUPO,
                Empresa.ativo.is_(True),
                Certificado.ativo.is_(True),
                Certificado.storage_key.isnot(None),
                Certificado.storage_key != "",
                Certificado.senha_secret_ref.isnot(None),
            )
            .all()
        )
        controles = (
            db.query(NsuControle)
            .filter(NsuControle.certificado_id.in_(CERTIFICADOS_RECONCILIAR))
            .all()
        )
        print(
            {
                "modo": "APLICAR" if args.apply else "SIMULAR",
                "filtros_anteriores": config.filtros_json,
                "certificados_elegiveis": len(elegiveis),
                "controles_reconciliacao": len(controles),
            }
        )
        if not args.apply:
            return

        atuais = ConsultaIniciarRequest(**(config.filtros_json or {}))
        globais = atuais.model_copy(
            update={
                "automatico": True,
                "empresa_ids": None,
                "certificado_ids": None,
                "nsu_inicio": None,
                "forcar": False,
            }
        )
        config.automatico_ativo = True
        config.filtros_json = globais.model_dump()
        config.proximo_ciclo_em = None
        db.add(config)
        for controle in controles:
            controle.ultima_reconciliacao_em = None
            db.add(controle)
        db.commit()
        print({"resultado": "monitor_global_restaurado", "reconciliacoes_reabertas": len(controles)})


if __name__ == "__main__":
    main()
