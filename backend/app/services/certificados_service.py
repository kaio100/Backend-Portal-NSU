from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Certificado
from backend.app.repositories import certificados_repo, empresas_repo
from backend.app.schemas.consultas import ConsultaIniciarRequest
from backend.app.services import certificado_metadata_service, consultas_service, secrets_service
from backend.app.services.certificado_metadata_service import CertificadoMetadataError
from backend.app.services.storage_service import (
    StorageService,
    build_certificado_key,
    normalize_storage_key,
)


class CertificadoServiceError(ValueError):
    pass


logger = logging.getLogger(__name__)


def _sanitize_filename(filename: str) -> str:
    name = Path((filename or "").replace("\\", "/")).name.strip()
    if not name:
        raise CertificadoServiceError("Nome do arquivo PFX e obrigatorio.")
    suffix = Path(name).suffix.lower()
    if suffix not in {".pfx", ".p12"}:
        raise CertificadoServiceError("Arquivo deve ter extensao .pfx ou .p12.")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return normalize_storage_key(safe)


def _normalizar_ambiente(value: str) -> str:
    ambiente = (value or "producao").lower().strip()
    if ambiente in {"homologacao", "homologação"}:
        return "homologacao"
    if ambiente in {"restrita", "producao_restrita", "produção_restrita"}:
        return "restrita"
    if ambiente == "producao":
        return "producao"
    raise CertificadoServiceError("Ambiente deve ser 'producao' ou 'homologacao'.")


def _cnpj_from_text(value: str) -> str:
    for match in re.findall(r"\d{14}", value or ""):
        return match
    return ""


def testar_certificado_pfx_bytes(pfx_bytes: bytes, senha: str) -> dict[str, Any]:
    try:
        import adn_nfse_downloader as legacy

        if legacy.pkcs12 is None:
            return {"ok": False, "erro": "Dependencia cryptography indisponivel."}

        _, cert, _ = legacy.pkcs12.load_key_and_certificates(
            pfx_bytes,
            (senha or "").encode("utf-8"),
            backend=legacy.default_backend(),
        )
        if cert is None:
            return {"ok": False, "erro": "Certificado invalido."}

        subject_cn = ""
        attrs = cert.subject.get_attributes_for_oid(legacy.NameOID.COMMON_NAME)
        if attrs:
            subject_cn = attrs[0].value

        subject_text = cert.subject.rfc4514_string()
        thumbprint = cert.fingerprint(hashes.SHA1()).hex().upper()
        valido_de = getattr(cert, "not_valid_before_utc", cert.not_valid_before)
        valido_ate = getattr(cert, "not_valid_after_utc", cert.not_valid_after)

        return {
            "ok": True,
            "subject_cn": subject_cn,
            "thumbprint": thumbprint,
            "valido_de": valido_de,
            "valido_ate": valido_ate,
            "cnpj_detectado": _cnpj_from_text(f"{subject_cn} {subject_text}"),
        }
    except Exception as exc:
        logger.warning("Falha ao validar PFX/P12 enviado: %s", exc)
        return {"ok": False, "erro": "Senha invalida ou certificado invalido."}


def criar_certificado_com_upload(
    db: Session,
    storage: StorageService,
    empresa_id: int,
    nome: str,
    filename: str,
    pfx_bytes: bytes,
    senha_teste: str | None = None,
) -> Certificado:
    empresa = empresas_repo.get_empresa(db, empresa_id)
    if empresa is None:
        raise CertificadoServiceError("Empresa nao encontrada.")
    if not pfx_bytes:
        raise CertificadoServiceError("Arquivo PFX vazio.")

    safe_filename = _sanitize_filename(filename)
    test_result = testar_certificado_pfx_bytes(pfx_bytes, senha_teste) if senha_teste else {}

    certificado = certificados_repo.create_certificado(
        db,
        {
            "empresa_id": empresa.id,
            "nome": nome or safe_filename,
            "storage_key": "pending",
            "senha_secret_ref": None,
            "thumbprint": test_result.get("thumbprint") if test_result.get("ok") else None,
            "subject_cn": test_result.get("subject_cn") if test_result.get("ok") else None,
            "valido_de": test_result.get("valido_de") if test_result.get("ok") else None,
            "valido_ate": test_result.get("valido_ate") if test_result.get("ok") else None,
            "ativo": True,
        },
    )

    storage_key = build_certificado_key(empresa.cnpj, str(certificado.id), safe_filename)
    storage.put_bytes(storage_key, pfx_bytes, content_type="application/x-pkcs12")
    return certificados_repo.update_certificado(db, certificado, {"storage_key": storage_key})


