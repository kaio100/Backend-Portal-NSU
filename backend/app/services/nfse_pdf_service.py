from __future__ import annotations

"""
Gerador de DANFSe (espelho) usando ReportLab puro — sem HTML intermediário.
Pensado para encaixar no seu NfsePdfService (mesmos nomes de método:
_draw_header, _draw_key_qr, _draw_qr, gerar_danfse_espelho).

Estratégia:
- Cabeçalho, box da chave de acesso e QR code: desenhados direto no canvas
  (igual ao que vocês já fazem).
- Corpo (Emitente, Tomador, Serviço, Tributação etc.): montado com
  reportlab.platypus.Table (facilita muito bordas, colspans e quebra de
  linha automática) e "carimbado" no canvas via table.drawOn(c, x, y).

Requer: reportlab (já no requirements.txt), qrcode é OPCIONAL — aqui uso
o QrCodeWidget nativo do ReportLab (reportlab.graphics.barcode.qr), então
não precisa de dependência nova.
"""

import re
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF

PAGE_W, PAGE_H = A4
MARGIN_X = 10 * mm
MARGIN_TOP = 10 * mm
MARGIN_BOTTOM = 9 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X

GRID_COLOR = colors.black
TITLE_BG = colors.HexColor("#d9d9d9")

VALUE_STYLE = ParagraphStyle(
    "value", fontName="Helvetica", fontSize=7.6, leading=9.2, textColor=colors.black,
)
CENTER_BOLD_STYLE = ParagraphStyle(
    "center_bold", fontName="Helvetica-Bold", fontSize=7.6, leading=9.2,
    alignment=1,  # center
)


def _cell(label: str, value=None):
    """Célula padrão: rótulo em negrito pequeno + valor embaixo."""
    value = "-" if value in (None, "") else str(value)
    txt = f"<font size=6.2 name='Helvetica-Bold'>{label}</font><br/><font size=7.6>{value}</font>"
    return Paragraph(txt, VALUE_STYLE)


def _blank():
    return Paragraph("", VALUE_STYLE)


def _sanitize_filename(value: str) -> str:
    value = str(value or "NFS-e").strip()
    value = re.sub(r'[<>:"/\\|?*]+', "", value)
    value = re.sub(r"\s+", "_", value)
    return value[:180].strip("._-") or "NFS-e"


