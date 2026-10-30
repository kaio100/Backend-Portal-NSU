"""Regenera o PDF espelho das notas emitidas a partir de uma data (padrao 01/09/2026).

O espelho guardado no storage e o que o ZIP em lote entrega. PDFs gerados antes
da mudanca de layout (`e71fc73c`, 06/10/2026) ficam no layout antigo. Este script
refaz so as notas com `data_emissao >= --desde`, a partir do XML armazenado.

Sem `--aplicar` e uma simulacao: gera o PDF novo em memoria, compara com o
guardado e nao grava nada. Com `--aplicar`, troca o arquivo na mesma chave de
storage e atualiza `arquivos` (tamanho e checksum); se o banco falhar, devolve o
PDF anterior ao storage. Notas sem espelho (por exemplo, so tinham o PDF oficial
que nao existe mais) ganham um espelho novo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

from backend.app.core.config import settings
from backend.app.db.models import Arquivo, Empresa, Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.services.danfse_service import DanfseService, friendly_pdf_filename
from backend.app.services.nfse_xml_parser import extrair_dados_nfse
from backend.app.services.storage_service import build_pdf_espelho_key, get_storage_service

DESDE_PADRAO = "2026-09-01"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenera o PDF espelho das notas emitidas a partir de uma data.")
    parser.add_argument("--desde", default=DESDE_PADRAO, help="Data de emissao inicial, YYYY-MM-DD (padrao 2026-09-01)")
    parser.add_argument("--empresa-id", type=int, default=None)
    parser.add_argument("--limite", type=int, default=None, help="Maximo de notas nesta execucao")
    parser.add_argument("--aplicar", action="store_true", help="Grava no storage; sem esta opcao e so simulacao")
    parser.add_argument("--relatorio", type=Path, default=None, help="Grava o resultado por nota em JSON")
    args = parser.parse_args(argv)
    desde = date.fromisoformat(args.desde)

    init_db()
    from backend.app.core.php_runtime import configurar_php

    configurar_php()
    storage = get_storage_service()
    gerador = DanfseService()
    contagem: Counter[str] = Counter()
    itens: list[dict] = []

    with SessionLocal() as db:
        query = db.query(Nota).filter(
            Nota.data_emissao >= desde,
            Nota.xml_storage_key.isnot(None),
            Nota.arquivada.is_(False),
        )
        if args.empresa_id is not None:
            query = query.filter(Nota.empresa_id == args.empresa_id)
        query = query.order_by(Nota.id.asc())
        if args.limite:
            query = query.limit(args.limite)
        notas = query.all()
        print(f"Notas emitidas desde {desde}: {len(notas)} ({'APLICANDO' if args.aplicar else 'simulacao'})", flush=True)
        cnpj_por_empresa = {
            empresa.id: empresa.cnpj
            for empresa in db.query(Empresa).filter(Empresa.id.in_({nota.empresa_id for nota in notas})).all()
        }

        for nota in notas:
            item = {"nota_id": int(nota.id), "numero_nfse": nota.numero_nfse, "status": "pendente"}
            itens.append(item)
            try:
                if not storage.exists(nota.xml_storage_key):
                    item["status"] = "ignorada_xml_ausente"
                    continue
                xml_bytes = storage.get_bytes(nota.xml_storage_key)
                novo, _ = gerador.generate(xml_bytes, watermark=nota.status_documento)
                novo_hash = _sha256(novo)

                chave = nota.pdf_espelho_storage_key
                antigo: bytes | None = None
                if chave and storage.exists(chave):
                    antigo = storage.get_bytes(chave)
                    if _sha256(antigo) == novo_hash:
                        item["status"] = "ja_atual"
                        continue
                item["acao"] = "regenerar" if antigo is not None else "criar"
                if not args.aplicar:
                    item["status"] = "simulada"
                    continue

                filename = None
                if chave is None:
                    with tempfile.TemporaryDirectory(prefix="danfse_desde_") as temp_dir:
                        xml_path = Path(temp_dir) / "entrada.xml"
                        xml_path.write_bytes(xml_bytes)
                        filename = friendly_pdf_filename(extrair_dados_nfse(xml_path, prefeitura_info=None))
                    ref = nota.competencia or nota.data_emissao
                    chave = build_pdf_espelho_key(
                        cnpj_por_empresa[nota.empresa_id], str(ref.year), f"{ref.month:02d}", filename
                    )

                storage.put_bytes(chave, novo, content_type="application/pdf")
                try:
                    nota.pdf_espelho_storage_key = chave
                    arquivo = (
                        db.query(Arquivo)
                        .filter(Arquivo.nota_id == nota.id, Arquivo.tipo.in_(("PDF_ESPELHO", "pdf_espelho")))
                        .first()
                    )
                    if arquivo is None:
                        arquivo = Arquivo(
                            empresa_id=nota.empresa_id,
                            nota_id=nota.id,
                            processo_id=nota.processo_id,
                            tipo="PDF_ESPELHO",
                            storage_backend=settings.storage_backend,
                            storage_bucket=settings.storage_bucket,
                            storage_key=chave,
                        )
                        db.add(arquivo)
                    arquivo.storage_key = chave
                    if filename:
                        arquivo.filename = filename
                    arquivo.content_type = "application/pdf"
                    arquivo.tamanho_bytes = len(novo)
                    arquivo.checksum = novo_hash
                    db.commit()
                except Exception:
                    db.rollback()
                    if antigo is not None:
                        storage.put_bytes(chave, antigo, content_type="application/pdf")
                    else:
                        storage.delete(chave)
                    raise
                item["status"] = "regenerada" if antigo is not None else "criada"
            except Exception as exc:
                db.rollback()
                item["status"] = "falha"
                item["erro"] = f"{type(exc).__name__}: {exc}"[:500]
                print(f"Falha nota {nota.id} ({nota.numero_nfse}): {item['erro']}", flush=True)
            finally:
                contagem[item["status"]] += 1
                total = sum(contagem.values())
                if total % 25 == 0:
                    print(f"Progresso: {total}/{len(notas)} {dict(contagem)}", flush=True)

    resumo = {"desde": str(desde), "aplicado": bool(args.aplicar), "total": len(itens), "resultado": dict(contagem)}
    print(json.dumps(resumo, ensure_ascii=False, indent=2))
    if args.relatorio:
        args.relatorio.parent.mkdir(parents=True, exist_ok=True)
        args.relatorio.write_text(
            json.dumps({**resumo, "itens": itens}, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    return 1 if contagem.get("falha") else 0


if __name__ == "__main__":
    raise SystemExit(main())
