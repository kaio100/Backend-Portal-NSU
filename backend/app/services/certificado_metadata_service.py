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


def cnpj_valido(value: str) -> bool:
    digits = _digits(value)
    if len(digits) != 14 or digits == digits[0] * 14:
        return False

    def digito(base: str, pesos: list[int]) -> str:
        total = sum(int(numero) * peso for numero, peso in zip(base, pesos))
        resto = total % 11
        return str(0 if resto < 2 else 11 - resto)

    primeiro = digito(digits[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    segundo = digito(digits[:12] + primeiro, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return digits[-2:] == primeiro + segundo


def extrair_cnpj_texto(*values: str | None) -> str | None:
    for value in values:
        texto = value or ""
        candidatos = re.findall(r"(?<!\d)\d{14}(?!\d)", texto)
        candidatos.extend(
            match.group(0)
            for match in re.finditer(r"\d{2}\D?\d{3}\D?\d{3}\D?\d{4}\D?\d{2}", texto)
        )
        for candidate in candidatos:
            digits = _digits(candidate)
            if cnpj_valido(digits):
                return digits

    # Compatibilidade com subjects sem separador: avalia todas as janelas,
    # mas nunca aceita apenas os primeiros 14 algarismos concatenados.
    for value in values:
        digits = _digits(value or "")
        for index in range(0, max(len(digits) - 13, 0)):
            candidate = digits[index : index + 14]
            if cnpj_valido(candidate):
                return candidate
    return None


def _extract_cnpj(*values: str | None) -> str | None:
    return extrair_cnpj_texto(*values)


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