def criar_certificado_com_upload_e_senha(
    db: Session,
    storage: StorageService,
    empresa_id: int,
    nome: str,
    filename: str,
    pfx_bytes: bytes,
    senha: str,
    ativo: bool = True,
) -> Certificado:
    empresa = empresas_repo.get_empresa(db, empresa_id)
    if empresa is None:
        raise CertificadoServiceError("Empresa nao encontrada.")
    if not empresa.ativo:
        raise CertificadoServiceError("Empresa inativa.")
    if not pfx_bytes:
        raise CertificadoServiceError("Arquivo PFX e obrigatorio.")
    if not senha:
        raise CertificadoServiceError("Senha do certificado e obrigatoria.")

    safe_filename = _sanitize_filename(filename)
    test_result = testar_certificado_pfx_bytes(pfx_bytes, senha)
    if not test_result.get("ok"):
        raise CertificadoServiceError("Senha invalida ou certificado invalido.")

    certificado = Certificado(
        empresa_id=empresa.id,
        nome=nome or safe_filename,
        storage_key="pending",
        senha_secret_ref=None,
        thumbprint=test_result.get("thumbprint"),
        subject_cn=test_result.get("subject_cn"),
        valido_de=test_result.get("valido_de"),
        valido_ate=test_result.get("valido_ate"),
        ativo=ativo,
    )

    try:
        db.add(certificado)
        db.flush()

        storage_key = build_certificado_key(empresa.cnpj, str(certificado.id), safe_filename)
        storage.put_bytes(storage_key, pfx_bytes, content_type="application/x-pkcs12")

        ref = secrets_service.build_certificado_senha_ref(certificado.id)
        secrets_service.save_secret(db, ref, "pfx_password", senha)
        certificado.storage_key = storage_key
        certificado.senha_secret_ref = ref
        db.add(certificado)
        db.commit()
        db.refresh(certificado)
        return certificado
    except secrets_service.SecretsServiceError as exc:
        db.rollback()
        raise CertificadoServiceError(str(exc)) from exc
    except Exception:
        db.rollback()
        raise


