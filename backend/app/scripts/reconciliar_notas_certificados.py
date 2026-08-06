from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from backend.app.db.models import Certificado, Empresa, Job, Nota, Processo
from backend.app.db.session import SessionLocal
from backend.app.services import legacy_processing_service
from backend.app.services.legacy_ingestion_service import _parse_xml_resumo, ingerir_saida_legado
from backend.app.services.storage_service import get_storage_service


STATUS_ATIVOS = ("pendente", "rodando")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def _xml_e_evento(path_value: str) -> bool:
    path = Path(path_value or "")
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return False
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError:
        return False
    return root.tag.rsplit("}", 1)[-1].lower() == "evento"


def _restaurar_indices_nfse(base_dir: Path) -> dict[str, int]:
    index_path = base_dir / "index_nfse.csv"
    ocorrencias_path = base_dir / "ocorrencias_nsu.csv"
    index_rows = _read_csv(index_path)
    ocorrencias = _read_csv(ocorrencias_path)
    if not index_rows or not ocorrencias:
        return {"indices_evento_detectados": 0, "indices_restaurados": 0}

    nfse_por_chave: dict[str, list[dict[str, str]]] = defaultdict(list)
    for ocorrencia in ocorrencias:
        tipo = str(ocorrencia.get("tipo_documento") or "").strip().upper()
        if tipo in {"NFSE", "NFS-E"}:
            nfse_por_chave[str(ocorrencia.get("chave") or "").strip()].append(ocorrencia)

    corrompidos = [
        row for row in index_rows
        if str(row.get("tipo_documento") or "").strip().upper() in {"NFSE", "NFS-E"}
        and _xml_e_evento(row.get("xml_path") or "")
    ]
    if not corrompidos:
        return {"indices_evento_detectados": 0, "indices_restaurados": 0}

    legacy = legacy_processing_service._load_legacy_module(999_998)
    legacy_processing_service._configure_legacy_output(legacy, base_dir)
    ultimos_nsu = {str(row.get("chave") or "").strip(): row.get("ultimo_nsu") or "" for row in corrompidos}
    restaurados = 0
    for row in corrompidos:
        chave = str(row.get("chave") or "").strip()
        candidatas = sorted(
            nfse_por_chave.get(chave, []),
            key=lambda item: int(item.get("nsu") or 0),
        )
        if not candidatas:
            continue
        json_path = Path(candidatas[0].get("json_path") or "")
        if not json_path.is_absolute():
            json_path = Path.cwd() / json_path
        if not json_path.exists():
            continue
        documento = json.loads(json_path.read_text(encoding="utf-8-sig"))
        legacy.salvar_documento(documento)
        restaurados += 1

    # Restaurar o XML original nao deve apagar a informacao de que houve um
    # evento posterior com NSU mais alto.
    rows_by_key = legacy.carregar_csv_por_chave(legacy.INDEX_UNICO_FILE, "chave")
    for chave, ultimo_nsu in ultimos_nsu.items():
        if chave in rows_by_key and ultimo_nsu:
            rows_by_key[chave]["ultimo_nsu"] = ultimo_nsu
    legacy.salvar_index_unico(rows_by_key)
    return {
        "indices_evento_detectados": len(corrompidos),
        "indices_restaurados": restaurados,
    }


