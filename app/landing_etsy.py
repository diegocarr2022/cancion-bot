"""Landing /etsy (oct 2026): la misma landing EN (LANDING_HTML_EN) en "modo Etsy".

Quien llega aca ya compro la cancion en la tienda de Etsy de Diego (VibeCraftDigitalShop),
asi que esta pagina NO muestra precios ni cobra: pide el numero de pedido de Etsy, el backend
lo valida contra el Worker de Cloudflare (app/etsy_client.py) y recien entonces se habilita el
chat de siempre. Al aprobar la letra se gasta un credito del pedido en vez de cobrar (ver
web_conversation._finalizar_letra_etsy).

Por que no es una landing duplicada ni un "esconder precios con CSS": el HTML se arma desde la
plantilla EN ya existente, sustituyendo del lado del SERVIDOR cada pedazo que habla de dinero
(precio, contador de oferta, caja de preview, caja de pago de Stripe, FAQ de costo, JSON-LD,
pixel de Meta y Google Ads). Asi el precio nunca llega al navegador de un comprador de Etsy
(Etsy no deja ofrecer comprar fuera de su plataforma) y los demos de estilos, la identidad de
marca y el chat se mantienen identicos y se actualizan solos cuando cambia la landing normal.

Falla cerrado: si la plantilla EN cambia y alguna sustitucion ya no encaja, o si despues de
armar la pagina queda alguna palabra de dinero en el texto visible, ETSY_LANDING_HTML queda en
None y /etsy responde 503 en vez de mostrar una pagina con precios. El resto del sitio no se
entera. Ver ETSY_LANDING_ERROR para el motivo (se loguea al arrancar).
"""
import logging
import re

from app.config import BASE_URL, BRAND_NAME_EN
from app.landing import LANDING_HTML_EN, _GOOGLE_ADS_SCRIPT, _META_PIXEL_SCRIPT_EN

log = logging.getLogger("cancion-bot")


class _TemplateChanged(Exception):
    pass


def _sub(html: str, old: str, new: str) -> str:
    if old not in html:
        raise _TemplateChanged(f"no encontre este pedazo en LANDING_HTML_EN: {old[:80]!r}")
    return html.replace(old, new, 1)


def _rx(html: str, pattern: str, new: str) -> str:
    out, n = re.subn(pattern, lambda _m: new, html, count=1, flags=re.S)
    if n != 1:
        raise _TemplateChanged(f"patron no encontrado en LANDING_HTML_EN: {pattern[:80]!r}")
    return out


_GATE_CSS = """
<style>
  body.etsy-locked #chat-section { display: none; }
  .etsy-gate { max-width: 440px; margin: 6px auto 22px; text-align: center; position: relative; z-index: 1; }
  .etsy-gate .gate-title { font-family: 'Fraunces', serif; font-weight: 900; font-size: 20px; margin: 0 0 6px; }
  .etsy-gate .gate-sub { font-size: 13.5px; color: var(--ink-soft); margin: 0 0 14px; }
  .etsy-gate .gate-row { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; }
  .etsy-gate input { flex: 1 1 200px; min-width: 0; padding: 14px 16px; font-size: 16px; border-radius: 10px;
    border: 1px solid var(--line); background: #fff8e8; color: #241a10; font-family: inherit; }
  .etsy-gate button { padding: 14px 22px; font-size: 15px; font-weight: 700; border: none; border-radius: 10px;
    background: var(--rec); color: #fff5ee; cursor: pointer; font-family: inherit; }
  .etsy-gate button:disabled { opacity: 0.6; cursor: default; }
  .etsy-gate .gate-hint { font-size: 12px; color: var(--ink-soft); margin: 12px 0 0; }
  .etsy-gate .gate-error { color: #d14b3e; font-size: 13.5px; margin: 12px 0 0; min-height: 1.2em; }
</style>
"""

_GATE_HTML = """<div class="etsy-gate" id="etsy-gate">
      <p class="gate-title">Enter your Etsy order number</p>
      <p class="gate-sub">It's in your Etsy purchase confirmation email, or under <b>Purchases and reviews</b> in your Etsy account.</p>
      <form class="gate-row" id="etsy-gate-form" autocomplete="off">
        <input id="etsy-order-input" inputmode="numeric" placeholder="e.g. 3912345678" aria-label="Etsy order number" required>
        <button id="etsy-order-btn" type="submit">Start my song</button>
      </form>
      <p class="gate-error" id="etsy-gate-error" role="alert"></p>
      <p class="gate-hint">One order number = one personalized song.</p>
    </div>

    <div class="trust-row">
      <span class="trust-pill">Approve the lyrics before anything is recorded</span>
      <span class="trust-pill">Ready in minutes</span>
    </div>

    """

_HERO_SUB = (
    '<p class="sub">The most unique gift you\'ll ever give - a real song written and sung from your story. '
    "You approve every lyric before anything is recorded, and your finished song is ready in minutes.</p>"
)

