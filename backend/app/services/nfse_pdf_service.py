from __future__ import annotations

import re
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle


PAGE_W, PAGE_H = A4
MARGIN_X = 10 * mm
MARGIN_TOP = 10 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X
GRID_COLOR = colors.black
TITLE_BG = colors.HexColor("#d9d9d9")

VALUE_STYLE = ParagraphStyle("value", fontName="Helvetica", fontSize=7.4, leading=8.7)
CENTER_BOLD_STYLE = ParagraphStyle(
    "center_bold",
    fontName="Helvetica-Bold",
    fontSize=7.5,
    leading=9,
    alignment=1,
)


def _sanitize_filename(value: str) -> str:
    value = str(value or "NFS-e").strip()
    value = re.sub(r'[<>:"/\\|?*]+', "", value)
    value = re.sub(r"\s+", "_", value)
    return value[:180].strip("._-") or "NFS-e"


def friendly_pdf_filename(dados: dict) -> str:
    prestador = dados.get("emit_nome") or dados.get("prestador_nome") or "NFS-e"
    numero = dados.get("numero_nfse") or "-"
    return f"{_sanitize_filename(prestador)} NFS-e {_sanitize_filename(numero)}.pdf"


def _cell(label: str, value=None) -> Paragraph:
    value = "-" if value in (None, "") else str(value)
    text = f"<font size=6.1 name='Helvetica-Bold'>{label}</font><br/><font size=7.4>{value}</font>"
    return Paragraph(text, VALUE_STYLE)


def _blank() -> Paragraph:
    return Paragraph("", VALUE_STYLE)


