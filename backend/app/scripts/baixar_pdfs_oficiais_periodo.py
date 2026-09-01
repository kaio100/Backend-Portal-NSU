from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import time
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from sqlalchemy import or_

from backend.app.core.config import settings
from backend.app.db.models import Certificado, Empresa, Nota
from backend.app.db.session import SessionLocal
from backend.app.repositories import arquivos_repo
from backend.app.services import legacy_processing_service, secrets_service
from backend.app.services.pdf_status_service import aplicar_status_pdf_oficial
from backend.app.services.storage_service import build_pdf_oficial_key, get_storage_service


def baixar(*, certificado_id: int, inicio: date, fim: date, pausa: float, executar: bool = False) -> dict:
    db = SessionLocal()
    temp_pfx: Path | None = None
    try:
        certificado = db.get(Certificado, certificado_id)
        if certificado is None or not certificado.ativo:
            raise RuntimeError("Certificado ativo nao encontrado.")
        empresa = db.get(Empresa, certificado.empresa_id)
        if empresa is None:
            raise RuntimeError("Empresa do certificado nao encontrada.")

        storage = get_storage_service()
        pfx_bytes = storage.get_bytes(certificado.storage_key)
        senha = secrets_service.get_secret_value(db, certificado.senha_secret_ref or "")
        descriptor, temp_name = tempfile.mkstemp(prefix="nfse_pdf_oficial_", suffix=".pfx")
        os.close(descriptor)
        Path(temp_name).write_bytes(pfx_bytes)
        temp_pfx = Path(temp_name)

        legacy = legacy_processing_service._load_legacy_module(0)
        config = legacy_processing_service._build_legacy_config(
            legacy,
            {
                "nome": empresa.nome,
                "cnpj": empresa.cnpj,
                "pfx_path": str(temp_pfx),
                "pfx_password": senha,
                "ambiente": empresa.ambiente or "producao",
                "verify_ssl": True,
            },
        )

        notas = (
            db.query(Nota)
            .filter(Nota.empresa_id == empresa.id)
            .filter(or_(Nota.tomador_cnpj == empresa.cnpj, Nota.prestador_cnpj == empresa.cnpj))
            .filter(Nota.data_emissao >= inicio)
            .filter(Nota.data_emissao < fim + timedelta(days=1))
            .order_by(Nota.data_emissao.asc(), Nota.id.asc())
            .all()
        )
        resultados: Counter[str] = Counter()
        if not executar:
            ausentes = sum(
                1 for nota in notas
                if not (nota.pdf_oficial_storage_key and storage.exists(nota.pdf_oficial_storage_key))
            )
            return {"executado": False, "notas": len(notas), "pdfs_ausentes": ausentes}
        for indice, nota in enumerate(notas, start=1):
            if nota.pdf_oficial_storage_key and storage.exists(nota.pdf_oficial_storage_key):
                content = storage.get_bytes(nota.pdf_oficial_storage_key)
                aplicar_status_pdf_oficial(nota, content, nota.status_documento)
                db.add(nota)
                db.commit()
                resultados["ja_existente"] += 1
                resultados["revalidado"] += 1
                continue
            chave = (nota.chave or "").strip()
            if not chave:
                resultados["sem_chave"] += 1
                continue

            response = None
            for tentativa in range(1, 4):
                try:
                    response = legacy.mtls_get(
                        config,
                        f"{config.base_danfse}/{chave}",
                        accept="application/pdf, application/json, text/plain, */*",
                        timeout=30,
                    )
                    break
                except Exception:
                    if tentativa == 3:
                        resultados["erro_conexao"] += 1
                    else:
                        time.sleep(2 * tentativa)
            if response is None:
                continue

            content = response.content or b""
            content_type = response.headers.get("content-type", "")
            if response.status_code != 200 or not (content.startswith(b"%PDF") or "pdf" in content_type.lower()):
                resultados[f"http_{response.status_code}"] += 1
                continue

            ano = str(nota.data_emissao.year if nota.data_emissao else inicio.year)
            mes = f"{nota.data_emissao.month if nota.data_emissao else inicio.month:02d}"
            filename = f"{chave}.pdf"
            storage_key = build_pdf_oficial_key(empresa.cnpj, ano, mes, filename)
            storage.put_bytes(storage_key, content, content_type="application/pdf")
            checksum = hashlib.sha256(content).hexdigest()
            arquivos_repo.create_arquivo_if_missing(
                db,
                {
                    "empresa_id": empresa.id,
                    "nota_id": nota.id,
                    "processo_id": nota.processo_id,
                    "tipo": "PDF_ORIGINAL",
                    "storage_backend": storage.backend,
                    "storage_bucket": settings.storage_bucket,
                    "storage_key": storage_key,
                    "filename": filename,
                    "content_type": "application/pdf",
                    "tamanho_bytes": len(content),
                    "checksum": checksum,
                },
            )
            nota.pdf_oficial_storage_key = storage_key
            aplicar_status_pdf_oficial(nota, content, nota.status_documento)
            db.add(nota)
            db.commit()
            resultados["baixado"] += 1
            print(f"{indice}/{len(notas)} baixado={resultados['baixado']}", flush=True)
            if pausa > 0:
                time.sleep(pausa)

        return {"executado": True, "notas": len(notas), **dict(resultados)}
    finally:
        db.close()
        if temp_pfx is not None:
            temp_pfx.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificado-id", type=int, required=True)
    parser.add_argument("--inicio", type=date.fromisoformat, required=True)
    parser.add_argument("--fim", type=date.fromisoformat, required=True)
    parser.add_argument("--pausa", type=float, default=0.5)
    parser.add_argument("--executar", action="store_true", help="Sem esta opcao apenas conta PDFs ausentes")
    args = parser.parse_args()
    print(baixar(certificado_id=args.certificado_id, inicio=args.inicio, fim=args.fim, pausa=args.pausa, executar=args.executar))


if __name__ == "__main__":
    main()
