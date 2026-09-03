"""Regenera exclusivamente PDFs espelho de uma competência e certificado."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import func

from backend.app.db.models import Arquivo, Certificado, Empresa, Nota, Processo
from backend.app.db.session import SessionLocal, init_db
from backend.app.services.danfse_service import DanfseError, DanfseService
from backend.app.services.storage_service import get_storage_service


@dataclass
class ItemResultado:
    nota_id: int
    numero_nfse: str | None
    pdf_espelho: str
    hash_anterior: str | None = None
    hash_novo: str | None = None
    tamanho_anterior: int | None = None
    tamanho_novo: int | None = None
    status: str = "pendente"
    erro: str | None = None


@dataclass
class Relatorio:
    certificado_id: int | None = None
    certificado_nome: str | None = None
    empresa_nome: str | None = None
    empresa_cnpj: str | None = None
    competencia: str = ""
    encontradas: int = 0
    elegiveis: int = 0
    regeneradas: int = 0
    falhas: int = 0
    itens: list[ItemResultado] = field(default_factory=list)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def executar(competencia: str, certificado_nome: str, dry_run: bool = True) -> Relatorio:
    try:
        inicio = date.fromisoformat(f"{competencia}-01")
    except ValueError as exc:
        raise ValueError("Competencia deve estar no formato YYYY-MM") from exc
    fim = date(inicio.year + (inicio.month == 12), 1 if inicio.month == 12 else inicio.month + 1, 1)

    init_db()
    storage = get_storage_service()
    relatorio = Relatorio(competencia=competencia)

    with SessionLocal() as db:
        certificados = (
            db.query(Certificado)
            .join(Empresa, Empresa.id == Certificado.empresa_id)
            .filter(Certificado.ativo.is_(True), func.lower(Certificado.nome).like(f"%{certificado_nome.lower()}%"))
            .all()
        )
        if len(certificados) != 1:
            raise RuntimeError(f"Certificado ativo ambiguo ou nao encontrado: {certificado_nome!r} ({len(certificados)} encontrados)")
        certificado = certificados[0]
        relatorio.certificado_id = int(certificado.id)
        relatorio.certificado_nome = certificado.nome
        relatorio.empresa_nome = certificado.empresa.nome
        relatorio.empresa_cnpj = certificado.empresa.cnpj

        notas = (
            db.query(Nota)
            .join(Processo, Processo.id == Nota.processo_id)
            .filter(
                Processo.certificado_id == certificado.id,
                Nota.competencia >= inicio,
                Nota.competencia < fim,
            )
            .order_by(Nota.id.asc())
            .all()
        )
        relatorio.encontradas = len(notas)

        for nota in notas:
            item = ItemResultado(int(nota.id), nota.numero_nfse, nota.pdf_espelho_storage_key or "")
            relatorio.itens.append(item)
            if not nota.xml_storage_key or not nota.pdf_espelho_storage_key:
                item.status = "ignorada_sem_xml_ou_espelho"
                continue
            arquivos = (
                db.query(Arquivo)
                .filter(
                    Arquivo.nota_id == nota.id,
                    func.lower(Arquivo.tipo) == "pdf_espelho",
                    Arquivo.storage_key == nota.pdf_espelho_storage_key,
                )
                .all()
            )
            if not arquivos or not storage.exists(nota.xml_storage_key) or not storage.exists(nota.pdf_espelho_storage_key):
                item.status = "ignorada_arquivo_ausente"
                continue
            relatorio.elegiveis += 1
            try:
                antigo = storage.get_bytes(nota.pdf_espelho_storage_key)
                item.hash_anterior = _sha256(antigo)
                item.tamanho_anterior = len(antigo)
                xml_bytes = storage.get_bytes(nota.xml_storage_key)
                novo, _ = DanfseService().generate(xml_bytes, watermark=nota.status_documento)
                item.hash_novo = _sha256(novo)
                item.tamanho_novo = len(novo)
                if dry_run:
                    item.status = "simulada"
                    continue

                meta = storage.put_bytes(nota.pdf_espelho_storage_key, novo, content_type="application/pdf")
                try:
                    for arquivo in arquivos:
                        arquivo.tamanho_bytes = int(meta.get("size") or len(novo))
                        arquivo.checksum = item.hash_novo
                        arquivo.content_type = "application/pdf"
                    db.commit()
                except Exception:
                    db.rollback()
                    storage.put_bytes(nota.pdf_espelho_storage_key, antigo, content_type="application/pdf")
                    raise
                item.status = "regenerada"
                relatorio.regeneradas += 1
            except Exception as exc:
                db.rollback()
                item.status = "falha"
                item.erro = f"{type(exc).__name__}: {exc}"[:500]
                relatorio.falhas += 1

    return relatorio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenera somente PDF_ESPELHO por certificado e competencia.")
    parser.add_argument("--competencia", required=True, help="Competencia no formato YYYY-MM")
    parser.add_argument("--certificado-nome", default="Central Park")
    parser.add_argument("--apply", action="store_true", help="Grava os PDFs; sem esta opcao executa dry-run")
    parser.add_argument("--relatorio", type=Path)
    args = parser.parse_args(argv)
    relatorio = executar(args.competencia, args.certificado_nome, dry_run=not args.apply)
    payload = asdict(relatorio)
    output = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    print(output)
    if args.relatorio:
        args.relatorio.parent.mkdir(parents=True, exist_ok=True)
        args.relatorio.write_text(output + "\n", encoding="utf-8")
    return 1 if relatorio.falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
