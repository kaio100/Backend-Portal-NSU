from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func

from backend.app.db.models import Certificado, Empresa, Job, Nota, NsuControle, Processo
from backend.app.db.session import SessionLocal
from backend.app.services import certificado_metadata_service, secrets_service
from backend.app.services.storage_service import get_storage_service


def executar() -> dict:
    storage = get_storage_service()
    agora = datetime.now(timezone.utc)
    itens: list[dict] = []

    with SessionLocal() as db:
        certificados = db.query(Certificado).order_by(Certificado.id).all()
        empresas_por_cnpj = {empresa.cnpj: empresa for empresa in db.query(Empresa).all()}

        for certificado in certificados:
            empresa = db.get(Empresa, certificado.empresa_id)
            problemas: list[str] = []
            metadata = None

            if empresa is None:
                problemas.append("empresa_ausente")
            if not certificado.storage_key or certificado.storage_key == "pending":
                problemas.append("storage_key_ausente")
            elif not certificado.senha_secret_ref:
                problemas.append("senha_ausente")
            else:
                try:
                    pfx = storage.get_bytes(certificado.storage_key)
                except Exception as exc:
                    problemas.append(f"pfx_inacessivel:{type(exc).__name__}")
                else:
                    try:
                        senha = secrets_service.get_secret_value(db, certificado.senha_secret_ref)
                        metadata = certificado_metadata_service.extrair_metadata_pfx(pfx, senha)
                    except Exception as exc:
                        problemas.append(f"pfx_ou_senha_invalido:{type(exc).__name__}")

            cnpj_pfx = metadata.cnpj if metadata else None
            empresa_cnpj = empresa.cnpj if empresa else None
            empresa_correta = empresas_por_cnpj.get(cnpj_pfx) if cnpj_pfx else None
            if metadata and not cnpj_pfx:
                problemas.append("cnpj_nao_extraido_do_pfx")
            if cnpj_pfx and empresa_cnpj != cnpj_pfx:
                problemas.append("cnpj_pfx_diverge_da_empresa")
            if metadata and certificado.thumbprint and certificado.thumbprint != metadata.thumbprint:
                problemas.append("thumbprint_divergente")
            if metadata and metadata.valido_ate:
                valido_ate = metadata.valido_ate
                if valido_ate.tzinfo is None:
                    valido_ate = valido_ate.replace(tzinfo=timezone.utc)
                if valido_ate < agora:
                    problemas.append("certificado_expirado")

            nsu = (
                db.query(NsuControle)
                .filter(
                    NsuControle.empresa_id == certificado.empresa_id,
                    NsuControle.certificado_id == certificado.id,
                )
                .first()
            )
            if nsu is None:
                problemas.append("controle_nsu_ausente")
            elif empresa_cnpj and nsu.cnpj != empresa_cnpj:
                problemas.append("cnpj_controle_nsu_divergente")

            notas_total, maior_nsu = (
                db.query(func.count(Nota.id), func.max(Nota.ultimo_nsu))
                .filter(Nota.empresa_id == certificado.empresa_id)
                .one()
            )
            processos_total = db.query(func.count(Processo.id)).filter(Processo.certificado_id == certificado.id).scalar()
            jobs_ativos = (
                db.query(func.count(Job.id))
                .filter(Job.certificado_id == certificado.id, Job.status.in_(("pendente", "rodando")))
                .scalar()
            )

            itens.append(
                {
                    "certificado_id": certificado.id,
                    "ativo": certificado.ativo,
                    "empresa_id": certificado.empresa_id,
                    "empresa_nome": empresa.nome if empresa else None,
                    "empresa_cnpj": empresa_cnpj,
                    "grupo": empresa.grupo if empresa else None,
                    "cnpj_pfx": cnpj_pfx,
                    "empresa_correta_id": empresa_correta.id if empresa_correta else None,
                    "thumbprint_pfx": metadata.thumbprint if metadata else None,
                    "valido_ate": metadata.valido_ate.isoformat() if metadata and metadata.valido_ate else None,
                    "ultimo_nsu_controle": int(nsu.ultimo_nsu or 0) if nsu else None,
                    "maior_nsu_nota": int(maior_nsu or 0),
                    "notas_empresa": int(notas_total or 0),
                    "processos_certificado": int(processos_total or 0),
                    "jobs_ativos": int(jobs_ativos or 0),
                    "problemas": problemas,
                }
            )

    thumbprints = Counter(item["thumbprint_pfx"] for item in itens if item["thumbprint_pfx"])
    for item in itens:
        if item["thumbprint_pfx"] and thumbprints[item["thumbprint_pfx"]] > 1:
            item["problemas"].append("pfx_duplicado")

    contagem = Counter(problema.split(":", 1)[0] for item in itens for problema in item["problemas"])
    return {
        "somente_leitura": True,
        "storage_backend": storage.backend,
        "certificados_total": len(itens),
        "certificados_ativos": sum(1 for item in itens if item["ativo"]),
        "certificados_com_problema": sum(1 for item in itens if item["problemas"]),
        "problemas_por_tipo": dict(sorted(contagem.items())),
        "itens": itens,
    }


def main() -> None:
    print(json.dumps(executar(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