def autocadastrar_certificado(
    db: Session,
    storage: StorageService,
    filename: str,
    pfx_bytes: bytes,
    senha: str,
    ambiente: str = "producao",
    auto_iniciar: bool = True,
    limite: int | None = None,
    nsu_inicio: int | None = None,
    forcar: bool = False,
) -> dict[str, Any]:
    if not pfx_bytes:
        raise CertificadoServiceError("Arquivo PFX/P12 e obrigatorio.")
    if not senha:
        raise CertificadoServiceError("Senha do certificado e obrigatoria.")
    if nsu_inicio is not None and int(nsu_inicio) < 0:
        raise CertificadoServiceError("nsu_inicio nao pode ser negativo.")

    safe_filename = _sanitize_filename(filename)
    ambiente_normalizado = _normalizar_ambiente(ambiente)
    logger.info("Certificado recebido para autocadastro: filename=%s size=%s", safe_filename, len(pfx_bytes))

    try:
        metadata = certificado_metadata_service.extrair_metadata_pfx(pfx_bytes, senha)
    except CertificadoMetadataError as exc:
        logger.warning("Erro de senha/certificado invalido no autocadastro: %s", exc)
        raise CertificadoServiceError(str(exc)) from exc

    if not metadata.cnpj:
        logger.warning("Autocadastro sem CNPJ detectavel: subject_cn=%s", metadata.subject_cn)
        raise CertificadoServiceError(
            "Nao foi possivel identificar o CNPJ no certificado. Cadastre a empresa manualmente ou use outro certificado."
        )

    logger.info("CNPJ extraido do certificado: %s", metadata.cnpj)
    empresa = empresas_repo.get_empresa_by_cnpj(db, metadata.cnpj)
    empresa_existente = empresa is not None
    if empresa is None:
        empresa = empresas_repo.create_empresa(
            db,
            {
                "nome": metadata.nome or metadata.subject_cn or f"Empresa {metadata.cnpj}",
                "cnpj": metadata.cnpj,
                "ambiente": ambiente_normalizado,
                "ativo": True,
            },
        )
        logger.info("Empresa criada automaticamente: empresa_id=%s cnpj=%s", empresa.id, empresa.cnpj)
    else:
        updates: dict[str, Any] = {}
        if not empresa.nome and (metadata.nome or metadata.subject_cn):
            updates["nome"] = metadata.nome or metadata.subject_cn
        if not empresa.ambiente:
            updates["ambiente"] = ambiente_normalizado
        if not empresa.ativo:
            updates["ativo"] = True
        if updates:
            empresa = empresas_repo.update_empresa(db, empresa, updates)
        logger.info("Empresa reutilizada no autocadastro: empresa_id=%s cnpj=%s", empresa.id, empresa.cnpj)

    certificado = None
    if metadata.thumbprint:
        certificado = (
            db.query(Certificado)
            .filter(Certificado.empresa_id == empresa.id)
            .filter(Certificado.thumbprint == metadata.thumbprint)
            .filter(Certificado.ativo.is_(True))
            .order_by(Certificado.id.desc())
            .first()
        )

    certificado_existente = certificado is not None
    if certificado is None:
        certificado = Certificado(
            empresa_id=empresa.id,
            nome=metadata.nome or metadata.subject_cn or safe_filename,
            storage_key="pending",
            senha_secret_ref=None,
            thumbprint=metadata.thumbprint,
            subject_cn=metadata.subject_cn,
            valido_de=metadata.valido_de,
            valido_ate=metadata.valido_ate,
            ativo=True,
        )
        db.add(certificado)

    try:
        db.flush()
        storage_key = build_certificado_key(empresa.cnpj, str(certificado.id), safe_filename)
        storage.put_bytes(storage_key, pfx_bytes, content_type="application/x-pkcs12")
        ref = secrets_service.build_certificado_senha_ref(certificado.id)
        secrets_service.save_secret(db, ref, "pfx_password", senha)
        certificado.nome = metadata.nome or metadata.subject_cn or certificado.nome or safe_filename
        certificado.storage_key = storage_key
        certificado.senha_secret_ref = ref
        certificado.thumbprint = metadata.thumbprint
        certificado.subject_cn = metadata.subject_cn
        certificado.valido_de = metadata.valido_de
        certificado.valido_ate = metadata.valido_ate
        certificado.ativo = True
        db.add(certificado)
        db.commit()
        db.refresh(certificado)
        if certificado_existente:
            logger.info("Certificado ativo atualizado por thumbprint: certificado_id=%s empresa_id=%s", certificado.id, empresa.id)
        else:
            logger.info("Certificado salvo no autocadastro: certificado_id=%s empresa_id=%s", certificado.id, empresa.id)
    except secrets_service.SecretsServiceError as exc:
        db.rollback()
        raise CertificadoServiceError(str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    processo = None
    if auto_iniciar:
        nsu_inicio_efetivo = int(nsu_inicio) if empresa_existente and nsu_inicio is not None else None
        options = ConsultaIniciarRequest(
            automatico=True,
            intervalo_minutos=15,
            empresa_ids=[int(empresa.id)],
            certificado_ids=[int(certificado.id)],
            nsu_inicio=nsu_inicio_efetivo,
            limite=limite or settings.consultas_default_limite,
            pausa=settings.consultas_default_pausa,
            forcar=forcar,
        )
        result = consultas_service.iniciar_consultas_automaticas(db, options=options)
        processo = (result.get("processos_criados") or [None])[0]
        if processo is None:
            logger.info("Job ignorado no autocadastro: ja existe pendente/rodando para certificado_id=%s", certificado.id)
        else:
            logger.info("Job criado no autocadastro: processo_id=%s certificado_id=%s", processo.id, certificado.id)

    return {
        "empresa": empresa,
        "certificado": certificado,
        "processo": processo,
        "consulta_status": consultas_service.montar_status(db),
    }


def atualizar_certificado_com_upload_ou_senha(
    db: Session,
    storage: StorageService,
    certificado_id: int,
    nome: str | None = None,
    filename: str | None = None,
    pfx_bytes: bytes | None = None,
    senha: str | None = None,
    ativo: bool | None = None,
) -> Certificado:
    certificado = obter_certificado(db, certificado_id)
    empresa = empresas_repo.get_empresa(db, certificado.empresa_id)
    if empresa is None:
        raise CertificadoServiceError("Empresa nao encontrada.")

    has_new_pfx = pfx_bytes is not None and len(pfx_bytes) > 0
    has_new_senha = senha is not None and senha != ""
    if has_new_pfx and not has_new_senha:
        raise CertificadoServiceError("Nova senha e obrigatoria ao substituir o PFX.")

    test_result: dict[str, Any] = {}
    storage_key = certificado.storage_key
    if has_new_pfx:
        safe_filename = _sanitize_filename(filename or "")
        test_result = testar_certificado_pfx_bytes(pfx_bytes or b"", senha or "")
        if not test_result.get("ok"):
            raise CertificadoServiceError("Senha invalida ou certificado invalido.")
        storage_key = build_certificado_key(empresa.cnpj, str(certificado.id), safe_filename)
        storage.put_bytes(storage_key, pfx_bytes or b"", content_type="application/x-pkcs12")
    elif has_new_senha:
        pfx_bytes_current = storage.get_bytes(certificado.storage_key)
        test_result = testar_certificado_pfx_bytes(pfx_bytes_current, senha or "")
        if not test_result.get("ok"):
            raise CertificadoServiceError("Senha invalida ou certificado invalido.")

    try:
        if nome is not None and nome.strip():
            certificado.nome = nome.strip()
        if ativo is not None:
            certificado.ativo = ativo
        if has_new_pfx:
            certificado.storage_key = storage_key
            certificado.thumbprint = test_result.get("thumbprint")
            certificado.subject_cn = test_result.get("subject_cn")
            certificado.valido_de = test_result.get("valido_de")
            certificado.valido_ate = test_result.get("valido_ate")
        if has_new_senha:
            ref = secrets_service.build_certificado_senha_ref(certificado.id)
            secrets_service.save_secret(db, ref, "pfx_password", senha or "")
            certificado.senha_secret_ref = ref

        db.add(certificado)
        db.commit()
        db.refresh(certificado)
        return certificado
    except secrets_service.SecretsServiceError as exc:
        db.rollback()
        raise CertificadoServiceError(str(exc)) from exc
    except Exception:
        db.rollback()
        raise


def listar_certificados(
    db: Session,
    empresa_id: int | None = None,
    ativo: bool | None = None,
) -> list[Certificado]:
    return certificados_repo.list_certificados(db, empresa_id=empresa_id, ativo=ativo)


def obter_certificado(db: Session, certificado_id: int) -> Certificado:
    certificado = certificados_repo.get_certificado(db, certificado_id)
    if certificado is None:
        raise CertificadoServiceError("Certificado nao encontrado.")
    return certificado


def testar_certificado_salvo(
    db: Session,
    storage: StorageService,
    certificado_id: int,
    senha: str,
) -> dict[str, Any]:
    certificado = obter_certificado(db, certificado_id)
    pfx_bytes = storage.get_bytes(certificado.storage_key)
    return testar_certificado_pfx_bytes(pfx_bytes, senha)


def desativar_certificado(db: Session, certificado_id: int) -> Certificado:
    certificado = obter_certificado(db, certificado_id)
    return certificados_repo.deactivate_certificado(db, certificado)


def salvar_senha_certificado(
    db: Session,
    storage: StorageService,
    certificado_id: int,
    senha: str,
    testar_antes: bool = True,
) -> dict[str, Any]:
    certificado = obter_certificado(db, certificado_id)
    if testar_antes:
        pfx_bytes = storage.get_bytes(certificado.storage_key)
        resultado = testar_certificado_pfx_bytes(pfx_bytes, senha)
        if not resultado.get("ok"):
            raise CertificadoServiceError("Senha invalida ou certificado invalido.")

    ref = secrets_service.build_certificado_senha_ref(certificado.id)
    try:
        secrets_service.save_secret(db, ref, "pfx_password", senha)
        certificados_repo.update_certificado(db, certificado, {"senha_secret_ref": ref})
        db.commit()
        db.refresh(certificado)
    except secrets_service.SecretsServiceError as exc:
        db.rollback()
        raise CertificadoServiceError(str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    return {"certificado_id": certificado.id, "senha_configurada": True}


def status_senha_certificado(db: Session, certificado_id: int) -> dict[str, Any]:
    certificado = obter_certificado(db, certificado_id)
    return {
        "certificado_id": certificado.id,
        "senha_configurada": bool(certificado.senha_secret_ref),
    }


def remover_senha_certificado(db: Session, certificado_id: int) -> dict[str, Any]:
    certificado = obter_certificado(db, certificado_id)
    ref = certificado.senha_secret_ref or secrets_service.build_certificado_senha_ref(certificado.id)
    try:
        secrets_service.delete_secret(db, ref)
        certificados_repo.update_certificado(db, certificado, {"senha_secret_ref": None})
        db.commit()
        db.refresh(certificado)
    except Exception:
        db.rollback()
        raise

    return {"certificado_id": certificado.id, "senha_configurada": False}


def testar_certificado_com_senha_salva(
    db: Session,
    storage: StorageService,
    certificado_id: int,
) -> dict[str, Any]:
    certificado = obter_certificado(db, certificado_id)
    if not certificado.senha_secret_ref:
        raise CertificadoServiceError("Senha do certificado nao configurada.")
    try:
        senha = secrets_service.get_secret_value(db, certificado.senha_secret_ref)
    except secrets_service.SecretsServiceError as exc:
        raise CertificadoServiceError(str(exc)) from exc

    pfx_bytes = storage.get_bytes(certificado.storage_key)
    return testar_certificado_pfx_bytes(pfx_bytes, senha)
