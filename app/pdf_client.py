"""
Genera al vuelo el PDF de la letra aprobada, para que el cliente lo pueda
guardar/imprimir - un detalle extra sobre el link de audio (ver el pedido de
Diego: si hay un reclamo o simplemente quiere un recuerdo fisico, esto ya
esta listo sin depender de un servicio externo).

Usa reportlab (pura Python, sin binarios externos como wkhtmltopdf) para no
depender de que Render tenga instalado algo fuera del venv. Paleta y tono
calcados de LANDING_HTML_EN (ver app/landing.py: --ink #16110d, --paper
#efe4cc, --amber #e8a23a) - pensado para el flujo en ingles de Tunecraft.
"""
import io
from xml.sax.saxutils import escape as _esc

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

INK = colors.HexColor("#16110d")
PAPER = colors.HexColor("#efe4cc")
AMBER = colors.HexColor("#e8a23a")
INK_SOFT = colors.HexColor("#6b5c42")

_HEADER_H = 0.85 * inch
_FOOTER_H = 0.45 * inch


def _draw_chrome(canvas, _doc):
    canvas.saveState()
    page_w, page_h = LETTER
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    canvas.setFillColor(INK)
    canvas.rect(0, page_h - _HEADER_H, page_w, _HEADER_H, fill=1, stroke=0)
    canvas.setFillColor(AMBER)
    canvas.setFont("Helvetica-Bold", 20)
    canvas.drawString(0.9 * inch, page_h - 0.55 * inch, "TUNECRAFT")
    canvas.setFillColor(PAPER)
    canvas.setFont("Helvetica", 9)
    canvas.drawRightString(page_w - 0.9 * inch, page_h - 0.55 * inch, "tunecraft.studio")

    canvas.setFillColor(INK_SOFT)
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(page_w / 2, 0.35 * inch, "A one-of-a-kind song, written for a real story.")
    canvas.restoreState()


def build_lyrics_pdf(title: str, style: str, lyric: str) -> bytes:
    """Devuelve los bytes del PDF (una o mas paginas segun el largo de la
    letra - SimpleDocTemplate pagina solo automaticamente)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        topMargin=_HEADER_H + 0.45 * inch,
        bottomMargin=_FOOTER_H + 0.3 * inch,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        title=title or "Your song",
    )

    title_style = ParagraphStyle(
        "SongTitle", fontName="Helvetica-Bold", fontSize=22, leading=27,
        textColor=INK, alignment=TA_CENTER, spaceAfter=6,
    )
    style_style = ParagraphStyle(
        "SongStyle", fontName="Helvetica-Oblique", fontSize=11, leading=14,
        textColor=INK_SOFT, alignment=TA_CENTER, spaceAfter=20,
    )
    tag_style = ParagraphStyle(
        "Tag", fontName="Helvetica-Bold", fontSize=10.5, leading=13,
        textColor=AMBER, spaceBefore=14, spaceAfter=4,
    )
    line_style = ParagraphStyle(
        "Line", fontName="Helvetica", fontSize=11.5, leading=16,
        textColor=INK,
    )

    story = [Paragraph(_esc(title or "Your song"), title_style)]
    story.append(Paragraph(_esc(style), style_style) if style else Spacer(1, 18))

    for raw_line in (lyric or "").splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 6))
            continue
        if line.startswith("[") and line.endswith("]"):
            story.append(Paragraph(_esc(line.upper()), tag_style))
        else:
            story.append(Paragraph(_esc(line), line_style))

    doc.build(story, onFirstPage=_draw_chrome, onLaterPages=_draw_chrome)
    return buf.getvalue()
