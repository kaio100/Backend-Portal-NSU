"""Varre notas autorizadas e consulta seus eventos no ADN.

Uso tipico apos um periodo em que o motor ficou sem consultar (o fluxo por NSU
entrega os eventos, mas so quando a empresa e consultada). Reaproveita o mesmo
servico da rota POST /notas/{id}/sincronizar-eventos.

    python -m backend.app.scripts.sincronizar_eventos_lote --empresa-id 3
    python -m backend.app.scripts.sincronizar_eventos_lote --todas --desde 2026-06-01
    python -m backend.app.scripts.sincronizar_eventos_lote --todas --dry-run

Sem --executar nada e consultado: o comando apenas conta as notas alvo.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import date

from backend.app.db.models import Empresa, Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.services import eventos_sync_service
from backend.app.services.storage_service import get_storage_service


def _notas_alvo(db, empresa_id: int | None, desde: date | None, limite: int | None):
    query = (
        db.query(Nota)
        .join(Empresa, Empresa.id == Nota.empresa_id)
        .filter(Empresa.ativo.is_(True))
        .filter(Nota.arquivada.is_(False))
        # Uma nota ja cancelada/substituida nao muda de novo; so as autorizadas
        # podem ter recebido evento desde a ultima consulta.
        .filter(Nota.status_documento == "autorizada")
    )
    if empresa_id is not None:
        query = query.filter(Nota.empresa_id == empresa_id)
    if desde is not None:
        query = query.filter(Nota.data_emissao >= desde)
    query = query.order_by(Nota.empresa_id.asc(), Nota.id.asc())
    if limite:
        query = query.limit(limite)
    return query.all()


def executar(
    empresa_id: int | None,
    desde: date | None,
    limite: int | None,
    pausa: float,
    executar: bool,
) -> dict:
    init_db()
    storage = get_storage_service()
    contadores: Counter = Counter()
    alteradas: list[dict] = []
    erros: list[dict] = []
    with SessionLocal() as db:
        notas = _notas_alvo(db, empresa_id, desde, limite)
        contadores["notas_alvo"] = len(notas)
        if not executar:
            return {"dry_run": True, **contadores}
        for nota in notas:
            try:
                resultado = eventos_sync_service.sincronizar_eventos_nota(db, storage, nota)
                contadores["consultadas"] += 1
                contadores["eventos_aplicados"] += int(resultado.get("eventos_aplicados") or 0)
                if resultado.get("status_atual") != resultado.get("status_anterior"):
                    contadores["status_alterado"] += 1
                    alteradas.append(
                        {
                            "nota_id": nota.id,
                            "empresa_id": nota.empresa_id,
                            "de": resultado.get("status_anterior"),
                            "para": resultado.get("status_atual"),
                        }
                    )
            except Exception as exc:
                db.rollback()
                contadores["erros"] += 1
                if len(erros) < 50:
                    erros.append({"nota_id": nota.id, "empresa_id": nota.empresa_id, "erro": str(exc)[:200]})
            if pausa > 0:
                time.sleep(pausa)
    return {"dry_run": False, **contadores, "alteradas": alteradas, "erros_detalhes": erros}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--empresa-id", type=int)
    grupo.add_argument("--todas", action="store_true")
    parser.add_argument("--desde", type=date.fromisoformat, default=None, help="Somente notas emitidas a partir desta data")
    parser.add_argument("--limite", type=int, default=None, help="Maximo de notas a consultar")
    parser.add_argument("--pausa", type=float, default=0.3, help="Segundos entre consultas ao ADN")
    parser.add_argument("--executar", action="store_true", help="Sem esta opcao apenas conta as notas alvo")
    args = parser.parse_args()
    relatorio = executar(
        empresa_id=args.empresa_id,
        desde=args.desde,
        limite=args.limite,
        pausa=args.pausa,
        executar=args.executar,
    )
    print(json.dumps(relatorio, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
