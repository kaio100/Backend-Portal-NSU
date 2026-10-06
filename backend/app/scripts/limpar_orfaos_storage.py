"""Acha (e, com --aplicar, apaga) arquivos do storage que nenhum registro usa.

Olha so os prefixos gravados pelo portal: xml/, pdf-oficial/, pdf-espelho/ e
certificados/. Um arquivo e orfao quando nao aparece em arquivos.storage_key,
nas chaves de notas (xml, pdf oficial, pdf espelho, backup do arquivamento),
em eventos.xml_storage_key nem em certificados.storage_key.

Com --pfx-inativos tambem entram os PFX de certificados desativados (quem
renovou o certificado deixa o PFX antigo guardado; apagar reduz a exposicao).

Rode com o worker parado: durante uma consulta o arquivo e gravado no storage
um pouco antes do registro no banco. Antes de apagar, cada chave e conferida
de novo no banco.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.db.models import Arquivo, Certificado, Evento, Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.services.storage_service import StorageService, get_storage_service

PREFIXOS = ("xml/", "pdf-oficial/", "pdf-espelho/", "certificados/")


def _normalizar(chave: str | None) -> str | None:
    if not chave:
        return None
    return str(chave).replace("\\", "/").lstrip("/")


def _chaves_em_uso(db: Session, pfx_inativos: bool) -> set[str]:
    colunas = [
        Arquivo.storage_key,
        Nota.xml_storage_key,
        Nota.pdf_oficial_storage_key,
        Nota.pdf_espelho_storage_key,
        Nota.arquivo_backup_storage_key,
        Evento.xml_storage_key,
    ]
    em_uso: set[str] = set()
    for coluna in colunas:
        for (valor,) in db.query(coluna).filter(coluna.isnot(None)).yield_per(5000):
            chave = _normalizar(valor)
            if chave:
                em_uso.add(chave)
    certificados = db.query(Certificado.storage_key)
    if pfx_inativos:
        certificados = certificados.filter(Certificado.ativo.is_(True))
    for (valor,) in certificados.all():
        chave = _normalizar(valor)
        if chave:
            em_uso.add(chave)
    return em_uso


def executar(
    aplicar: bool = False,
    pfx_inativos: bool = False,
    storage: StorageService | None = None,
) -> dict:
    init_db()
    storage = storage or get_storage_service()
    relatorio: dict = {"modo": "aplicacao" if aplicar else "simulacao", "por_prefixo": {}, "orfaos": [], "apagados": 0}
    with SessionLocal() as db:
        em_uso = _chaves_em_uso(db, pfx_inativos)
        for prefixo in PREFIXOS:
            chaves = storage.list_keys(prefixo)
            orfaos = [chave for chave in chaves if _normalizar(chave) not in em_uso]
            relatorio["por_prefixo"][prefixo] = {"arquivos": len(chaves), "orfaos": len(orfaos)}
            relatorio["orfaos"].extend(orfaos)
        if aplicar and relatorio["orfaos"]:
            # Confere de novo: algo pode ter sido gravado desde a primeira leitura.
            em_uso = _chaves_em_uso(db, pfx_inativos)
            for chave in relatorio["orfaos"]:
                if _normalizar(chave) in em_uso:
                    continue
                if storage.delete(chave):
                    relatorio["apagados"] += 1
    relatorio["total_orfaos"] = len(relatorio["orfaos"])
    return relatorio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--aplicar", action="store_true", help="Apaga os orfaos; sem esta opcao apenas lista.")
    parser.add_argument("--pfx-inativos", action="store_true", help="Trata PFX de certificados desativados como orfaos.")
    parser.add_argument("--relatorio", default="relatorio_orfaos_storage.json")
    args = parser.parse_args(argv)
    relatorio = executar(aplicar=args.aplicar, pfx_inativos=args.pfx_inativos)
    Path(args.relatorio).write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in relatorio.items() if k != "orfaos"}, ensure_ascii=False, indent=2))
    print(f"Lista completa: {args.relatorio}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