def _parse_number(value) -> float | None:
    if value in (None, "", "-"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text == "-":
        return None
    text = re.sub(r"[^0-9,.-]", "", text)
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _fmt_br_number(value) -> str | None:
    number = _parse_number(value)
    if number is None:
        return None
    return f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_money(value) -> str:
    if value in (None, "", "-"):
        return "-"
    formatted = _fmt_br_number(value)
    if formatted is None:
        text = str(value).strip()
        return text if text.startswith("R$") else f"R$ {text}"
    return f"R$ {formatted}"


def _fmt_percent(value, spaced: bool = False) -> str:
    if value in (None, "", "-"):
        return "-"
    suffix = " %" if spaced else "%"
    formatted = _fmt_br_number(value)
    if formatted is None:
        text = str(value).strip()
        return text if "%" in text else f"{text}{suffix}"
    return f"{formatted}{suffix}"


def _info_complementar(dados: dict) -> str:
    lines = []
    nbs = dados.get("nbs")
    if nbs not in (None, "", "-"):
        line = f"NBS: {nbs}"
        descricao_nbs = dados.get("descricao_nbs")
        if descricao_nbs not in (None, "", "-"):
            line = f"{line} - {descricao_nbs}"
        lines.append(line)
    info = dados.get("informacoes_complementares")
    if info not in (None, "", "-"):
        lines.append(str(info))
    if lines:
        return "<br/>".join(lines)
    return f"NFSe Subst: {dados.get('nfse_subst') or '-'}"


class NfsePdfService:
    def gerar_danfse_espelho(
        self,
        dados: dict,
        output_path: str | Path,
        storage_key_xml: str | None = None,
        checksum_xml: str | None = None,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        c = canvas.Canvas(str(output_path), pagesize=A4)
        y = PAGE_H - MARGIN_TOP

        y = self._draw_header(c, y, dados)
        y = self._draw_key_qr(c, y, dados)
        y -= 2
        y = self._draw_identificacao(c, y, dados)
        y = self._draw_emitente(c, y, dados)
        y = self._draw_tomador(c, y, dados)
        y = self._draw_center_line(c, y, dados.get("intermediario_texto", "INTERMEDIÁRIO DO SERVIÇO NÃO IDENTIFICADO NA NFS-e"))
        y = self._draw_servico(c, y, dados)
        y = self._draw_tributacao_municipal(c, y, dados)
        y = self._draw_tributacao_federal(c, y, dados)
        y = self._draw_valor_total(c, y, dados)
        y = self._draw_totais_aproximados(c, y, dados)
        self._draw_informacoes_complementares(c, y, dados)

        c.save()
        return output_path

    def _draw_header(self, c, y, dados):
        top = y
        c.setFont("Helvetica-Bold", 16)
        c.drawString(MARGIN_X, top - 6 * mm, "NFSe")
        c.setFont("Helvetica", 6)
        c.drawString(MARGIN_X, top - 9.5 * mm, "Nota Fiscal de")
        c.drawString(MARGIN_X, top - 11.5 * mm, "Serviço eletrônica")

        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(PAGE_W / 2, top - 6 * mm, "DANFSe v1.0")
        c.setFont("Helvetica", 9)
        c.drawCentredString(PAGE_W / 2, top - 10 * mm, "Documento Auxiliar da NFS-e")

        right_x = PAGE_W - MARGIN_X
        municipio = dados.get("municipio_prefeitura") or ""
        prefeitura = f"Prefeitura Municipal de {municipio}" if municipio else ""
        c.setFont("Helvetica-Bold", 7.5)
        c.drawRightString(right_x, top - 4 * mm, prefeitura)
        c.setFont("Helvetica", 6.5)
        c.drawRightString(right_x, top - 7 * mm, dados.get("orgao_prefeitura", ""))
        c.drawRightString(right_x, top - 9.5 * mm, dados.get("telefone_prefeitura", ""))
        c.drawRightString(right_x, top - 12 * mm, dados.get("email_prefeitura", ""))
        return top - 16 * mm

    def _draw_key_qr(self, c, y, dados):
        x = MARGIN_X
        w = CONTENT_W
        h = 18 * mm
        qr_w = 0.22 * w
        chave_w = w - qr_w
        c.setLineWidth(0.75)
        c.rect(x, y - h, w, h)
        c.line(x + chave_w, y - h, x + chave_w, y)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(x + 2, y - 4 * mm, "Chave de Acesso da NFS-e")
        c.setFont("Helvetica", 9.3)
        c.drawString(x + 2, y - 8 * mm, dados.get("chave_acesso", ""))
        self._draw_qr(c, x + chave_w + 2, y - h + 2, qr_w - 4, h - 4, dados)
        return y - h

    def _draw_qr(self, c, x, y, w, h, dados):
        size = min(w * 0.55, h)
        qr_content = dados.get("qr_conteudo") or f"https://www.nfse.gov.br/consultapublica?chave={dados.get('chave_acesso', '')}"
        widget = QrCodeWidget(qr_content)
        b = widget.getBounds()
        bw, bh = b[2] - b[0], b[3] - b[1]
        drawing = Drawing(size, size, transform=[size / bw, 0, 0, size / bh, 0, 0])
        drawing.add(widget)
        renderPDF.draw(drawing, c, x, y + (h - size) / 2)
        legenda = (
            "A autenticidade desta NFS-e pode ser verificada pela leitura deste código QR "
            "ou pela consulta da chave de acesso no portal nacional da NFS-e"
        )
        _wrap_text(c, legenda, x + size + 2, y + h - 3, w - size - 2, size=4.8, leading=5.4)

    def _draw_identificacao(self, c, y, dados):
        return self._draw_data_table(
            c,
            y,
            rows=[
                [(1, "Número da NFS-e", dados.get("numero_nfse")), (1, "Competência da NFS-e", dados.get("competencia")), (2, "Data e Hora da emissão da NFS-e", dados.get("data_emissao_nfse"))],
                [(1, "Número da DPS", dados.get("numero_dps")), (1, "Série da DPS", dados.get("serie_dps")), (2, "Data e Hora da emissão da DPS", dados.get("data_emissao_dps"))],
            ],
            col_fracs=(0.25, 0.25, 0.25, 0.25),
        )

    def _draw_emitente(self, c, y, dados):
        y = self._draw_section_title(c, y, "EMITENTE DA NFS-e")
        return self._draw_data_table(
            c,
            y,
            rows=[
                [(1, "Prestador do Serviço", ""), (1, "CNPJ / CPF / NIF", dados.get("emit_cnpj")), (1, "Inscrição Municipal", dados.get("emit_inscricao_municipal")), (1, "Telefone", dados.get("emit_telefone"))],
                [(2, "Nome / Nome Empresarial", dados.get("emit_nome")), (2, "E-mail", dados.get("emit_email"))],
                [(2, "Endereço", dados.get("emit_endereco")), (1, "Município", dados.get("emit_municipio")), (1, "CEP", dados.get("emit_cep"))],
                [(2, "Simples Nacional na Data de Competência", dados.get("emit_simples_nacional")), (2, "Regime de Apuração Tributária pelo SN", dados.get("emit_regime_apuracao"))],
            ],
            col_fracs=(0.25, 0.25, 0.25, 0.25),
        )

    def _draw_tomador(self, c, y, dados):
        if not dados.get("tomador_identificado"):
            return self._draw_center_line(c, y, "TOMADOR DO SERVIÇO NÃO IDENTIFICADO NA NFS-e")
        y = self._draw_section_title(c, y, "TOMADOR DO SERVIÇO")
        return self._draw_data_table(
            c,
            y,
            rows=[
                [(1, "CNPJ / CPF / NIF", dados.get("tom_cnpj")), (1, "Inscrição Municipal", dados.get("tom_inscricao_municipal")), (2, "Telefone", dados.get("tom_telefone"))],
                [(2, "Nome / Nome Empresarial", dados.get("tom_nome")), (2, "E-mail", dados.get("tom_email"))],
                [(2, "Endereço", dados.get("tom_endereco")), (2, "Município", dados.get("tom_municipio"))],
                [(4, "CEP", dados.get("tom_cep"))],
            ],
            col_fracs=(0.25, 0.25, 0.25, 0.25),
        )

    def _draw_servico(self, c, y, dados):
        y = self._draw_section_title(c, y, "SERVIÇO PRESTADO")
        return self._draw_data_table(
            c,
            y,
            rows=[
                [(1, "Código de Tributação Nacional", dados.get("codigo_tributacao_nacional")), (1, "Código de Tributação Municipal", dados.get("codigo_tributacao_municipal")), (1, "Local da Prestação", dados.get("local_prestacao")), (1, "País da Prestação", dados.get("pais_prestacao"))],
                [(4, "Descrição do Serviço", dados.get("descricao_servico"))],
            ],
            col_fracs=(0.34, 0.22, 0.22, 0.22),
        )

    def _draw_tributacao_municipal(self, c, y, dados):
        y = self._draw_section_title(c, y, "TRIBUTAÇÃO MUNICIPAL")
        return self._draw_data_table(
            c,
            y,
            rows=[
                [(1, "Tributação do ISSQN", dados.get("tributacao_issqn")), (1, "País Resultado da Prestação do Serviço", dados.get("pais_resultado_prestacao")), (1, "Município de Incidencia do ISSQN", dados.get("municipio_incidencia_issqn")), (1, "Regime Especial de Tributação", dados.get("regime_especial_tributacao", "Nenhum"))],
                [(1, "Tipo de Imunidade", dados.get("tipo_imunidade")), (1, "Suspensão da Exigibilidade do ISSQN", dados.get("suspensao_exigibilidade_issqn", "Nao")), (1, "Número Processo Suspensão", dados.get("numero_processo_suspensao")), (1, "Benefício Municipal", dados.get("beneficio_municipal"))],
                [(1, "Valor do Serviço", _fmt_money(dados.get("valor_servico"))), (1, "Desconto Incondicionado", _fmt_money(dados.get("desconto_incondicionado_mun"))), (1, "Total Deduções/Reduções", _fmt_money(dados.get("total_deducoes_reducoes"))), (1, "Cálculo do BM", dados.get("calculo_bm"))],
                [(1, "BC ISSQN", _fmt_money(dados.get("bc_issqn"))), (1, "Alíquota Aplicada", _fmt_percent(dados.get("aliquota_aplicada"))), (1, "Retenção do ISSQN", dados.get("retencao_issqn", "Não Retido")), (1, "ISSQN Apurado", _fmt_money(dados.get("issqn_apurado")))],
            ],
            col_fracs=(0.25, 0.25, 0.25, 0.25),
        )

    def _draw_tributacao_federal(self, c, y, dados):
        y = self._draw_section_title(c, y, "TRIBUTAÇÃO FEDERAL")
        return self._draw_data_table(
            c,
            y,
            rows=[
                [(1, "IRRF", _fmt_money(dados.get("irrf"))), (1, "Contribuição Previdenciária - Retida", _fmt_money(dados.get("contrib_previdenciaria_retida"))), (1, "CSLL - Retida", _fmt_money(dados.get("contrib_sociais_retidas"))), (1, "Total Retenções Federais", _fmt_money(dados.get("total_retencoes_federais")))],
                [(1, "PIS - Retido", _fmt_money(dados.get("pis_retido"))), (1, "COFINS - Retido", _fmt_money(dados.get("cofins_retido"))), (2, "Descrição Contrib. Sociais - Retidas", dados.get("descricao_contrib_sociais_retidas"))],
                [(2, "PIS - Débito Apuração Própria", dados.get("pis_debito_apuracao_propria")), (2, "COFINS - Débito Apuração Própria", dados.get("cofins_debito_apuracao_propria"))],
            ],
            col_fracs=(0.25, 0.25, 0.25, 0.25),
        )

    def _draw_valor_total(self, c, y, dados):
        y = self._draw_section_title(c, y, "VALOR TOTAL DA NFS-E")
        return self._draw_data_table(
            c,
            y,
            rows=[
                [(1, "Valor do Serviço", _fmt_money(dados.get("valor_servico"))), (1, "Desconto Condicionado", _fmt_money(dados.get("desconto_condicionado"))), (1, "Desconto Incondicionado", _fmt_money(dados.get("desconto_incondicionado"))), (1, "ISSQN Retido", _fmt_money(dados.get("issqn_retido")))],
                [(1, "Total das Retenções Federais", _fmt_money(dados.get("total_retencoes_federais"))), (1, "PIS/COFINS - Débito Apur. Própria", dados.get("pis_cofins_debito_apur_propria")), (1, "", ""), (1, "Valor Líquido da NFS-e", _fmt_money(dados.get("valor_liquido_nfse")))],
            ],
            col_fracs=(0.25, 0.25, 0.25, 0.25),
        )

    def _draw_totais_aproximados(self, c, y, dados):
        y = self._draw_section_title(c, y, "TOTAIS APROXIMADOS DOS TRIBUTOS")
        return self._draw_data_table(
            c,
            y,
            rows=[[
                (1, "Federais", _fmt_percent(dados.get("totais_federais"), spaced=True)),
                (1, "Estaduais", _fmt_percent(dados.get("totais_estaduais"), spaced=True)),
                (1, "Municipais", _fmt_percent(dados.get("totais_municipais"), spaced=True)),
            ]],
            col_fracs=(1 / 3, 1 / 3, 1 / 3),
            center=True,
        )

    def _draw_informacoes_complementares(self, c, y, dados):
        y = self._draw_section_title(c, y, "INFORMAÇÕES COMPLEMENTARES")
        return self._draw_data_table(c, y, rows=[[(1, "", _info_complementar(dados))]], col_fracs=(1,))

    def _draw_section_title(self, c, y, text):
        h = 4.8 * mm
        c.setFillColor(TITLE_BG)
        c.rect(MARGIN_X, y - h, CONTENT_W, h, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setLineWidth(0.75)
        c.rect(MARGIN_X, y - h, CONTENT_W, h, fill=0, stroke=1)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(MARGIN_X + 2, y - h + 1.45 * mm, text)
        return y - h

    def _draw_center_line(self, c, y, text):
        h = 5 * mm
        c.setLineWidth(0.75)
        c.rect(MARGIN_X, y - h, CONTENT_W, h)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawCentredString(PAGE_W / 2, y - h + 1.45 * mm, text)
        return y - h

    def _draw_data_table(self, c, y, rows, col_fracs, center: bool = False):
        n_cols = len(col_fracs)
        col_widths = [fraction * CONTENT_W for fraction in col_fracs]
        table_data = []
        span_cmds = []
        for row_index, row in enumerate(rows):
            line_cells = []
            col_index = 0
            for colspan, label, value in row:
                if center:
                    text = f"<font size=6.1 name='Helvetica-Bold'>{label}</font><br/><font size=7.4>{value}</font>"
                    cell = Paragraph(text, CENTER_BOLD_STYLE)
                else:
                    cell = _cell(label, value)
                line_cells.append(cell)
                for _ in range(colspan - 1):
                    line_cells.append(_blank())
                if colspan > 1:
                    span_cmds.append(("SPAN", (col_index, row_index), (col_index + colspan - 1, row_index)))
                col_index += colspan
            while len(line_cells) < n_cols:
                line_cells.append(_blank())
            table_data.append(line_cells)

        table = Table(table_data, colWidths=col_widths)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.75, GRID_COLOR),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 1.6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6),
                    *span_cmds,
                ]
            )
        )
        _, height = table.wrapOn(c, CONTENT_W, PAGE_H)
        table.drawOn(c, MARGIN_X, y - height)
        return y - height


def _wrap_text(c, text, x, y, max_width, font="Helvetica", size=5, leading=6):
    c.setFont(font, size)
    words = text.split()
    line = ""
    lines = []
    for word in words:
        test = f"{line} {word}".strip()
        if c.stringWidth(test, font, size) <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    for index, line_text in enumerate(lines):
        c.drawString(x, y - index * leading, line_text)

