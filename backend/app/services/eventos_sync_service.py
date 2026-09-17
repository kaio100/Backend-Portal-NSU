"""Consulta os eventos de uma NFS-e no ADN e aplica na nota ja importada.

O fluxo normal de consulta por NSU ja entrega eventos (cancelamento,
substituicao) e a ingestao os aplica. Este servico cobre o que o NSU nao
alcanca: nota antiga, empresa que ficou sem consulta por um periodo ou duvida
pontual do operador. Usa o endpoint `/NFSe/{chave}/Eventos` do ADN com o
certificado da empresa e reaproveita exatamente a mesma rotina de ingestao
(`_registrar_evento_xml` + regeneracao do espelho com carimbo).
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import requests
import requests_pkcs12
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Certificado, Empresa, Nota
from backend.app.services import legacy_ingestion_service, secrets_service
from backend.app.services.storage_service import StorageService, build_xml_key


class EventosSyncError(RuntimeError):
    pass


ADN_BASES = {
    "producao": "https://adn.nfse.gov.br/contribuintes",
    "restrita": "https://adn.producaorestrita.nfse.gov.br/contribuintes",
    "homologacao": "https://adn.producaorestrita.nfse.gov.br/contribuintes",
}


def _certificado_da_empresa(db: Session, empresa_id: int) -> Certificado:
    certificado = (
        db.query(Certificado)
        .filter(Certificado.empresa_id == empresa_id)
        .filter(Certificado.ativo.is_(True))
        .filter(Certificado.storage_key.isnot(None))
        .filter(Certificado.senha_secret_ref.isnot(None))
        .order_by(Certificado.valido_ate.desc().nullslast(), Certificado.id.desc())
        .first()
    )
    if certificado is None:
        raise EventosSyncError("A empresa nao possui certificado ativo com senha cadastrada.")
    return certificado


_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 ADN-NFSe-Portal/2.0",
}


def _base_adn(ambiente: str) -> str:
    base = ADN_BASES.get((ambiente or "producao").lower().strip())
    if base is None:
        raise EventosSyncError("Ambiente da empresa deve ser 'producao' ou 'restrita'.")
    return base


class SessaoCertificado:
    """PFX temporario + conexao HTTPS mTLS reaproveitados para varias consultas.

    Por nota, o caminho simples baixava o PFX do R2, decifrava a senha e abria
    um handshake TLS novo (~7 s por nota na varredura). Uma sessao por empresa
    reduz isso a uma unica preparacao e mantem a conexao viva (keep-alive).
    """

    def __init__(self, db: Session, storage: StorageService, empresa: Empresa) -> None:
        certificado = _certificado_da_empresa(db, int(empresa.id))
        self.empresa = empresa
        self.cnpj = re.sub(r"\D", "", str(empresa.cnpj or ""))
        self.base = _base_adn(str(empresa.ambiente or "producao"))
        temp_dir = Path(settings.worker_temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        self.pfx_path = temp_dir / f"eventos_cert_{certificado.id}_{uuid.uuid4().hex}.pfx"
        self.pfx_path.write_bytes(storage.get_bytes(certificado.storage_key))
        senha = secrets_service.get_secret_value(db, str(certificado.senha_secret_ref))
        self.http = requests.Session()
        self.http.mount(self.base, requests_pkcs12.Pkcs12Adapter(pkcs12_filename=str(self.pfx_path), pkcs12_password=senha))
        senha = ""

    def consultar(self, chave: str, timeout: int = 120) -> dict[str, Any]:
        response = self.http.get(
            f"{self.base}/NFSe/{chave}/Eventos",
            params={"cnpjConsulta": self.cnpj},
            headers=_HEADERS,
            timeout=timeout,
        )
        return _payload_eventos(response)

    def fechar(self) -> None:
        try:
            self.http.close()
        finally:
            self.pfx_path.unlink(missing_ok=True)

    def __enter__(self) -> "SessaoCertificado":
        return self

    def __exit__(self, *_exc) -> None:
        self.fechar()


def _payload_eventos(response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise EventosSyncError(f"ADN respondeu HTTP {response.status_code} sem JSON.") from exc
    # O ADN usa 404 tambem para "nenhum documento" (E2220); nao e falha.
    if response.status_code not in {200, 404}:
        detalhe = payload.get("Erros") if isinstance(payload, dict) else None
        raise EventosSyncError(f"ADN respondeu HTTP {response.status_code}: {detalhe or ''}".strip())
    return payload if isinstance(payload, dict) else {}


def consultar_eventos_adn(
    *,
    chave: str,
    cnpj: str,
    ambiente: str,
    pfx_path: str,
    pfx_password: str,
    timeout: int = 120,
) -> dict[str, Any]:
    base = _base_adn(ambiente)
    response = requests_pkcs12.get(
        f"{base}/NFSe/{chave}/Eventos",
        params={"cnpjConsulta": cnpj},
        headers=_HEADERS,
        pkcs12_filename=pfx_path,
        pkcs12_password=pfx_password,
        timeout=timeout,
        verify=True,
    )
    return _payload_eventos(response)


def sincronizar_eventos_nota(
    db: Session,
    storage: StorageService,
    nota: Nota,
    sessao: SessaoCertificado | None = None,
) -> dict[str, Any]:
    empresa = db.get(Empresa, int(nota.empresa_id))
    if empresa is None:
        raise EventosSyncError("Empresa da nota nao encontrada.")
    if sessao is not None:
        return aplicar_eventos_payload(db, storage, nota, empresa, sessao.consultar(str(nota.chave)))
    certificado = _certificado_da_empresa(db, int(empresa.id))
    senha = secrets_service.get_secret_value(db, str(certificado.senha_secret_ref))
    pfx_bytes = storage.get_bytes(certificado.storage_key)
    cnpj = re.sub(r"\D", "", str(empresa.cnpj or ""))

    temp_dir = Path(settings.worker_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    pfx_path = temp_dir / f"eventos_cert_{certificado.id}_{uuid.uuid4().hex}.pfx"
    try:
        pfx_path.write_bytes(pfx_bytes)
        payload = consultar_eventos_adn(
            chave=str(nota.chave),
            cnpj=cnpj,
            ambiente=str(empresa.ambiente or "producao"),
            pfx_path=str(pfx_path),
            pfx_password=senha,
        )
    finally:
        senha = ""
        pfx_path.unlink(missing_ok=True)

    return aplicar_eventos_payload(db, storage, nota, empresa, payload)


def aplicar_eventos_payload(
    db: Session,
    storage: StorageService,
    nota: Nota,
    empresa: Empresa,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Aplica na nota os documentos de evento retornados pelo ADN."""
    # _registrar_evento_xml e _regenerar_pdf_espelho_evento foram escritos para
    # o contexto de um processo de consulta; aqui nao ha processo, entao passa
    # um objeto com os mesmos atributos que elas leem.
    contexto = SimpleNamespace(id=None, empresa_id=int(empresa.id), empresa=empresa)
    resultado: dict[str, Any] = {
        "nota_id": int(nota.id),
        "chave": str(nota.chave),
        "status_anterior": nota.status_documento,
        "status_processamento": payload.get("StatusProcessamento"),
        "documentos": 0,
        # O endpoint devolve a propria NFS-e como primeiro documento e, depois,
        # os eventos. Contar a nota a parte evita que "ignorados" pareca erro.
        "nota_retornada": 0,
        "eventos_aplicados": 0,
        "eventos_ignorados": 0,
        "pdf_regenerado": False,
        "erros": [],
    }
    lote = payload.get("LoteDFe") or []
    resultado["documentos"] = len(lote)
    status_final: str | None = None
    for doc in lote:
        try:
            arquivo_xml = doc.get("ArquivoXml")
            if not arquivo_xml:
                resultado["eventos_ignorados"] += 1
                continue
            xml_bytes = gzip.decompress(base64.b64decode(arquivo_xml))
            resumo = legacy_ingestion_service.parse_xml_resumo_bytes(xml_bytes, "evento.xml")
            if resumo.get("tipo_xml") != "evento":
                if str(doc.get("TipoDocumento") or "").upper() == "NFSE":
                    resultado["nota_retornada"] += 1
                else:
                    resultado["eventos_ignorados"] += 1
                continue
            nsu_raw = str(doc.get("NSU") or "").strip()
            nsu = int(nsu_raw) if nsu_raw.isdigit() else None
            chave_evento = (
                str(resumo.get("chave") or doc.get("ChaveAcesso") or "").strip()
                or f"evento_{uuid.uuid4().hex[:12]}"
            )
            competencia = nota.competencia or nota.data_emissao
            ano = f"{competencia.year:04d}" if competencia else "0000"
            mes = f"{competencia.month:02d}" if competencia else "00"
            nome_xml = f"{chave_evento}_evento.xml"
            xml_storage_key = build_xml_key(str(empresa.cnpj), ano, mes, nome_xml)
            if not storage.exists(xml_storage_key):
                storage.put_bytes(xml_storage_key, xml_bytes, content_type="application/xml")
            legacy_ingestion_service._registrar_arquivo(
                db,
                storage,
                int(empresa.id),
                None,
                int(nota.id),
                "xml",
                xml_storage_key,
                "application/xml",
                len(xml_bytes),
                hashlib.sha256(xml_bytes).hexdigest(),
                nome_xml,
            )
            # Garante que o evento aponte para esta nota mesmo que o XML nao
            # traga a chave afetada em um campo reconhecido pelo parser.
            if not resumo.get("chave_afetada"):
                resumo["chave_afetada"] = str(nota.chave)
            legacy_ingestion_service._registrar_evento_xml(db, contexto, resumo, xml_storage_key, nsu)
            status = str(resumo.get("status_documento") or "").strip().lower()
            if status in {"cancelada", "substituida"}:
                status_final = status
            resultado["eventos_aplicados"] += 1
        except Exception as exc:  # um evento invalido nao pode impedir os demais
            resultado["erros"].append(str(exc)[:300])
    if status_final and nota.xml_storage_key:
        # O status e a verdade fiscal; o espelho e derivado e pode ser refeito
        # depois (regenerar_carimbos_pdfs). Uma falha no PHP nao pode
        # descartar, no rollback, o cancelamento que o ADN acabou de informar.
        try:
            legacy_ingestion_service._regenerar_pdf_espelho_evento(db, storage, contexto, nota, status_final)
            resultado["pdf_regenerado"] = True
        except Exception as exc:
            resultado["erros"].append(f"pdf_espelho: {str(exc)[:300]}")
    db.commit()
    db.refresh(nota)
    resultado["status_atual"] = nota.status_documento
    return resultado
