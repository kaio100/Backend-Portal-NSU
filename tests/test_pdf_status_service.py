from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from reportlab.pdfgen import canvas

from backend.app.services.pdf_status_service import aplicar_status_pdf_oficial, detectar_status_pdf_oficial


def _pdf_com_carimbo(texto: str | None) -> bytes:
    output = BytesIO()
    pdf = canvas.Canvas(output)
    pdf.drawString(30, 800, "Documento Auxiliar da NFS-e")
    if texto:
        pdf.saveState()
        pdf.translate(160, 180)
        pdf.rotate(45)
        pdf.setFont("Helvetica", 72)
        pdf.drawString(0, 0, texto)
        pdf.restoreState()
    pdf.save()
    return output.getvalue()


def test_detecta_carimbos_de_status_no_pdf_oficial():
    assert detectar_status_pdf_oficial(_pdf_com_carimbo("SUBSTITUÍDA")) == "substituida"
    assert detectar_status_pdf_oficial(_pdf_com_carimbo("CANCELADA")) == "cancelada"
    assert detectar_status_pdf_oficial(_pdf_com_carimbo(None)) is None


def test_status_do_pdf_prevalece_e_preenche_observacao():
    nota = SimpleNamespace(
        status_documento="autorizada",
        status_rotulo="Autorizada",
        conferencia_observacao=None,
    )
    status = aplicar_status_pdf_oficial(nota, _pdf_com_carimbo("CANCELADA"))
    assert status == "cancelada"
    assert nota.status_documento == "cancelada"
    assert nota.status_rotulo == "Cancelada"
    assert "pdf oficial" in nota.conferencia_observacao.lower()
