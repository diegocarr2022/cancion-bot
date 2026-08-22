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

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
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


def _qr_drawing(data: str, size: float) -> Drawing:
    """QR code como Flowable de reportlab (Drawing ya hereda de Flowable, se
    puede meter directo en el "story") - sin librerias externas (ni qrcode
    ni Pillow), reportlab ya trae el generador de codigos de barra/QR."""
    widget = QrCodeWidget(data)
    x0, y0, x1, y1 = widget.getBounds()
    w, h = x1 - x0, y1 - y0
    drawing = Drawing(size, size, transform=[size / w, 0, 0, size / h, -x0 * size / w, -y0 * size / h])
    drawing.add(widget)
    drawing.hAlign = "CENTER"
    return drawing


def build_lyrics_pdf(title: str, style: str, lyric: str, song_url: str | None = None) -> bytes:
    """Devuelve los bytes del PDF (una o mas paginas segun el largo de la
    letra - SimpleDocTemplate pagina solo automaticamente). Si se pasa
    song_url, se agrega un QR chiquito al final (despues de la letra, no en
    el pie de cada pagina - asi aparece una sola vez, donde sea que termine
    cayendo segun el largo de la letra) para que puedan escanearlo y volver
    directo a su cancion."""
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

    if song_url:
        qr_caption_style = ParagraphStyle(
            "QRCaption", fontName="Helvetica", fontSize=9, leading=11,
            textColor=INK_SOFT, alignment=TA_CENTER, spaceBefore=8,
        )
        story.append(Spacer(1, 28))
        story.append(_qr_drawing(song_url, 0.9 * inch))
        story.append(Paragraph("Scan to play your song", qr_caption_style))

    doc.build(story, onFirstPage=_draw_chrome, onLaterPages=_draw_chrome)
    return buf.getvalue()