def friendly_pdf_filename(dados: dict) -> str:
    prestador = dados.get("emit_nome") or dados.get("prestador_nome") or "NFS-e"
    numero = dados.get("numero_nfse") or "-"
    return f"{_sanitize_filename(prestador)} NFS-e {_sanitize_filename(numero)}.pdf"


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

        y = self._draw_data_table(
            c, y,
            rows=[
                [(1, "Número da NFS-e", dados.get("numero_nfse")),
                 (1, "Competência da NFS-e", dados.get("competencia")),
                 (2, "Data e Hora da emissão da NFS-e", dados.get("data_emissao_nfse"))],
                [(1, "Número da DPS", dados.get("numero_dps")),
                 (1, "Série da DPS", dados.get("serie_dps")),
                 (2, "Data e Hora da emissão da DPS", dados.get("data_emissao_dps"))],
            ],
            col_fracs=(0.25, 0.25, 0.25, 0.25),
        )

        y = self._draw_section_title(c, y, "EMITENTE DA NFS-e")
        y = self._draw_data_table(
            c, y,
            rows=[
                [(1, "Prestador do Serviço", ""),
                 (1, "CNPJ / CPF / NIF", dados.get("emit_cnpj")),
                 (1, "Inscrição Municipal", dados.get("emit_inscricao_municipal")),
                 (1, "Telefone", dados.get("emit_telefone"))],
                [(2, "Nome / Nome Empresarial", dados.get("emit_nome")),
                 (2, "E-mail", dados.get("emit_email"))],
                [(2, "Endereço", dados.get("emit_endereco")),
                 (1, "Município", dados.get("emit_municipio")),
                 (1, "CEP", dados.get("emit_cep"))],
                [(2, "Simples Nacional na Data de Competência", dados.get("emit_simples_nacional")),
                 (2, "Regime de Apuração Tributária pelo SN", dados.get("emit_regime_apuracao"))],
            ],
            col_fracs=(0.25, 0.25, 0.25, 0.25),
        )

        y = self._draw_section_title(c, y, "TOMADOR DO SERVIÇO")
        y = self._draw_data_table(
            c, y,
            rows=[
                [(1, "CNPJ / CPF / NIF", dados.get("tom_cnpj")),
                 (1, "Inscrição Municipal", dados.get("tom_inscricao_municipal")),
                 (2, "Telefone", dados.get("tom_telefone"))],
                [(2, "Nome / Nome Empresarial", dados.get("tom_nome")),
                 (2, "E-mail", dados.get("tom_email"))],
                [(2, "Endereço", dados.get("tom_endereco")),
                 (2, "Município", dados.get("tom_municipio"))],
                [(4, "CEP", dados.get("tom_cep"))],
            ],
            col_fracs=(0.25, 0.25, 0.25, 0.25),
        )

        y = self._draw_center_line(
            c, y, dados.get("intermediario_texto", "INTERMEDIÁRIO DO SERVIÇO NÃO IDENTIFICADO NA NFS-e")
        )

        y = self._draw_section_title(c, y, "SERVIÇO PRESTADO")
        y = self._draw_data_table(
            c, y,
            rows=[
                [(1, "Código de Tributação Nacional", dados.get("codigo_tributacao_nacional")),
                 (1, "Código de Tributação Municipal", dados.get("codigo_tributacao_municipal")),
                 (1, "Local da Prestação", dados.get("local_prestacao")),
                 (1, "País da Prestação", dados.get("pais_prestacao"))],
                [(4, "Descrição do Serviço", dados.get("descricao_servico"))],
            ],
            col_fracs=(0.34, 0.22, 0.22, 0.22),
        )

        y = self._draw_section_title(c, y, "TRIBUTAÇÃO MUNICIPAL")
        y = self._draw_data_table(
            c, y,
            rows=[
                [(1, "Tributação do ISSQN", dados.get("tributacao_issqn")),
                 (1, "País Resultado da Prestação do Serviço", dados.get("pais_resultado_prestacao")),
                 (1, "Município de Incidência do ISSQN", dados.get("municipio_incidencia_issqn")),
                 (1, "Regime Especial de Tributação", dados.get("regime_especial_tributacao", "Nenhum"))],
                [(1, "Tipo de Imunidade", dados.get("tipo_imunidade")),
                 (1, "Suspensão da Exigibilidade do ISSQN", dados.get("suspensao_exigibilidade_issqn", "Não")),
                 (1, "Número Processo Suspensão", dados.get("numero_processo_suspensao")),
                 (1, "Benefício Municipal", dados.get("beneficio_municipal"))],
                [(1, "Valor do Serviço", _fmt_money(dados.get("valor_servico"))),
                 (1, "Desconto Incondicionado", dados.get("desconto_incondicionado_mun")),
                 (1, "Total Deduções/Reduções", dados.get("total_deducoes_reducoes")),
                 (1, "Cálculo do BM", dados.get("calculo_bm"))],
                [(1, "BC ISSQN", dados.get("bc_issqn")),
                 (1, "Alíquota Aplicada", dados.get("aliquota_aplicada")),
                 (1, "Retenção do ISSQN", dados.get("retencao_issqn", "Não Retido")),
                 (1, "ISSQN Apurado", dados.get("issqn_apurado"))],
            ],
            col_fracs=(0.25, 0.25, 0.25, 0.25),
        )

        y = self._draw_section_title(c, y, "TRIBUTAÇÃO FEDERAL")
        y = self._draw_data_table(
            c, y,
            rows=[
                [(1, "IRRF", dados.get("irrf")),
                 (1, "Contribuição Previdenciária - Retida", dados.get("contrib_previdenciaria_retida")),
                 (1, "Contribuições Sociais - Retidas", dados.get("contrib_sociais_retidas")),
                 (1, "Descrição Contrib. Sociais - Retidas", dados.get("descricao_contrib_sociais_retidas"))],
                [(2, "PIS - Débito Apuração Própria", dados.get("pis_debito_apuracao_propria")),
                 (2, "COFINS - Débito Apuração Própria", dados.get("cofins_debito_apuracao_propria"))],
            ],
            col_fracs=(0.25, 0.25, 0.25, 0.25),
        )

        y = self._draw_section_title(c, y, "VALOR TOTAL DA NFS-E")
        y = self._draw_data_table(
            c, y,
            rows=[
                [(1, "Valor do Serviço", _fmt_money(dados.get("valor_servico"))),
                 (1, "Desconto Condicionado", dados.get("desconto_condicionado")),
                 (1, "Desconto Incondicionado", dados.get("desconto_incondicionado")),
                 (1, "ISSQN Retido", dados.get("issqn_retido"))],
                [(1, "Total das Retenções Federais", dados.get("total_retencoes_federais")),
                 (1, "PIS/COFINS - Débito Apur. Própria", dados.get("pis_cofins_debito_apur_propria")),
                 (1, "", ""),
                 (1, "Valor Líquido da NFS-e", _fmt_money(dados.get("valor_liquido_nfse")))],
            ],
            col_fracs=(0.25, 0.25, 0.25, 0.25),
        )

        y = self._draw_section_title(c, y, "TOTAIS APROXIMADOS DOS TRIBUTOS")
        y = self._draw_data_table(
            c, y,
            rows=[[
                (1, "Federais", f"{dados.get('totais_federais', '0,00')} %"),
                (1, "Estaduais", f"{dados.get('totais_estaduais', '0,00')} %"),
                (1, "Municipais", f"{dados.get('totais_municipais', '0,00')} %"),
            ]],
            col_fracs=(1 / 3, 1 / 3, 1 / 3),
            center=True,
        )

        y = self._draw_section_title(c, y, "INFORMAÇÕES COMPLEMENTARES")
        y = self._draw_data_table(
            c, y,
            rows=[[(1, "NFSe Subst:", dados.get("nfse_subst"))]],
            col_fracs=(1,),
        )

        c.save()
        return output_path

    # ------------------------------------------------------------------
    # Blocos de desenho
    # ------------------------------------------------------------------

    def _draw_header(self, c, y, dados):
        x = MARGIN_X
        h = 16 * mm
        top = y

        # Logo "NFSe" textual (troque por c.drawImage(...) se tiver o logo em arquivo)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(x, top - 6 * mm, "NFSe")
        c.setFont("Helvetica", 6)
        c.drawString(x, top - 9.5 * mm, "Nota Fiscal de")
        c.drawString(x, top - 11.5 * mm, "Serviço eletrônica")

        # Título central
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString(PAGE_W / 2, top - 6 * mm, "DANFSe v1.0")
        c.setFont("Helvetica", 9)
        c.drawCentredString(PAGE_W / 2, top - 10 * mm, "Documento Auxiliar da NFS-e")

        # Info prefeitura (direita)
        right_x = PAGE_W - MARGIN_X
        c.setFont("Helvetica-Bold", 7.5)
        c.drawRightString(right_x, top - 4 * mm, f"Prefeitura Municipal de {dados.get('municipio_prefeitura', '')}")
        c.setFont("Helvetica", 6.5)
        c.drawRightString(right_x, top - 7 * mm, dados.get("orgao_prefeitura", "Departamento de Arrecadação e Fiscalização."))
        c.drawRightString(right_x, top - 9.5 * mm, dados.get("telefone_prefeitura", ""))
        c.drawRightString(right_x, top - 12 * mm, dados.get("email_prefeitura", ""))

        return top - h

    def _draw_key_qr(self, c, y, dados):
        x = MARGIN_X
        w = CONTENT_W
        h = 18 * mm
        qr_w = 0.22 * w
        chave_w = w - qr_w

        c.setLineWidth(0.75)
        c.rect(x, y - h, w, h)
        c.line(x + chave_w, y - h, x + chave_w, y)  # divisória

        c.setFont("Helvetica-Bold", 7)
        c.drawString(x + 2, y - 4 * mm, "Chave de Acesso da NFS-e")
        c.setFont("Helvetica", 9.5)
        c.drawString(x + 2, y - 8 * mm, dados.get("chave_acesso", ""))

        self._draw_qr(c, x + chave_w + 2, y - h + 2, qr_w - 4, h - 4, dados)

        return y - h

    def _draw_qr(self, c, x, y, w, h, dados):
        """Desenha o QR code dentro do box (x, y, w, h)."""
        size = min(w * 0.55, h)
        qr_content = dados.get(
            "qr_conteudo",
            f"https://www.nfse.gov.br/consultapublica?chave={dados.get('chave_acesso', '')}",
        )
        widget = QrCodeWidget(qr_content)
        b = widget.getBounds()
        bw, bh = b[2] - b[0], b[3] - b[1]
        d = Drawing(size, size, transform=[size / bw, 0, 0, size / bh, 0, 0])
        d.add(widget)
        renderPDF.draw(d, c, x, y + (h - size) / 2)

        c.setFont("Helvetica", 4.8)
        legenda = (
            "A autenticidade desta NFS-e pode ser verificada pela leitura "
            "deste código QR ou pela consulta da chave de acesso no portal "
            "nacional da NFS-e"
        )
        text_x = x + size + 2
        text_w = w - size - 2
        _wrap_text(c, legenda, text_x, y + h - 3, text_w, font="Helvetica", size=4.8, leading=5.4)

    def _draw_section_title(self, c, y, text):
        h = 5.2 * mm
        x = MARGIN_X
        w = CONTENT_W
        c.setFillColor(TITLE_BG)
        c.rect(x, y - h, w, h, fill=1, stroke=0)
        c.setFillColor(colors.black)
        c.setLineWidth(0.75)
        c.rect(x, y - h, w, h, fill=0, stroke=1)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x + 2, y - h + 1.6 * mm, text)
        return y - h

    def _draw_center_line(self, c, y, text):
        h = 5 * mm
        x = MARGIN_X
        w = CONTENT_W
        c.setLineWidth(0.75)
        c.rect(x, y - h, w, h)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawCentredString(PAGE_W / 2, y - h + 1.5 * mm, text)
        return y - h

    def _draw_data_table(self, c, y, rows, col_fracs, center=False):
        """
        rows: lista de linhas; cada linha é lista de tuplas (colspan, label, value)
        colspan é em "unidades de coluna" relativas a col_fracs.
        """
        n_cols = len(col_fracs)
        col_widths = [f * CONTENT_W for f in col_fracs]

        table_data = []
        span_cmds = []
        for r, row in enumerate(rows):
            line_cells = []
            col_i = 0
            for colspan, label, value in row:
                if center:
                    txt = f"<font size=6.2 name='Helvetica-Bold'>{label}</font><br/><font size=7.6>{value}</font>"
                    para = Paragraph(txt, CENTER_BOLD_STYLE)
                else:
                    para = _cell(label, value)
                line_cells.append(para)
                for _ in range(colspan - 1):
                    line_cells.append(_blank())
                if colspan > 1:
                    span_cmds.append(("SPAN", (col_i, r), (col_i + colspan - 1, r)))
                col_i += colspan
            # completa linha se faltar coluna
            while len(line_cells) < n_cols:
                line_cells.append(_blank())
            table_data.append(line_cells)

        t = Table(table_data, colWidths=col_widths)
        style_cmds = [
            ("GRID", (0, 0), (-1, -1), 0.75, GRID_COLOR),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ] + span_cmds
        if center:
            style_cmds.append(("ALIGN", (0, 0), (-1, -1), "CENTER"))
        t.setStyle(TableStyle(style_cmds))

        tw, th = t.wrapOn(c, CONTENT_W, PAGE_H)
        t.drawOn(c, MARGIN_X, y - th)
        return y - th


