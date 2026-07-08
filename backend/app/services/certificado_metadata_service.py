from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID


class CertificadoMetadataError(ValueError):
    pass


@dataclass
class CertificadoMetadata:
    cnpj: str | None
    nome: str | None
    subject_cn: str | None
    thumbprint: str | None
    valido_de: datetime | None
    valido_ate: datetime | None


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _extract_cnpj(*values: str | None) -> str | None:
    for value in values:
        digits = _digits(value or "")
        for index in range(0, max(len(digits) - 13, 0)):
            candidate = digits[index : index + 14]
            if len(candidate) == 14:
                return candidate
    return None


def _first_attr(cert, oid) -> str | None:
    attrs = cert.subject.get_attributes_for_oid(oid)
    if not attrs:
        return None
    value = attrs[0].value.strip()
    return value or None


def _looks_like_authority_name(value: str | None) -> bool:
    normalized = (value or "").strip().lower()
    return normalized in {"icp-brasil", "icp brasil"}


def _extract_business_name(subject_cn: str | None, organization: str | None) -> str | None:
    if subject_cn:
        name = re.split(r"[:|]", subject_cn, maxsplit=1)[0].strip()
        if name and not _looks_like_authority_name(name):
            return name
    if organization and not _looks_like_authority_name(organization):
        return organization
    return subject_cn or organization


def extrair_metadata_pfx(pfx_bytes: bytes, senha: str) -> CertificadoMetadata:
    try:
        _, cert, _ = pkcs12.load_key_and_certificates(
            pfx_bytes,
            (senha or "").encode("utf-8"),
        )
    except Exception as exc:
        raise CertificadoMetadataError("Senha invalida ou certificado invalido.") from exc

    if cert is None:
        raise CertificadoMetadataError("Certificado invalido.")

    subject_cn = _first_attr(cert, NameOID.COMMON_NAME)
    organization = _first_attr(cert, NameOID.ORGANIZATION_NAME)
    subject_text = cert.subject.rfc4514_string()
    cnpj = _extract_cnpj(subject_cn, organization, subject_text)
    nome = _extract_business_name(subject_cn, organization)
    thumbprint = cert.fingerprint(hashes.SHA1()).hex().upper()
    valido_de = getattr(cert, "not_valid_before_utc", cert.not_valid_before)
    valido_ate = getattr(cert, "not_valid_after_utc", cert.not_valid_after)

    return CertificadoMetadata(
        cnpj=cnpj,
        nome=nome,
        subject_cn=subject_cn,
        thumbprint=thumbprint,
        valido_de=valido_de,
        valido_ate=valido_ate,
    )