_FAQ_COST_REPLACEMENT = (
    '<div class="note"><p class="note-q">Is there anything else I need to do?</p>'
    '<p class="note-a">No - your Etsy order already includes your song. Enter your order number above, '
    "tell us the story, approve the lyrics, and that's it.</p></div>"
)

# Reemplaza desde "let _sesionArrancada" hasta el final del <script>: en modo Etsy la sesion NO
# arranca sola al ver el chat (eso creaba la sesion antes de validar el pedido) sino cuando el
# numero de pedido ya fue validado. Con ?session_id= (volver a ver su cancion) arranca directo.
_ETSY_BOOT_JS = """let _sesionArrancada = false;
function _arrancarSesionUnaVez() {
  if (_sesionArrancada) return;
  _sesionArrancada = true;
  iniciar();
}
function desbloquearChat(orderNumber) {
  window.ETSY_ORDER = orderNumber;
  document.body.classList.remove("etsy-locked");
  const gate = $("etsy-gate");
  if (gate) gate.style.display = "none";
  const sec = $("chat-section");
  if (sec) sec.scrollIntoView({behavior: "smooth", block: "start"});
  _arrancarSesionUnaVez();
}
document.addEventListener("DOMContentLoaded", () => {
  const params = new URLSearchParams(window.location.search);
  if (params.get("session_id")) {
    document.body.classList.remove("etsy-locked");
    const gate = $("etsy-gate");
    if (gate) gate.style.display = "none";
    _arrancarSesionUnaVez();
    return;
  }
  const form = $("etsy-gate-form");
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const btn = $("etsy-order-btn");
    const err = $("etsy-gate-error");
    err.textContent = "";
    const numero = $("etsy-order-input").value.replace(/\\D/g, "");
    if (!numero) { err.textContent = "Please enter the order number from your Etsy purchase."; return; }
    btn.disabled = true;
    try {
      const resp = await fetch("/etsy/check", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({order_number: numero}),
      });
      const data = await resp.json();
      if (data.ok && data.resume_session_id) {
        window.location.href = "/etsy?session_id=" + encodeURIComponent(data.resume_session_id);
        return;
      }
      if (data.ok) { desbloquearChat(numero); return; }
      err.textContent = data.error || "We couldn't verify that order. Please try again.";
    } catch (e) {
      err.textContent = "We couldn't reach the server. Please try again in a moment.";
    }
    btn.disabled = false;
  });
});
</script>
</body>
</html>
"""

# Texto visible que NUNCA debe aparecer en /etsy (dinero, cobro, oferta). Se revisa sobre el HTML
# ya armado, sin <script>/<style>/comentarios - es la red de seguridad de las sustituciones de arriba.
_FORBIDDEN_VISIBLE = re.compile(
    r"\$|€|£|\busd\b|\bmxn\b|\bprice|\bpricing|launch (price|window)|\bstripe\b|\bcheckout\b|\bpay\b|\bpays\b|\bpaying\b|"
    r"\bpayment|\bpaid\b|\bcharge|\bcost|\bpreview\b|\bdiscount|\bcoupon|\bvalue\b|\boffer\b",
    re.I,
)


def _visible_text(html: str) -> str:
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html)


def _meta_leaks(html: str) -> list[str]:
    """Textos de <meta>/<title> y de atributos visibles (alt, placeholder) tambien cuentan."""
    found = []
    for m in re.finditer(r'<meta[^>]+content="([^"]*)"|<title>(.*?)</title>', html, flags=re.S):
        found.append(m.group(1) or m.group(2) or "")
    return found


