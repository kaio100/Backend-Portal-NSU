from __future__ import annotations

from decimal import Decimal

from backend.app.db.models import Nota
from backend.app.db.session import SessionLocal
from backend.app.services.retencoes_calculo_service import calcular_liquido_com_retencoes_salvas, money


def recalcular_notas_salvas(batch_size: int = 500) -> dict[str, int]:
    """Atualiza de forma idempotente o liquido esperado de todas as notas salvas."""
    analisadas = atualizadas = 0
    ultimo_id = 0

    with SessionLocal() as db:
        while True:
            notas = (
                db.query(Nota)
                .filter(Nota.id > ultimo_id)
                .order_by(Nota.id.asc())
                .limit(max(1, batch_size))
                .all()
            )
            if not notas:
                break

            for nota in notas:
                analisadas += 1
                ultimo_id = int(nota.id)
                calculado = calcular_liquido_com_retencoes_salvas(nota)
                informado = money(Decimal(str(nota.valor_liquido))) if nota.valor_liquido is not None else None
                status = "Correto" if informado is not None and abs(informado - calculado) <= Decimal("0.01") else "Divergente"
                atual = money(Decimal(str(nota.valor_liquido_correto))) if nota.valor_liquido_correto is not None else None
                calculado_atual = money(Decimal(str(nota.valor_liquido_calculado))) if nota.valor_liquido_calculado is not None else None
                if atual != calculado or calculado_atual != calculado or nota.status_valor_liquido != status:
                    nota.valor_liquido_correto = calculado
                    nota.valor_liquido_calculado = calculado
                    nota.status_valor_liquido = status
                    atualizadas += 1
            db.commit()

    return {"analisadas": analisadas, "atualizadas": atualizadas}
