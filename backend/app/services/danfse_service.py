from __future__ import annotations

import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from backend.app.core.config import settings
from backend.app.core.observability import alert_failure, metrics


class DanfseError(RuntimeError):
    pass


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _numero_nfse(xml_content: bytes) -> str:
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        raise DanfseError("XML invalido ou malformado.") from exc

    if _local_name(root.tag) not in {"nfse", "nfs-e"}:
        raise DanfseError("XML incompativel: documento nao e uma NFS-e Nacional.")

    for element in root.iter():
        if _local_name(element.tag) == "nnfse" and (element.text or "").strip():
            return re.sub(r"[^A-Za-z0-9_-]", "", element.text.strip())[:80] or "documento"
    return "documento"


def friendly_pdf_filename(dados: dict) -> str:
    prestador = str(dados.get("emit_nome") or dados.get("prestador_nome") or "NFS-e")
    numero = str(dados.get("numero_nfse") or "-")
    clean = lambda value: re.sub(r"\s+", "_", re.sub(r'[<>:"/\\|?*]+', "", value).strip())[:180] or "NFS-e"
    return f"{clean(prestador)} NFS-e {clean(numero)}.pdf"


class DanfseService:
    """Single runtime entry point for national DANFSe mirror PDFs."""

    def __init__(self) -> None:
        self.root = Path(settings.danfse_library_root).resolve()
        self.php_binary = str(settings.danfse_php_binary or "php")
        self.max_xml_bytes = max(1, int(settings.danfse_xml_max_bytes))
        self.bridge = self.root / "generate.php"

    def generate(self, xml_content: bytes, watermark: str | None = None) -> tuple[bytes, str]:
        if not xml_content:
            raise DanfseError("Arquivo XML vazio.")
        if len(xml_content) > self.max_xml_bytes:
            raise DanfseError("Arquivo XML excede o limite permitido.")
        numero = _numero_nfse(xml_content)
        if not self.bridge.is_file():
            raise DanfseError("Servico DANFSe Nacional nao configurado.")

        temp_root = Path(settings.worker_temp_dir)
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="danfse_", dir=temp_root) as temp_dir:
            base = Path(temp_dir).resolve()
            xml_path = base / "entrada.xml"
            pdf_path = base / f"DANFSe-{numero}.pdf"
            xml_path.write_bytes(xml_content)
            env = os.environ.copy()
            env["COMPOSER_HOME"] = str(base / "composer")
            try:
                command = [self.php_binary, str(self.bridge), str(xml_path), str(pdf_path)]
                if watermark in {"cancelada", "substituida"}:
                    command.append(watermark)
                completed = subprocess.run(
                    command,
                    cwd=str(self.root),
                    env=env,
                    capture_output=True,
                    timeout=max(10, int(settings.danfse_timeout_seconds)),
                    check=False,
                    text=True,
                )
            except FileNotFoundError as exc:
                alert_failure("danfse_generation", exc, numero_nfse=numero)
                raise DanfseError("PHP nao encontrado no ambiente do backend.") from exc
            except subprocess.TimeoutExpired as exc:
                alert_failure("danfse_generation", exc, numero_nfse=numero)
                raise DanfseError("Tempo limite excedido na geracao do DANFSe.") from exc

            if completed.returncode != 0:
                detail = (completed.stderr or "").strip().splitlines()
                message = detail[-1] if detail else "Falha na biblioteca DANFSe Nacional."
                alert_failure("danfse_generation", message, numero_nfse=numero)
                raise DanfseError(message[:300])
            if not pdf_path.is_file():
                alert_failure("danfse_generation", "PDF ausente", numero_nfse=numero)
                raise DanfseError("A biblioteca nao produziu um PDF valido.")
            pdf_bytes = pdf_path.read_bytes()
            if not pdf_bytes.startswith(b"%PDF"):
                alert_failure("danfse_generation", "PDF invalido", numero_nfse=numero)
                raise DanfseError("A biblioteca nao produziu um PDF valido.")
            metrics.inc("danfse_generated")
            return pdf_bytes, f"DANFSe-{numero}.pdf"