def _fmt_money(v):
    if v in (None, ""):
        return "-"
    return f"R$ {v}"


def _wrap_text(c, text, x, y, max_width, font="Helvetica", size=5, leading=6):
    """Quebra texto simples em múltiplas linhas dentro de max_width."""
    c.setFont(font, size)
    words = text.split()
    line = ""
    lines = []
    for word in words:
        test = f"{line} {word}".strip()
        if c.stringWidth(test, font, size) <= max_width:
            line = test
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    for i, ln in enumerate(lines):
        c.drawString(x, y - i * leading, ln)


if __name__ == "__main__":
    dados = {
        "municipio_prefeitura": "Hidrolândia-GO",
        "orgao_prefeitura": "Departamento de Arrecadação e Fiscalização.",
        "telefone_prefeitura": "(62)99506-8320",
        "email_prefeitura": "coletoria.hidrolandia@gmail.com",
        "chave_acesso": "52097052228460833000154000000000003626040412158633",
        "numero_nfse": "36",
        "competencia": "30/04/2026",
        "data_emissao_nfse": "30/04/2026 08:56:06",
        "numero_dps": "23",
        "serie_dps": "70000",
        "data_emissao_dps": "30/04/2026 08:56:06",
        "emit_cnpj": "28.460.833/0001-54",
        "emit_inscricao_municipal": "5294",
        "emit_telefone": "(62) 8122-5465",
        "emit_nome": "NK PUBLICIDADES E EVENTOS LTDA",
        "emit_email": "PILOTOCONTABILIDADE@GMAIL.COM",
        "emit_endereco": "R ARATICUM, S/N, VILLAGE DOS IPES",
        "emit_municipio": "Hidrolândia - GO",
        "emit_cep": "75340-594",
        "emit_simples_nacional": "Optante - Microempresa ou Empresa de Pequeno Porte (ME/EPP)",
        "emit_regime_apuracao": "Regime de apuração dos tributos federais e municipal pelo Simples Nacional",
        "tom_cnpj": "97.458.533/0001-53",
        "tom_nome": "GUARDIA ADMINISTRACAO E SERVICOS LTDA",
        "tom_endereco": "TUPINAMBAS, SN, QUADRA01 LOTE 09, VILA BRASILIA",
        "tom_municipio": "Aparecida de Goiânia - GO",
        "tom_cep": "74905-730",
        "codigo_tributacao_nacional": "17.06.01 - Propaganda e publicidade, inclusive promoção de vendas, p...",
        "local_prestacao": "Hidrolândia - GO",
        "descricao_servico": (
            "2 HORAS DE PROPAGANDA DE VOLANTE<br/>"
            "DADOS PARA PAGAMENTO: BANCO: BCO DO BRASIL S.A FAVORECIDO: NK PUBLICIDADES E EVENTOS LTDA "
            "AGÊNCIA: 5893-9 CORRENTE<br/>JURÍDICA: 18824-7<br/>CHAVE PIX: 28.460.833/0001-54"
        ),
        "tributacao_issqn": "Operação Tributável",
        "municipio_incidencia_issqn": "Hidrolândia - GO",
        "valor_servico": "180,00",
        "valor_liquido_nfse": "180,00",
        "nfse_subst": "52097052228460833000154000000000003426046845898325",
    }

    NfsePdfService().gerar_danfse_espelho(dados, "nfse_saida_reportlab.pdf")
    print("PDF gerado: nfse_saida_reportlab.pdf")