def reconciliar_certificado(certificado_id: int, batch_size: int | None = None) -> dict[str, Any]:
    with SessionLocal() as db:
        certificado = db.get(Certificado, certificado_id)
        if certificado is None or not certificado.ativo:
            return {"certificado_id": certificado_id, "ok": False, "motivo": "certificado_inativo_ou_ausente"}
        empresa = db.get(Empresa, certificado.empresa_id)
        if empresa is None:
            return {"certificado_id": certificado_id, "ok": False, "motivo": "empresa_ausente"}
        ativo = db.query(Job.id).filter(Job.certificado_id == certificado_id, Job.status.in_(STATUS_ATIVOS)).first()
        if ativo:
            return {"certificado_id": certificado_id, "ok": False, "motivo": "job_ativo"}

        base_dir = Path("saida_adn_nfse") / "empresas" / f"empresa_{empresa.id}_cert_{certificado.id}"
        index_path = base_dir / "index_nfse.csv"
        if not index_path.exists():
            return {
                "certificado_id": certificado.id,
                "empresa": empresa.nome,
                "grupo": empresa.grupo,
                "ok": True,
                "motivo": "sem_indice_local",
                "notas_ausentes": 0,
            }

        restauracao = _restaurar_indices_nfse(base_dir)
        rows = _read_csv(index_path)
        chaves_indice = {
            str(row.get("chave") or "").strip()
            for row in rows
            if str(row.get("tipo_documento") or "").strip().upper() in {"NFSE", "NFS-E"}
            and str(row.get("chave") or "").strip()
            and not _xml_e_evento(row.get("xml_path") or "")
        }
        chaves_banco = {
            str(chave) for (chave,) in db.query(Nota.chave).filter(Nota.empresa_id == empresa.id).all()
        }
        todas_ausentes = chaves_indice - chaves_banco
        ausentes = set(sorted(todas_ausentes)[:batch_size]) if batch_size else todas_ausentes
        if not todas_ausentes:
            return {
                "certificado_id": certificado.id,
                "empresa": empresa.nome,
                "grupo": empresa.grupo,
                "ok": True,
                **restauracao,
                "notas_indice": len(chaves_indice),
                "notas_ausentes": 0,
                "notas_importadas": 0,
            }

        processo = (
            db.query(Processo)
            .filter(Processo.certificado_id == certificado.id)
            .order_by(Processo.id.desc())
            .first()
        )
        if processo is None:
            return {
                "certificado_id": certificado.id,
                "empresa": empresa.nome,
                "grupo": empresa.grupo,
                "ok": False,
                "motivo": "sem_processo_para_ingestao",
                "notas_ausentes": len(todas_ausentes),
            }

        resultado = ingerir_saida_legado(
            db,
            get_storage_service(),
            processo,
            base_dir,
            only_chaves=ausentes,
            commit_every=25,
        )
        db.commit()
        return {
            "certificado_id": certificado.id,
            "empresa": empresa.nome,
            "grupo": empresa.grupo,
            "ok": int(resultado.get("erros") or 0) == 0,
            **restauracao,
            "notas_indice": len(chaves_indice),
            "notas_ausentes": len(todas_ausentes),
            "notas_processadas_neste_lote": len(ausentes),
            "notas_importadas": int(resultado.get("notas_criadas") or 0),
            "avisos_pdf": int(resultado.get("avisos_pdf") or 0),
            "erros": int(resultado.get("erros") or 0),
            "erros_detalhes": resultado.get("erros_detalhes") or [],
        }


def executar(
    grupo: str | None = None,
    certificado_id: int | None = None,
    batch_size: int | None = None,
) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        query = db.query(Certificado.id).join(Empresa, Empresa.id == Certificado.empresa_id).filter(
            Certificado.ativo.is_(True),
            Empresa.ativo.is_(True),
        )
        if grupo:
            query = query.filter(Empresa.grupo == grupo)
        if certificado_id:
            query = query.filter(Certificado.id == certificado_id)
        ids = [int(certificado_id) for (certificado_id,) in query.order_by(Certificado.id).all()]
    return [reconciliar_certificado(item_id, batch_size=batch_size) for item_id in ids]


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcilia indices ADN com notas persistidas")
    parser.add_argument("--grupo", default="")
    parser.add_argument("--certificado-id", type=int)
    parser.add_argument("--batch-size", type=int)
    args = parser.parse_args()
    print(json.dumps(executar(args.grupo or None, args.certificado_id, args.batch_size), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
