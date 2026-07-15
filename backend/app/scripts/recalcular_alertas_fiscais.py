"""Recalcula os alertas fiscais (subitem LC116, ISS retido, valor liquido)
das notas ja importadas, reparseando o XML ja armazenado localmente.

Nao baixa notas novas da ADN, nao apaga notas e nao apaga arquivos. So
atualiza os campos da tabela `notas` relacionados a analise fiscal.

Uso:
    python -m backend.app.scripts.recalcular_alertas_fiscais --dry-run
    python -m backend.app.scripts.recalcular_alertas_fiscais --all
    python -m backend.app.scripts.recalcular_alertas_fiscais --empresa-id 1
    python -m backend.app.scripts.recalcular_alertas_fiscais --all --dry-run --batch-size 500
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.app.db.models import Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.services.legacy_ingestion_service import (
    _aplicar_campos_fiscais_xml,
    _parse_decimal,
    parse_xml_resumo_bytes,
)
from backend.app.services.storage_service import StorageService, get_storage_service


@dataclass
class Relatorio:
    total_analisadas: int = 0
    notas_sem_xml: int = 0
    erros_xml: int = 0
    com_subitem: int = 0
    sem_subitem: int = 0
    notas_alteradas: int = 0
    alertas_removidos: int = 0
    alertas_mantidos: int = 0
    alertas_adicionados: int = 0

    def imprimir(self, dry_run: bool) -> None:
        modo = "DRY-RUN (nenhuma alteracao foi salva)" if dry_run else "EXECUCAO REAL (alteracoes salvas no banco)"
        linhas = [
            "",
            "========== Relatorio de recalculo de alertas fiscais ==========",
            f"Modo: {modo}",
            f"Total de notas analisadas..............: {self.total_analisadas}",
            f"Notas sem XML disponivel no storage.....: {self.notas_sem_xml}",
            f"Erros ao reprocessar XML................: {self.erros_xml}",
            f"Notas com subitem LC116 identificado....: {self.com_subitem}",
            f"Notas ainda sem subitem LC116...........: {self.sem_subitem}",
            f"Notas com alertas alterados..............: {self.notas_alteradas}",
            f"Total de alertas removidos...............: {self.alertas_removidos}",
            f"Total de alertas mantidos................: {self.alertas_mantidos}",
            f"Total de alertas novos...................: {self.alertas_adicionados}",
            "=================================================================",
        ]
        print("\n".join(linhas))


def _split_alertas(texto: str | None) -> set[str]:
    if not texto:
        return set()
    return {linha.strip() for linha in str(texto).split("\n") if linha.strip()}


def _listar_lotes_de_ids(db: Session, empresa_id: int | None, batch_size: int) -> list[list[int]]:
    query = db.query(Nota.id).order_by(Nota.id.asc())
    if empresa_id is not None:
        query = query.filter(Nota.empresa_id == empresa_id)
    ids = [row[0] for row in query.all()]
    return [ids[i : i + batch_size] for i in range(0, len(ids), batch_size)]


def recalcular_nota(nota: Nota, storage: StorageService, dry_run: bool, relatorio: Relatorio) -> None:
    relatorio.total_analisadas += 1

    storage_key = nota.xml_storage_key
    if not storage_key or not storage.exists(storage_key):
        relatorio.notas_sem_xml += 1
        return

    try:
        xml_bytes = storage.get_bytes(storage_key)
        resumo = parse_xml_resumo_bytes(xml_bytes, filename=storage_key)
    except Exception:
        relatorio.erros_xml += 1
        return

    if resumo.get("tipo_xml") == "evento" or "alertas_fiscais" not in resumo:
        relatorio.erros_xml += 1
        return

    if resumo.get("subitem_lc116"):
        relatorio.com_subitem += 1
    else:
        relatorio.sem_subitem += 1

    alertas_antigos = _split_alertas(nota.alertas_fiscais)
    alertas_novos = _split_alertas(resumo.get("alertas_fiscais"))
    relatorio.alertas_removidos += len(alertas_antigos - alertas_novos)
    relatorio.alertas_mantidos += len(alertas_antigos & alertas_novos)
    relatorio.alertas_adicionados += len(alertas_novos - alertas_antigos)

    nota_data: dict = {}
    _aplicar_campos_fiscais_xml(nota_data, resumo)
    if resumo.get("codigo_servico"):
        nota_data["codigo_servico"] = resumo.get("codigo_servico")
    # `_aplicar_campos_fiscais_xml` nao cobre esses dois campos (sao preenchidos
    # de outra forma no fluxo de ingestao normal), mas fazem parte da analise
    # fiscal e precisam ser atualizados no recalculo.
    if resumo.get("status_valor_liquido"):
        nota_data["status_valor_liquido"] = resumo.get("status_valor_liquido")
    if resumo.get("valor_liquido_correto") not in (None, ""):
        nota_data["valor_liquido_correto"] = _parse_decimal(str(resumo.get("valor_liquido_correto")))

    mudou = any(str(valor) != str(getattr(nota, campo, None)) for campo, valor in nota_data.items())
    if not mudou:
        return

    relatorio.notas_alteradas += 1
    if dry_run:
        return

    for campo, valor in nota_data.items():
        setattr(nota, campo, valor)


def executar(empresa_id: int | None, dry_run: bool, batch_size: int) -> Relatorio:
    init_db()
    storage = get_storage_service()
    relatorio = Relatorio()

    with SessionLocal() as db:
        lotes = _listar_lotes_de_ids(db, empresa_id, batch_size)
        total_lotes = len(lotes)
        for indice, lote_ids in enumerate(lotes, start=1):
            if not lote_ids:
                continue
            notas = db.query(Nota).filter(Nota.id.in_(lote_ids)).order_by(Nota.id.asc()).all()
            for nota in notas:
                recalcular_nota(nota, storage, dry_run, relatorio)
            if dry_run:
                db.rollback()
            else:
                db.commit()
            print(f"Lote {indice}/{total_lotes} processado ({len(notas)} notas).")

    return relatorio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recalcula alertas fiscais (subitem LC116, ISS retido, valor liquido) das notas "
            "ja importadas, reparseando o XML ja armazenado. Nao baixa notas novas da ADN, "
            "nao apaga notas nem arquivos."
        )
    )
    parser.add_argument("--dry-run", action="store_true", help="Nao grava alteracoes, apenas mostra o que mudaria.")
    parser.add_argument("--all", action="store_true", help="Processa as notas de todas as empresas.")
    parser.add_argument("--empresa-id", type=int, default=None, help="Processa apenas as notas da empresa informada.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Quantidade de notas processadas e commitadas por lote (padrao: 200).",
    )
    args = parser.parse_args(argv)

    if not args.all and args.empresa_id is None and not args.dry_run:
        parser.error(
            "Informe --all (todas as empresas) ou --empresa-id (uma empresa especifica) para "
            "uma execucao real. Use --dry-run para simular sem escopo explicito."
        )

    relatorio = executar(empresa_id=args.empresa_id, dry_run=args.dry_run, batch_size=max(1, args.batch_size))
    relatorio.imprimir(args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
