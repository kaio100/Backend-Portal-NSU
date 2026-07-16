from __future__ import annotations

import re
import unicodedata
from io import BytesIO

from pypdf import PdfReader


STATUS_ROTULOS = {
    "cancelada": "Cancelada",
    "substituida": "Substituida",
}


def _sem_acentos(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def detectar_status_pdf_oficial(pdf_bytes: bytes) -> str | None:
    """Detecta o carimbo vetorial CANCELADA/SUBSTITUIDA do DANFSe oficial."""
    if not pdf_bytes.startswith(b"%PDF"):
        return None

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        streams = []
        extracted_lines = []
        for page in reader.pages:
            extracted_lines.extend((page.extract_text() or "").splitlines())
            contents = page.get_contents()
            if contents is not None:
                # PDFs oficiais atuais usam texto Latin-1 no content stream;
                # outros geradores podem usar escapes PDF, cobertos acima por
                # extract_text().
                streams.append(contents.get_data().decode("latin-1", errors="ignore"))
    except Exception:
        return None

    linhas = {_sem_acentos(line).strip().upper() for line in extracted_lines}
    if "SUBSTITUIDA" in linhas:
        return "substituida"
    if "CANCELADA" in linhas:
        return "cancelada"

    raw = _sem_acentos("\n".join(streams)).upper()
    # O PDFsharp grava a marca d'agua como uma string isolada desenhada com
    # Tj. Exigir esse formato evita confundir palavras na descricao do servico.
    if re.search(r"\(\s*SUBSTITUIDA\s*\)\s*T[Jj]", raw):
        return "substituida"
    if re.search(r"\(\s*CANCELADA\s*\)\s*T[Jj]", raw):
        return "cancelada"
    return None


def aplicar_status_pdf_oficial(nota, pdf_bytes: bytes) -> str | None:
    status = detectar_status_pdf_oficial(pdf_bytes)
    if status is None:
        return None

    rotulo = STATUS_ROTULOS[status]
    nota.status_documento = status
    nota.status_rotulo = rotulo
    if not nota.conferencia_observacao:
        nota.conferencia_observacao = (
            f"Nota {rotulo.lower()}, conforme carimbo identificado automaticamente no PDF oficial."
        )
    return status
