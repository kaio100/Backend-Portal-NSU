from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from backend.app.db.models import Certificado, Empresa
from backend.app.db.session import SessionLocal
from backend.app.services import legacy_processing_service, secrets_service
from backend.app.services.storage_service import get_storage_service


def executar(certificado_id: int, nsus: list[int], pausa: float, lote: bool = False) -> list[dict]:
    with SessionLocal() as db:
        certificado = db.get(Certificado, certificado_id)
        if certificado is None or not certificado.ativo:
            raise RuntimeError("Certificado nao encontrado ou inativo.")
        empresa = db.get(Empresa, certificado.empresa_id)
        if empresa is None or not empresa.ativo:
            raise RuntimeError("Empresa nao encontrada ou inativa.")
        pfx_bytes = get_storage_service().get_bytes(certificado.storage_key)
        senha = secrets_service.get_secret_value(db, certificado.senha_secret_ref or "")
        empresa_item = {
            "cnpj": empresa.cnpj,
            "ambiente": empresa.ambiente or "producao",
            "verify_ssl": True,
            "pfx_password": senha,
        }

    resultados: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="nfse_nsu_diagnostico_") as temp_dir:
        pfx_path = Path(temp_dir) / "certificado.pfx"
        pfx_path.write_bytes(pfx_bytes)
        empresa_item["pfx_path"] = str(pfx_path)
        legacy = legacy_processing_service._load_legacy_module(0)
        config = legacy_processing_service._build_legacy_config(legacy, empresa_item)

        for indice, nsu in enumerate(nsus):
            try:
                url = f"{config.base_contribuintes}/DFe/{nsu}"
                response = legacy.mtls_get(
                    config,
                    url,
                    params={"cnpjConsulta": config.cnpj, "lote": str(lote).lower()},
                    timeout=60,
                )
                try:
                    payload = response.json()
                except Exception:
                    payload = {}
                lote_dfe = payload.get("LoteDFe") or [] if isinstance(payload, dict) else []
                estrutura = {
                    str(chave): (
                        f"lista[{len(valor)}]"
                        if isinstance(valor, list)
                        else f"objeto[{len(valor)}]"
                        if isinstance(valor, dict)
                        else valor
                        if isinstance(valor, (str, int, float, bool)) or valor is None
                        else type(valor).__name__
                    )
                    for chave, valor in payload.items()
                    if chave != "LoteDFe"
                } if isinstance(payload, dict) else {}
                erros = payload.get("Erros") if isinstance(payload, dict) else None
                resultados.append(
                    {
                        "nsu": nsu,
                        "http": response.status_code,
                        "status_processamento": payload.get("StatusProcessamento") if isinstance(payload, dict) else None,
                        "documentos": len(lote_dfe) if isinstance(lote_dfe, list) else 0,
                        "mensagem": (
                            payload.get("Mensagem")
                            or payload.get("mensagem")
                            or payload.get("Message")
                            or payload.get("message")
                        ) if isinstance(payload, dict) else None,
                        "resposta_json": isinstance(payload, dict) and bool(payload),
                        "estrutura": estrutura,
                        "erros": erros if isinstance(erros, list) else [],
                    }
                )
            except Exception as exc:
                resultados.append({"nsu": nsu, "erro": str(exc)})
            if indice < len(nsus) - 1:
                time.sleep(max(0.0, pausa))
    return resultados


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("certificado_id", type=int)
    parser.add_argument("nsus", nargs="+", type=int)
    parser.add_argument("--pausa", type=float, default=2.0)
    parser.add_argument("--lote", action="store_true")
    args = parser.parse_args()
    print(json.dumps(executar(args.certificado_id, args.nsus, args.pausa, args.lote), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