def build_etsy_landing() -> str:
    html = LANDING_HTML_EN

    # --- cabecera: sin indexar, sin precio en descripciones, sin datos estructurados de oferta ---
    html = _rx(html, r"<title>.*?</title>", f"<title>Your Personalized Song | {BRAND_NAME_EN}</title>")
    html = _rx(
        html,
        r'<meta name="description" content="[^"]*">',
        '<meta name="description" content="Create your personalized song: tell us your story, approve the lyrics, '
        'and get a real, sung song in minutes.">\n<meta name="robots" content="noindex, nofollow">',
    )
    html = _rx(
        html,
        r'<meta property="og:description" content="[^"]*">',
        '<meta property="og:description" content="A real, sung song written from your story.">',
    )
    html = _rx(html, r'<link rel="canonical" href="[^"]*">', f'<link rel="canonical" href="{BASE_URL}/etsy">')
    html = _rx(html, r'<meta property="og:url" content="[^"]*">', f'<meta property="og:url" content="{BASE_URL}/etsy">')
    html = re.sub(r'<script type="application/ld\+json">.*?</script>', "", html, flags=re.S)

    # --- sin tracking de ventas/anuncios (sesiones de Etsy no son conversiones de la landing) ---
    html = _sub(html, _META_PIXEL_SCRIPT_EN, "")
    html = _sub(html, _GOOGLE_ADS_SCRIPT, "")
    html = re.sub(r'<script src="https://js\.stripe\.com/[^"]*"[^>]*></script>', "", html)

    # --- hero: fuera precio/contador/oferta; entra el campo de numero de pedido ---
    html = _rx(html, r'<p class="sub">.*?</p>', _HERO_SUB)
    html = _rx(html, r'<div class="price-row">.*?(?=<div class="tag-row">)', _GATE_HTML)
    html = _sub(html, "</head>", _GATE_CSS + "</head>")
    html = _sub(html, "<body>", '<body class="etsy-locked">')

    # --- textos que mencionan cobro ---
    html = _sub(html, "before any money moves", "before anything is recorded")
    html = _sub(html, "Takes about 2 minutes. No account, no commitment yet.", "Takes about 3 minutes. No account needed.")
    html = _sub(html, "You see the full lyrics before you pay anything.", "You see the full lyrics before anything is recorded.")
    html = _sub(html, "Usually within a few minutes of paying.", "Usually within a few minutes of approving your lyrics.")
    html = _rx(html, r'<div class="note"><p class="note-q">How much does it cost\?</p>.*?</div>', _FAQ_COST_REPLACEMENT)
    html = _sub(html, "not a paid purchase, just two", "just two")
    html = _sub(html, "It's included in what you already paid - completely free.", "It's included - completely free.")
    html = _sub(html, "no charge was made for it, and your song is safe either way.", "your song is safe either way.")

    # --- cajas de preview gratis y pago: fuera su contenido (el JS solo necesita que existan) ---
    html = _rx(
        html,
        r'<div class="player" id="preview-box">.*?(?=<div class="player" id="estado-box">)',
        '<div class="player" id="preview-box"></div>\n\n'
        '    <div class="player" id="pago-box"><div id="preview-player-container"></div></div>\n\n    ',
    )
    # --- sin pedido de resena en Trustpilot (para Etsy la resena va en Etsy) ---
    html = re.sub(r'<div id="review-box".*?</div>', "", html, count=1, flags=re.S)

    # --- JS: la sesion lleva el pedido de Etsy, los redirects vuelven a /etsy, y no hay pago/preview ---
    html = _sub(html, 'let sessionId = null;', 'let sessionId = null;\nwindow.ETSY_ORDER = null;')
    # ?session_id= invalido/vencido: nunca crear una sesion normal (con cobro) en esta pagina.
    html = _sub(
        html,
        "    const ok = await retomarSesion();\n    if (ok) return;\n",
        "    const ok = await retomarSesion();\n    if (ok) return;\n"
        '    if (!window.ETSY_ORDER) { window.location.href = "/etsy"; return; }\n',
    )
    html = _sub(html, 'fbp, lang: "en",', 'fbp, lang: "en", etsy_order: window.ETSY_ORDER,')
    html = _sub(html, 'window.location.href = "/?session_id="', 'window.location.href = "/etsy?session_id="')
    html = _sub(
        html,
        "} else if (data.generando_preview) {",
        '} else if (data.etsy_generando) {\n'
        '    $("chat").style.display = "none";\n'
        '    $("estado-box").style.display = "block";\n'
        '    iniciarPolling();\n'
        "  } else if (data.generando_preview) {",
    )
    i = html.index("let _sesionArrancada = false;")
    html = html[:i] + _ETSY_BOOT_JS

    # --- marcas de precio dinamico: no deberia quedar ninguna ---
    html = html.replace("___PRECIO_BADGE_DYNAMIC___", "").replace("___PRECIO_BADGE_WAS_DYNAMIC___", "")
    leftovers = re.findall(r"___[A-Z_]+___", html)
    if leftovers:
        raise _TemplateChanged(f"quedaron marcadores sin resolver: {sorted(set(leftovers))}")

    # --- red de seguridad: nada de dinero en el texto visible ni en meta/title ---
    texto = _visible_text(html) + " " + " ".join(_meta_leaks(html))
    leaks = sorted({m.group(0).lower() for m in _FORBIDDEN_VISIBLE.finditer(texto)})
    if leaks:
        raise _TemplateChanged(f"quedaron palabras de dinero en el texto visible: {leaks}")
    return html


ETSY_LANDING_HTML: str | None
ETSY_LANDING_ERROR: str | None
try:
    ETSY_LANDING_HTML = build_etsy_landing()
    ETSY_LANDING_ERROR = None
except Exception as e:  # noqa: BLE001 - cualquier fallo deshabilita /etsy, nunca tumba el sitio
    ETSY_LANDING_HTML = None
    ETSY_LANDING_ERROR = f"{type(e).__name__}: {e}"
    log.error("Landing /etsy deshabilitada: %s", ETSY_LANDING_ERROR)
