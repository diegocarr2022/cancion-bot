"""
Genera al vuelo el PDF de la letra aprobada, para que el cliente lo pueda
guardar/imprimir - un detalle extra sobre el link de audio (ver el pedido de
Diego: si hay un reclamo o simplemente quiere un recuerdo fisico, esto ya
esta listo sin depender de un servicio externo).

Usa reportlab (pura Python, sin binarios externos como wkhtmltopdf) para no
depender de que Render tenga instalado algo fuera del venv. Paleta y tono
calcados de LANDING_HTML_EN (ver app/landing.py: --ink #16110d, --paper
#efe4cc, --amber #e8a23a) - pensado para el flujo en ingles de Tunecraft.

El titulo usa la misma tipografia que el H1 de la landing (Fraunces, ver
`h1, h2, h3 { font-family: 'Fraunces' }` en landing.py). Fraunces es una
fuente variable (OFL) sin instancias estaticas publicadas por Google Fonts,
asi que app/fonts/Fraunces-Black.ttf es una instancia ESTATICA generada una
sola vez con `fonttools varLib.instancer` fijando los ejes wght=900 (Black,
el peso mas oscuro que carga la landing) y opsz=40 (mismo optical size que
usa el H1 via font-variation-settings) - reportlab no soporta fuentes
variables directamente, necesita un TTF estatico para poder embeberlo.
"""
import io
import os
import re
from xml.sax.saxutils import escape as _esc

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

INK = colors.HexColor("#16110d")
PAPER = colors.HexColor("#efe4cc")
AMBER = colors.HexColor("#e8a23a")
INK_SOFT = colors.HexColor("#6b5c42")

_HEADER_H = 0.85 * inch
_FOOTER_H = 0.45 * inch

_FONT_TITLE = "Fraunces-Black"
pdfmetrics.registerFont(
    TTFont(_FONT_TITLE, os.path.join(os.path.dirname(__file__), "fonts", "Fraunces-Black.ttf"))
)


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


def _normalizar(texto: str) -> str:
    """Para decidir si dos bloques (ej. el Chorus y el Final Chorus) son "la
    misma letra" y se puede colapsar el segundo a "Repeat" - se ignoran
    mayusculas/puntuacion/saltos de linea, porque en la practica Suno/Claude
    a veces varian un signo de exclamacion o una mayuscula entre una
    repeticion y otra sin que sea realmente una letra distinta."""
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9\s]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def build_lyrics_pdf(title: str, lyric: str) -> bytes:
    """Devuelve los bytes del PDF (una o mas paginas segun el largo de la
    letra - SimpleDocTemplate pagina solo automaticamente, aunque el ajuste
    de tamanos de fuente esta pensado para que una letra de largo tipico
    entre en una sola hoja).

    Deliberadamente NO incluye el genero/estilo musical ni un QR (a pedido
    de Diego: solo titulo + letra, para que quepa en una hoja - el QR que
    se probo antes le quitaba el espacio que le faltaba)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        topMargin=_HEADER_H + 0.4 * inch,
        bottomMargin=_FOOTER_H + 0.25 * inch,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        title=title or "Your song",
    )

    title_style = ParagraphStyle(
        "SongTitle", fontName=_FONT_TITLE, fontSize=21, leading=25,
        textColor=INK, alignment=TA_CENTER, spaceAfter=16,
    )
    tag_style = ParagraphStyle(
        "Tag", fontName="Helvetica-Bold", fontSize=9, leading=11,
        textColor=AMBER, alignment=TA_CENTER, spaceBefore=9, spaceAfter=3,
    )
    line_style = ParagraphStyle(
        "Line", fontName="Helvetica", fontSize=9.5, leading=13,
        textColor=INK, alignment=TA_CENTER,
    )
    repeat_style = ParagraphStyle(
        "Repeat", fontName="Helvetica-Oblique", fontSize=9.5, leading=13,
        textColor=INK_SOFT, alignment=TA_CENTER,
    )

    story = [Paragraph(_esc(title or "Your song"), title_style)]

    # Partir la letra en secciones [Tag] + cuerpo, para poder colapsar un
    # bloque repetido (mismo Coro/Pre-Coro/Final Chorus que ya aparecio
    # antes) a un simple "Repeat" en vez de repetirlo completo - asi entra
    # en una sola hoja aunque la cancion tenga el coro 2-3 veces. Se compara
    # normalizado (ver _normalizar) para que una coma o mayuscula de mas en
    # el Final Chorus no le impida matchear con el Chorus de antes.
    secciones = []
    tag_actual = None
    cuerpo_actual = []
    for raw_line in (lyric or "").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            secciones.append((tag_actual, cuerpo_actual))
            tag_actual = line
            cuerpo_actual = []
        else:
            cuerpo_actual.append(line)
    secciones.append((tag_actual, cuerpo_actual))

    cuerpos_vistos = set()
    for tag, cuerpo in secciones:
        if tag:
            story.append(Paragraph(_esc(tag.upper()), tag_style))
        normalizado = _normalizar("\n".join(cuerpo))
        if tag and normalizado and normalizado in cuerpos_vistos:
            story.append(Paragraph("Repeat", repeat_style))
            continue
        if normalizado:
            cuerpos_vistos.add(normalizado)
        for line in cuerpo:
            if not line:
                story.append(Spacer(1, 3))
            else:
                story.append(Paragraph(_esc(line), line_style))

    doc.build(story, onFirstPage=_draw_chrome, onLaterPages=_draw_chrome)
    return buf.getvalue()
