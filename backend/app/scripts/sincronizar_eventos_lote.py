"""Varre notas autorizadas e consulta seus eventos no ADN.

Uso tipico apos um periodo em que o motor ficou sem consultar (o fluxo por NSU
entrega os eventos, mas so quando a empresa e consultada). Reaproveita o mesmo
servico da rota POST /notas/{id}/sincronizar-eventos.

    python -m backend.app.scripts.sincronizar_eventos_lote --empresa-id 3 --executar
    python -m backend.app.scripts.sincronizar_eventos_lote --todas --desde 2026-08-01 --executar
    python -m backend.app.scripts.sincronizar_eventos_lote --todas --desde 2026-08-01 --workers 4 --executar

Sem --executar nada e consultado: o comando apenas conta as notas alvo.

Desempenho: o certificado (PFX + senha) e a conexao mTLS sao preparados uma
vez por empresa (`SessaoCertificado`), e as empresas rodam em paralelo
(`--workers`), cada uma em sequencia para nao disparar rajada em um mesmo
CNPJ no ADN. Sem isso a varredura custava ~7 s por nota.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from backend.app.db.models import Empresa, Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.services import eventos_sync_service
from backend.app.services.storage_service import get_storage_service


def _ids_alvo(db, empresa_id: int | None, desde: date | None, ate: date | None, limite: int | None) -> list[tuple[int, int]]:
    query = (
        db.query(Nota.id, Nota.empresa_id)
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
    if ate is not None:
        query = query.filter(Nota.data_emissao < ate)
    query = query.order_by(Nota.empresa_id.asc(), Nota.id.asc())
    if limite:
        query = query.limit(limite)
    return [(int(nid), int(eid)) for nid, eid in query.all()]


def _processar_empresa(empresa_id: int, nota_ids: list[int], pausa: float, progresso, lock: threading.Lock) -> dict:
    """Roda em uma thread: uma sessao de banco, um certificado, notas em sequencia."""
    storage = get_storage_service()
    contadores: Counter = Counter()
    alteradas: list[dict] = []
    erros: list[dict] = []
    with SessionLocal() as db:
        empresa = db.get(Empresa, empresa_id)
        try:
            sessao = eventos_sync_service.SessaoCertificado(db, storage, empresa)
        except Exception as exc:
            return {"empresa_id": empresa_id, "erro_certificado": str(exc)[:200], "notas": len(nota_ids)}
        try:
            for nota_id in nota_ids:
                nota = db.get(Nota, nota_id)
                if nota is None or nota.status_documento != "autorizada":
                    contadores["puladas"] += 1
                    continue
                try:
                    resultado = eventos_sync_service.sincronizar_eventos_nota(db, storage, nota, sessao=sessao)
                    contadores["consultadas"] += 1
                    contadores["eventos_aplicados"] += int(resultado.get("eventos_aplicados") or 0)
                    if resultado.get("status_atual") != resultado.get("status_anterior"):
                        contadores["status_alterado"] += 1
                        alteradas.append({"nota_id": nota_id, "empresa_id": empresa_id, "de": resultado.get("status_anterior"), "para": resultado.get("status_atual")})
                except Exception as exc:
                    db.rollback()
                    contadores["erros"] += 1
                    if len(erros) < 20:
                        erros.append({"nota_id": nota_id, "empresa_id": empresa_id, "erro": str(exc)[:200]})
                if pausa > 0:
                    time.sleep(pausa)
                with lock:
                    progresso["feitas"] += 1
                    progresso["alteradas"] += 1 if (alteradas and alteradas[-1]["nota_id"] == nota_id) else 0
                    if progresso["feitas"] % 200 == 0:
                        print(f"Progresso: {progresso['feitas']}/{progresso['total']} consultadas, {progresso['alteradas']} alteradas", flush=True)
        finally:
            sessao.fechar()
    return {"empresa_id": empresa_id, **contadores, "alteradas": alteradas, "erros_detalhes": erros}


def executar(
    empresa_id: int | None,
    desde: date | None,
    limite: int | None,
    pausa: float,
    executar: bool,
    ate: date | None = None,
    workers: int = 1,
) -> dict:
    init_db()
    with SessionLocal() as db:
        alvo = _ids_alvo(db, empresa_id, desde, ate, limite)
    por_empresa: dict[int, list[int]] = defaultdict(list)
    for nota_id, eid in alvo:
        por_empresa[eid].append(nota_id)
    if not executar:
        return {"dry_run": True, "notas_alvo": len(alvo), "empresas": len(por_empresa)}

    progresso = {"feitas": 0, "alteradas": 0, "total": len(alvo)}
    lock = threading.Lock()
    print(f"Notas alvo: {len(alvo)} em {len(por_empresa)} empresas | workers={workers}", flush=True)
    resultados: list[dict] = []
    # Empresas maiores primeiro: evita que uma fila longa fique por ultimo sozinha.
    ordem = sorted(por_empresa.items(), key=lambda item: -len(item[1]))
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futuros = [pool.submit(_processar_empresa, eid, ids, pausa, progresso, lock) for eid, ids in ordem]
        for futuro in as_completed(futuros):
            resultados.append(futuro.result())

    totais: Counter = Counter()
    alteradas: list[dict] = []
    erros: list[dict] = []
    empresas_sem_certificado: list[dict] = []
    for r in resultados:
        if "erro_certificado" in r:
            empresas_sem_certificado.append(r)
            continue
        for k in ("consultadas", "eventos_aplicados", "status_alterado", "erros", "puladas"):
            totais[k] += int(r.get(k) or 0)
        alteradas.extend(r.get("alteradas") or [])
        erros.extend(r.get("erros_detalhes") or [])
    return {
        "dry_run": False,
        "notas_alvo": len(alvo),
        "empresas": len(por_empresa),
        **totais,
        "empresas_sem_certificado": empresas_sem_certificado,
        "alteradas": alteradas,
        "erros_detalhes": erros[:50],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--empresa-id", type=int)
    grupo.add_argument("--todas", action="store_true")
    parser.add_argument("--desde", type=date.fromisoformat, default=None, help="Somente notas emitidas a partir desta data")
    parser.add_argument("--ate", type=date.fromisoformat, default=None, help="Somente notas emitidas antes desta data (exclusivo)")
    parser.add_argument("--limite", type=int, default=None, help="Maximo de notas a consultar")
    parser.add_argument("--pausa", type=float, default=0.2, help="Segundos entre consultas de uma mesma empresa")
    parser.add_argument("--workers", type=int, default=1, help="Empresas processadas em paralelo")
    parser.add_argument("--executar", action="store_true", help="Sem esta opcao apenas conta as notas alvo")
    args = parser.parse_args()
    relatorio = executar(
        empresa_id=args.empresa_id,
        desde=args.desde,
        limite=args.limite,
        pausa=args.pausa,
        executar=args.executar,
        ate=args.ate,
        workers=args.workers,
    )
    print(json.dumps(relatorio, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
