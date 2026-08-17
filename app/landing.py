"""
Landing page /cancion: la version "sin fricciones" que reemplaza al link a
Telegram para el trafico de anuncios (Marketplace, etc.). Todo en un solo
archivo HTML+CSS+JS embebido, servido como string (mismo patron que
/admin y /pago-exitoso en main.py) - no hace falta un build step ni
archivos estaticos aparte (la unica excepcion es la imagen de marca, servida
desde app/static/ - ver el mount en main.py).

Flujo en el navegador (sin pantalla de correo previa - eso es un click de
friccion que se elimino a proposito):
1. El chat con Claude se abre de una, apenas carga la pagina (mismo motor
   conversacional que el bot de Telegram). Claude pide el correo el mismo,
   como parte natural de la charla, cuando ya reunio los demas datos.
2. Cuando la letra queda aprobada, aparece el boton de pago (se abre en una
   pestaña NUEVA a proposito, para que esta pestaña se quede viva haciendo
   polling de /web/status).
3. En cuanto el pago se confirma y la cancion esta lista, aparece el link de
   descarga directo aca mismo - sin necesidad de instalar nada.

Bloque "Como funciona" y de muestras de audio: agregados para prevenir la
confusion detectada en produccion (ago 2026) de clientes que pensaban que la
LETRA escrita ya era "la cancion" - el explicador de 4 pasos deja clarisimo
que el audio cantado es un paso aparte, posterior al pago.

SAMPLE_AUDIO_URLS: lista de URLs de audio de muestra (canciones DEMO,
generadas especificamente para mostrar en la landing - nunca canciones de
clientes reales sin permiso). Vacia por default - la seccion de muestras se
oculta sola hasta que se carguen 1-2 URLs reales aca.

Pixel de Meta (ago 2026): el codigo base va en el <head> (PageView del lado
del navegador, y pone la cookie _fbp que se manda luego junto al fbclid al
crear la sesion - ver iniciar() mas abajo y app/meta_capi.py para el evento
"Purchase" server-side que se dispara al confirmarse el pago). Si
META_PIXEL_ID no esta configurado, no se inyecta nada - la landing funciona
igual, simplemente sin tracking de Meta.

Expansion a EE.UU. (ago 2026): LANDING_HTML_ES (la de siempre, sin cambios)
y LANDING_HTML_EN (nueva, para trafico de Google Ads en ingles - paga via
PayPal, ver app/paypal_client.py) son dos strings separados, no una sola
plantilla parametrizada - asi la version en espanol queda con exactamente el
mismo comportamiento de siempre, sin ningun riesgo de regresion por tocar
codigo compartido. main.py elige cual servir segun ?lang= en la URL o el
header Accept-Language (ver /cancion en main.py).
"""

from app.config import META_PIXEL_ID, BRAND_NAME_EN, BASE_URL, LAUNCH_PRICE_ENDS_AT


def pixel_script(track_calls: str, noscript_ev: str = "PageView") -> str:
    """Arma el bloque <script> del Pixel de Meta (bootstrap + init + los
    fbq('track', ...) que se le pasen) - se usa tanto para el PageView de la
    landing como para el Purchase de la pagina de pago exitoso (ver
    /pago-exitoso/web/{session_id} en main.py). Devuelve string vacio si
    META_PIXEL_ID no esta configurado, para que la pagina funcione igual
    sin tracking de Meta.

    ago 2026: esto quedo como la UNICA forma de medir conversiones - la
    Conversions API (server-side, app/meta_capi.py) no se pudo activar
    porque la cuenta de Meta Business de Diego tiene una restriccion vieja
    sin resolver (una app de hace años, ver conversacion). El Pixel del
    navegador es menos confiable (se pierde con bloqueadores de anuncios o
    si el cliente cierra la pestaña antes de que cargue), pero no depende
    de esa cuenta restringida - solo del ID publico del pixel."""
    if not META_PIXEL_ID:
        return ""
    return f"""
<script>
!function(f,b,e,v,n,t,s)
{{if(f.fbq)return;n=f.fbq=function(){{n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)}};
if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];
s.parentNode.insertBefore(t,s)}}(window, document,'script',
'https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '{META_PIXEL_ID}');
{track_calls}
</script>
<noscript><img height="1" width="1" style="display:none"
  src="https://www.facebook.com/tr?id={META_PIXEL_ID}&ev={noscript_ev}&noscript=1"/></noscript>
"""


_META_PIXEL_SCRIPT = pixel_script("fbq('track', 'PageView');")

# Reemplazado por SAMPLE_STYLES (grid de 6 generos, ago 2026) - se deja vacia
# para no mostrar una seccion duplicada/con audios que ya no existen con
# esos nombres.
SAMPLE_AUDIO_URLS: list[dict] = []

# Grid de 6 estilos musicales de muestra (ago 2026) - reemplaza/complementa
# la seccion anterior de 2 muestras genericas con un catalogo de generos
# reales, cada uno con su propia imagen + audio, para que el cliente vea de
# entrada la variedad de estilos que puede pedir y lo emocione mas la compra.
# Igual que SAMPLE_AUDIO_URLS: son canciones DEMO generadas para mostrar en
# la landing, nunca canciones de clientes reales.
# Imagenes en .jpg 400x400 (no los .png originales de ~2MB c/u) - en la
# landing se muestran como miniaturas de ~170px en un grid de 3 columnas,
# asi que 400x400 ya cubre pantallas retina de sobra sin pesar la carga.
SAMPLE_STYLES: list[dict] = [
    {"nombre": "Bachata", "imagen": "/static/bachata.jpg", "audio": "/static/bachata.mp3"},
    {"nombre": "Corrido Tumbado", "imagen": "/static/corrido_tumbado.jpg", "audio": "/static/corrido_tumbado.mp3"},
    {"nombre": "Norteño", "imagen": "/static/nortena.jpg", "audio": "/static/nortena.mp3"},
    {"nombre": "Cumbia", "imagen": "/static/cumbia.jpg", "audio": "/static/cumbia.mp3"},
    {"nombre": "Rock/Pop", "imagen": "/static/rock.jpg", "audio": "/static/rock.mp3"},
    {"nombre": "Balada", "imagen": "/static/balada.jpg", "audio": "/static/balada.mp3"},
]

_PASOS_HTML = """
<div class="card" id="pasos">
  <h2 class="pasos-titulo">¿Cómo funciona?</h2>
  <div class="paso">
    <div class="paso-num">1</div>
    <div><strong>Cuéntanos la historia</strong><br>
    <span class="paso-desc">Chateas con nosotros: para quién es, la ocasión, el estilo que prefieres.</span></div>
  </div>
  <div class="paso">
    <div class="paso-num">2</div>
    <div><strong>Aprueba la letra escrita</strong><br>
    <span class="paso-desc">Te mostramos el texto de la canción para que lo ajustes hasta que quede perfecto.</span></div>
  </div>
  <div class="paso">
    <div class="paso-num">3</div>
    <div><strong>Pagas y generamos el audio</strong><br>
    <span class="paso-desc">Con la letra aprobada, creamos la canción cantada de verdad (esto toma unos minutos).</span></div>
  </div>
  <div class="paso">
    <div class="paso-num">4</div>
    <div><strong>Recibes tu canción cantada</strong><br>
    <span class="paso-desc">Un archivo de audio listo para descargar y compartir - aquí mismo y por correo.</span></div>
  </div>
</div>
"""

if SAMPLE_AUDIO_URLS:
    _reproductores = "".join(
        f"""
        <div class="muestra">
          <p class="muestra-titulo">🎵 {m['titulo']}</p>
          <audio controls preload="none" src="{m['url']}"></audio>
        </div>
        """
        for m in SAMPLE_AUDIO_URLS
    )
    _MUESTRAS_HTML = f"""
    <div class="card" id="muestras">
      <h2 class="pasos-titulo">Escucha un ejemplo</h2>
      {_reproductores}
    </div>
    """
else:
    _MUESTRAS_HTML = ""

if SAMPLE_STYLES:
    _tarjetas_estilo = "".join(
        f"""
        <div class="estilo">
          <img src="{e['imagen']}" alt="{e['nombre']}" loading="lazy">
          <p class="estilo-nombre">{e['nombre']}</p>
          <audio controls preload="none" src="{e['audio']}"></audio>
        </div>
        """
        for e in SAMPLE_STYLES
    )
    _ESTILOS_HTML = f"""
    <div class="card" id="estilos">
      <h2 class="pasos-titulo">Algunos ejemplos de estilos</h2>
      <div class="estilos-grid">
        {_tarjetas_estilo}
      </div>
    </div>
    """
else:
    _ESTILOS_HTML = ""

# NOTA: LANDING_HTML_ES es un string NORMAL (no f-string) a proposito - tiene
# mucho CSS/JS con llaves "{ }" sueltas que romperian un f-string. El bloque
# de pasos/muestras se inserta con un .replace() simple sobre un marcador
# unico (___PASOS_Y_MUESTRAS___), ver el final del archivo.
LANDING_HTML_ES = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tu canción personalizada</title>
___META_PIXEL_SCRIPT___
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: linear-gradient(180deg, #fff7ed 0%, #fffaf5 100%);
    color: #292018; margin: 0; padding: 0 16px 40px;
    min-height: 100vh;
  }
  .wrap { max-width: 560px; margin: 0 auto; }
  .hero { width: 100%; border-radius: 0 0 20px 20px; overflow: hidden; margin: 0 -16px 16px; }
  .hero img { width: 100%; display: block; }
  h1 { font-size: 22px; text-align: center; margin: 8px 0 4px; }
  .sub { text-align: center; color: #7c6f5f; font-size: 14px; margin-bottom: 20px; }
  .card {
    background: white; border-radius: 16px; padding: 18px;
    box-shadow: 0 4px 20px rgba(180,120,60,0.10); margin-bottom: 16px;
  }
  input[type=text] {
    width: 100%; padding: 13px 14px; border-radius: 10px; border: 1px solid #e7dccb;
    font-size: 16px; margin-bottom: 0;
  }
  button {
    padding: 14px; border-radius: 10px; border: none;
    background: linear-gradient(135deg, #e8813a, #d96b2b); color: white;
    font-size: 16px; font-weight: 700; cursor: pointer;
  }
  button:disabled { opacity: 0.55; cursor: default; }
  #mensajes { max-height: 55vh; overflow-y: auto; padding: 4px 2px; margin-bottom: 12px; }
  .msg { padding: 10px 14px; border-radius: 14px; margin: 6px 0; font-size: 15px; line-height: 1.45; white-space: pre-wrap; }
  .msg.bot { background: #fff1e2; color: #4a3b26; border-bottom-left-radius: 4px; max-width: 92%; }
  .msg.user { background: #292018; color: white; margin-left: auto; border-bottom-right-radius: 4px; max-width: 85%; }
  .fila-input { display: flex; gap: 8px; }
  .fila-input input { margin-bottom: 0; }
  .fila-input button { width: auto; padding: 13px 18px; }
  #pago-box, #estado-box, #descarga-box { display: none; text-align: center; }
  #pago-box a, #descarga-box a {
    display: inline-block; margin-top: 10px; padding: 14px 26px;
    background: linear-gradient(135deg, #e8813a, #d96b2b); color: white;
    text-decoration: none; border-radius: 10px; font-weight: 700;
  }
  .spinner {
    display: inline-block; width: 16px; height: 16px; border: 2px solid #e7dccb;
    border-top-color: #d96b2b; border-radius: 50%; animation: girar 0.8s linear infinite;
    vertical-align: middle; margin-right: 8px;
  }
  @keyframes girar { to { transform: rotate(360deg); } }

  .chat-titulo { font-size: 16px; font-weight: 700; margin: 0 0 12px; text-align: center; }

  @keyframes rebotar {
    0%, 100% { transform: translateY(0); }
    30% { transform: translateY(-6px); }
    50% { transform: translateY(0); }
    65% { transform: translateY(-3px); }
    80% { transform: translateY(0); }
  }
  .fila-input button.rebote { animation: rebotar 0.6s ease; }

  /* Indicador de "escribiendo..." mientras se espera la respuesta - sin esto
     parece que el chat no hace nada mientras Claude procesa. */
  .msg.escribiendo { display: flex; align-items: center; gap: 4px; padding: 14px; }
  .punto {
    width: 7px; height: 7px; border-radius: 50%; background: #c7b8a0;
    animation: pulso 1.2s infinite ease-in-out;
  }
  .punto:nth-child(2) { animation-delay: 0.2s; }
  .punto:nth-child(3) { animation-delay: 0.4s; }
  @keyframes pulso {
    0%, 60%, 100% { opacity: 0.3; transform: scale(0.85); }
    30% { opacity: 1; transform: scale(1); }
  }
  footer { text-align: center; font-size: 12px; color: #b3a58d; margin-top: 24px; }
  footer a { color: #b3a58d; }

  .pasos-titulo { font-size: 16px; margin: 0 0 14px; text-align: center; }
  .paso { display: flex; gap: 12px; align-items: flex-start; margin-bottom: 14px; }
  .paso:last-child { margin-bottom: 0; }
  .paso-num {
    flex-shrink: 0; width: 28px; height: 28px; border-radius: 50%;
    background: linear-gradient(135deg, #e8813a, #d96b2b); color: white;
    font-weight: 700; font-size: 14px; display: flex; align-items: center;
    justify-content: center;
  }
  .paso-desc { font-size: 13px; color: #7c6f5f; }

  .muestra { margin-bottom: 14px; }
  .muestra:last-child { margin-bottom: 0; }
  .muestra-titulo { font-size: 14px; font-weight: 600; margin: 0 0 6px; }
  .muestra audio { width: 100%; }

  .estilos-grid {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px 8px;
  }
  .estilo { text-align: center; }
  .estilo img {
    width: 100%; aspect-ratio: 1 / 1; object-fit: cover; border-radius: 10px;
    display: block;
  }
  .estilo-nombre { font-size: 12px; font-weight: 600; margin: 6px 0 4px; }
  .estilo audio { width: 100%; height: 28px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="hero"><img src="/static/landing-hero.jpg" alt="Canción personalizada"></div>
  <h1>🎵 Tu canción personalizada</h1>
  <p class="sub">Una canción original, cantada de verdad, hecha con tu historia. Lista para descargar en minutos.</p>

  ___PASOS_Y_MUESTRAS___

  <div class="card" id="chat">
    <p class="chat-titulo">Comienza aquí...</p>
    <div id="mensajes"></div>
    <div class="fila-input">
      <input type="text" id="input-mensaje" placeholder="Escribe aquí..." disabled>
      <button id="btn-enviar" disabled>Enviar</button>
    </div>
  </div>

  <div class="card" id="pago-box">
    <p>✅ ¡Tu letra quedó lista! Cuando pagues, arrancamos la generación.</p>
    <a id="link-pago" href="#" target="_blank" rel="noopener">Pagar y generar mi canción</a>
    <p style="font-size:12px; color:#9a8b73; margin-top:14px;">
      Se abre en una pestaña nueva - no cierres esta, aquí va a aparecer tu canción
      apenas esté lista.
    </p>
  </div>

  <div class="card" id="estado-box">
    <p><span class="spinner"></span> Generando tu canción, esto toma unos minutos...</p>
  </div>

  <div class="card" id="descarga-box">
    <p>🎉 ¡Tu canción está lista!</p>
    <div id="links-descarga"></div>
    <p style="font-size:12px; color:#9a8b73; margin-top:14px;">
      También te la mandamos por correo como respaldo.
    </p>
  </div>

  <footer>
    <a href="/terminos">Términos y condiciones</a> · <a href="/privacidad">Aviso de privacidad</a>
  </footer>
</div>

<script>
let sessionId = null;
let pollTimer = null;

const $ = (id) => document.getElementById(id);

// Lee una cookie por nombre (se usa para _fbp, la que pone el Pixel de Meta
// del lado del navegador) - sin libreria externa, con RegExp simple.
function leerCookie(nombre) {
  const match = document.cookie.match(new RegExp("(?:^|; )" + nombre + "=([^;]*)"));
  return match ? decodeURIComponent(match[1]) : null;
}

function agregarMensaje(texto, quien) {
  const div = document.createElement("div");
  div.className = "msg " + quien;
  div.textContent = texto;
  $("mensajes").appendChild(div);
  $("mensajes").scrollTop = $("mensajes").scrollHeight;
}

async function iniciar() {
  const params = new URLSearchParams(window.location.search);

  // Si venimos de la pagina de "pago recibido" (boton "Ver el estado de mi
  // cancion"), el link ya trae el session_id de esa compra - hay que
  // retomarla en vez de crear una sesion nueva y perder el progreso.
  const sessionExistente = params.get("session_id");
  if (sessionExistente) {
    sessionId = sessionExistente;
    $("chat").style.display = "none";
    const ok = await retomarSesion();
    if (ok) return;
    // si la sesion no existe o ya no aplica, seguimos como si fuera nueva
    $("chat").style.display = "block";
  }

  const source = params.get("source") || null;
  const country = params.get("country") || null;
  // fbclid llega en el link del anuncio; fbp lo pone el Pixel de Meta (abajo
  // en el <head>) en cuanto carga la pagina - ambos se guardan con el pedido
  // para poder mandarle el evento "Purchase" a Meta cuando se pague (ver
  // app/meta_capi.py).
  const fbclid = params.get("fbclid") || null;
  const fbp = leerCookie("_fbp");

  const resp = await fetch("/web/session", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({source, country, fbclid, fbp}),
  });
  const data = await resp.json();
  sessionId = data.session_id;

  $("input-mensaje").disabled = false;
  $("btn-enviar").disabled = false;
  await enviarTurno("");
}

async function retomarSesion() {
  const resp = await fetch("/web/status?session_id=" + encodeURIComponent(sessionId));
  if (!resp.ok) return false;
  const data = await resp.json();

  if (data.delivered && data.audio_urls && data.audio_urls.length) {
    mostrarDescarga(data.audio_urls);
    return true;
  }
  if (data.step === "generando" || data.paid) {
    $("estado-box").style.display = "block";
    iniciarPolling();
    return true;
  }
  if (data.step === "esperando_pago" && data.payment_url) {
    $("link-pago").href = data.payment_url;
    $("pago-box").style.display = "block";
    iniciarPolling();
    return true;
  }
  return false; // no hay nada que retomar (ej. sesion muy vieja o invalida)
}

function mostrarDescarga(audioUrls) {
  $("estado-box").style.display = "none";
  $("pago-box").style.display = "none";
  const cont = $("links-descarga");
  cont.innerHTML = "";
  audioUrls.forEach((url, i) => {
    const a = document.createElement("a");
    a.href = url; a.target = "_blank"; a.rel = "noopener";
    a.textContent = audioUrls.length > 1 ? ("Descargar versión " + (i + 1)) : "Descargar mi canción";
    cont.appendChild(a);
    cont.appendChild(document.createElement("br"));
  });
  $("descarga-box").style.display = "block";
}

function mostrarEscribiendo() {
  const div = document.createElement("div");
  div.className = "msg bot escribiendo";
  div.id = "indicador-escribiendo";
  div.innerHTML = '<span class="punto"></span><span class="punto"></span><span class="punto"></span>';
  $("mensajes").appendChild(div);
  $("mensajes").scrollTop = $("mensajes").scrollHeight;
}

function ocultarEscribiendo() {
  const el = document.getElementById("indicador-escribiendo");
  if (el) el.remove();
}

async function enviarTurno(texto) {
  if (texto) agregarMensaje(texto, "user");
  $("btn-enviar").disabled = true;
  mostrarEscribiendo();

  let data;
  try {
    const resp = await fetch("/web/chat", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({session_id: sessionId, message: texto}),
    });
    data = await resp.json();
  } finally {
    ocultarEscribiendo();
  }

  (data.mensajes || []).forEach((m) => agregarMensaje(m, "bot"));

  if (data.listo_para_pagar && data.payment_url) {
    $("link-pago").href = data.payment_url;
    $("pago-box").style.display = "block";
    $("chat").style.display = "none";
    iniciarPolling();
  }
  $("btn-enviar").disabled = false;
}

// Boton "Enviar" hace un pequeño rebote cada pocos segundos cuando esta
// habilitado, para llamar la atencion de que hay que escribir algo (antes
// el chat se sentia "quieto" y no invitaba a interactuar).
setInterval(() => {
  const btn = $("btn-enviar");
  if (btn.disabled) return;
  btn.classList.add("rebote");
  setTimeout(() => btn.classList.remove("rebote"), 650);
}, 4000);

function iniciarPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    const resp = await fetch("/web/status?session_id=" + encodeURIComponent(sessionId));
    const data = await resp.json();
    if (data.step === "generando" || data.paid) {
      $("pago-box").style.display = "none";
      $("estado-box").style.display = "block";
    }
    if (data.delivered && data.audio_urls && data.audio_urls.length) {
      clearInterval(pollTimer);
      mostrarDescarga(data.audio_urls);
    }
  }, 5000);
}

$("btn-enviar").addEventListener("click", () => {
  const val = $("input-mensaje").value.trim();
  if (!val) return;
  $("input-mensaje").value = "";
  enviarTurno(val);
});
$("input-mensaje").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("btn-enviar").click();
});

// Al reproducir un audio de muestra (estilos o pasos), pausa cualquier otro
// que este sonando - sin esto se pueden solapar varias canciones a la vez.
document.querySelectorAll("audio").forEach((audio) => {
  audio.addEventListener("play", () => {
    document.querySelectorAll("audio").forEach((otro) => {
      if (otro !== audio) otro.pause();
    });
  });
});

iniciar();
</script>
</body>
</html>
"""

LANDING_HTML_ES = LANDING_HTML_ES.replace(
    "___PASOS_Y_MUESTRAS___", _PASOS_HTML + _ESTILOS_HTML + _MUESTRAS_HTML
)
LANDING_HTML_ES = LANDING_HTML_ES.replace("___META_PIXEL_SCRIPT___", _META_PIXEL_SCRIPT)


# ---------------------------------------------------------------------------
# Version en ingles (EE.UU., ago 2026) - traduccion de la landing de arriba,
# como un string separado a proposito (no una plantilla parametrizada
# compartida) para que LANDING_HTML_ES quede con exactamente el mismo
# comportamiento de siempre, sin ningun riesgo de regresion. Mismo CSS
# (el diseño no cambia por idioma), mismo flujo, mismo JS salvo por: manda
# lang="en" al crear la sesion, y los textos visibles (labels de descarga,
# boton "Send") estan en ingles. Fase 1: arranca el chat automatico igual
# que la version en espanol, tier="song" fijo - los botones de tier
# (song vs song+video) se agregan en la Fase 2 detras de ENABLE_VIDEO_TIER.
# ---------------------------------------------------------------------------
_META_PIXEL_SCRIPT_EN = pixel_script("fbq('track', 'PageView');")

# JSON-LD (schema.org) - Product+Offer (sin aggregateRating: no hay reviews
# reales todavia, no se inventan), FAQPage (espeja el bloque "Liner notes"
# de abajo palabra por palabra - si cambia el FAQ visible, hay que actualizar
# esto tambien), y Organization. No depende del dominio estar conectado
# todavia - BASE_URL ya viene armado desde config.py.
_JSON_LD_EN = f"""
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Personalized Song by Tunecraft",
  "description": "A real, sung song written from your story - the unique gift for her or him. You approve the lyrics before you pay.",
  "brand": {{"@type": "Brand", "name": "{BRAND_NAME_EN}"}},
  "offers": {{
    "@type": "Offer",
    "price": "27.00",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock",
    "url": "{BASE_URL}/"
  }}
}}
</script>
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {{"@type": "Question", "name": "What if I don't like the lyrics?", "acceptedAnswer": {{"@type": "Answer", "text": "You see the full lyrics before you pay anything. Want changes? We rewrite it together - as many times as it takes."}}}},
    {{"@type": "Question", "name": "How fast will it actually arrive?", "acceptedAnswer": {{"@type": "Answer", "text": "Usually within a few minutes of paying. It shows up right on this page, plus a backup copy by email."}}}},
    {{"@type": "Question", "name": "Is it really one-of-a-kind?", "acceptedAnswer": {{"@type": "Answer", "text": "Yes - every song is written from scratch, based on your story. No templates, no stock lyrics, no reused lines."}}}},
    {{"@type": "Question", "name": "What does it cost?", "acceptedAnswer": {{"@type": "Answer", "text": "$27, flat, for a limited launch window. You only pay once you've approved the lyrics - nothing before that."}}}}
  ]
}}
</script>
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "{BRAND_NAME_EN}",
  "url": "{BASE_URL}",
  "description": "Tunecraft writes and records real, sung personalized songs as unique gifts - built from your story, approved by you before you pay."
}}
</script>
"""

# ---------------------------------------------------------------------------
# LANDING_HTML_EN (ago 2026, v2 - rediseno completo) - concepto visual:
# "mixtape personal" (cassette + notas escritas a mano), elegido a proposito
# para alejarse del look generico "crema + serif + terracota" que cualquier
# IA produce por default. Estructura pensada para trafico frio que busca
# "unique gift for her/him" en Google Ads: hero -> como funciona (compacto)
# -> chat (el CTA real) -> prueba social honesta -> muestras de generos ->
# FAQ -> footer. Ver conversacion completa para el detalle de cada decision
# (por que cassette, por que sin fake scarcity, por que el countdown esta
# atado a LAUNCH_PRICE_ENDS_AT real en vez de ser decorativo).
#
# Fuentes: Fraunces (display, con caracter - nada de Playfair/Inter genericos),
# Caveat (acentos escritos a mano, ties directo al concepto de "nota en la
# cinta"), Work Sans (cuerpo). Via Google Fonts CDN normal - a diferencia del
# preview en Artifact (que necesito inlinear como data URI por el CSP del
# sandbox), esta pagina la sirve FastAPI a navegadores reales, asi que un
# link normal a fonts.googleapis.com es lo correcto (mas rapido, cacheado
# globalmente, sin inflar el HTML con ~250KB de fuentes inlineadas).
#
# NOTA: LANDING_HTML_EN es un string NORMAL (no f-string) por el mismo motivo
# que LANDING_HTML_ES - CSS/JS con demasiadas llaves sueltas. Los markers
# ___BRAND___, ___META_PIXEL_SCRIPT___, ___JSON_LD___ y
# ___LAUNCH_PRICE_ENDS_AT_ISO___ se sustituyen al final del archivo.
# ---------------------------------------------------------------------------
LANDING_HTML_EN = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unique Personalized Song Gift | ___BRAND___</title>
<meta name="description" content="Give the unique gift that's never existed before: a real, sung song written from your story. Approve the lyrics before you pay. $27 launch price, ready in minutes.">
<link rel="canonical" href="___CANONICAL_URL___">
<meta property="og:title" content="___BRAND___ - The Unique Gift That's Never Existed Until Now">
<meta property="og:description" content="A real, sung song written from your story. Approve the lyrics before you pay. $27 launch price.">
<meta property="og:type" content="website">
<meta property="og:url" content="___CANONICAL_URL___">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,900&family=Caveat:wght@600&family=Work+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
___JSON_LD___
___META_PIXEL_SCRIPT___
<style>
  :root {
    --ink: #16110d; --ink-raised: #1e1710; --paper: #efe4cc; --paper-dim: #e4d7ba;
    --amber: #e8a23a; --amber-bright: #f3b559; --rec: #d14b3e;
    --ink-soft: #b7a88f; --ink-faint: #7d715d; --paper-ink: #241a10;
    --paper-ink-soft: #6b5c42; --line: rgba(239,228,204,0.14);
  }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body { margin: 0; background: var(--ink); color: var(--paper); font-family: 'Work Sans', -apple-system, sans-serif; -webkit-font-smoothing: antialiased; }
  .wrap { max-width: 560px; margin: 0 auto; padding: 0 20px; }
  ::selection { background: var(--amber); color: var(--ink); }
  a { color: inherit; }
  h1, h2, h3 { font-family: 'Fraunces', serif; font-variation-settings: 'opsz' 40; text-wrap: balance; margin: 0; }
  .eyebrow { font-family: 'Caveat', cursive; font-size: 22px; color: var(--amber-bright); display: inline-block; transform: rotate(-2deg); }

  .hero { padding: 56px 0 40px; text-align: center; position: relative; overflow: hidden; }
  .hero::before { content: ""; position: absolute; inset: 0; background: radial-gradient(60% 50% at 50% 0%, rgba(232,162,58,0.16), transparent 70%); pointer-events: none; }
  .brand-row { display: flex; align-items: center; justify-content: center; gap: 8px; margin-bottom: 34px; position: relative; z-index: 1; }
  .brand-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--rec); box-shadow: 0 0 8px var(--rec); }
  .brand-name { font-family: 'Fraunces', serif; font-weight: 600; font-size: 15px; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-soft); }

  .cassette-stage { position: relative; z-index: 1; margin: 0 0 30px; }
  .cassette { width: 230px; margin: 0 auto; filter: drop-shadow(0 18px 30px rgba(0,0,0,0.45)); }
  .reel { animation: spin 6s linear infinite; }
  @media (prefers-reduced-motion: reduce) { .reel { animation: none; } }
  @keyframes spin { to { transform: rotate(360deg); } }

  .hero h1 { font-size: 34px; line-height: 1.08; font-weight: 900; color: var(--paper); margin: 0 0 14px; position: relative; z-index: 1; }
  .hero h1 em { font-style: normal; color: var(--amber-bright); }
  .hero .sub { font-size: 16px; line-height: 1.55; color: var(--ink-soft); max-width: 400px; margin: 0 auto 22px; position: relative; z-index: 1; }

  .price-row { display: flex; align-items: baseline; justify-content: center; gap: 10px; margin: 0 0 16px; position: relative; z-index: 1; }
  .price-was { font-family: 'Fraunces', serif; font-size: 18px; color: var(--ink-faint); text-decoration: line-through; text-decoration-color: var(--rec); }
  .price-now { font-family: 'Fraunces', serif; font-weight: 900; font-size: 30px; color: var(--amber-bright); }
  .price-label { font-size: 11px; color: var(--ink-soft); text-transform: uppercase; letter-spacing: 0.08em; }

  .odometer { display: flex; align-items: center; justify-content: center; gap: 10px; margin: 0 0 22px; position: relative; z-index: 1; }
  .odo-caption { font-family: 'Caveat', cursive; font-size: 16px; color: var(--ink-soft); width: 100%; text-align: center; margin: 0 0 8px; transform: rotate(-1deg); }
  .odo-unit { display: flex; flex-direction: column; align-items: center; gap: 5px; }
  .odo-digits { display: flex; gap: 3px; }
  .odo-digit {
    font-family: ui-monospace, 'SF Mono', Menlo, Consolas, monospace; font-weight: 700; font-size: 21px; line-height: 1;
    background: linear-gradient(180deg, #2a2018, #1b140e); color: var(--amber-bright);
    text-shadow: 0 0 6px rgba(232,162,58,0.55); border: 1px solid rgba(239,228,204,0.12);
    border-radius: 4px; width: 24px; padding: 8px 0; text-align: center; position: relative;
  }
  .odo-digit::after { content: ""; position: absolute; left: 0; right: 0; top: 50%; height: 1px; background: rgba(0,0,0,0.35); }
  .odo-sep { font-family: ui-monospace, monospace; color: var(--ink-faint); font-size: 18px; align-self: center; padding-top: 8px; }
  .odo-label { font-size: 9.5px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-faint); }

  .trust-row { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin: 0 0 26px; position: relative; z-index: 1; }
  .trust-pill { font-size: 12.5px; font-weight: 600; color: var(--ink); background: var(--paper); border-radius: 7px; padding: 7px 12px; display: flex; align-items: center; gap: 5px; }
  .trust-pill b { color: var(--rec); }

  .tag-row { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px 6px; position: relative; z-index: 1; }
  .tag { font-family: 'Caveat', cursive; font-size: 17px; color: var(--ink); background: var(--amber); padding: 3px 12px 5px; border-radius: 3px; transform: rotate(-3deg); }
  .tag:nth-child(2n) { transform: rotate(2deg); background: var(--paper); }
  .tag:nth-child(3n) { transform: rotate(-1deg); }

  section { padding: 44px 0; border-top: 1px solid var(--line); }
  .kicker { font-family: 'Caveat', cursive; color: var(--amber-bright); font-size: 19px; display: block; margin-bottom: 2px; transform: rotate(-1deg); }
  .section-title { font-size: 24px; font-weight: 700; color: var(--paper); margin-bottom: 22px; }

  .track { display: flex; gap: 16px; padding: 16px 0; border-bottom: 1px dashed var(--line); align-items: flex-start; }
  .track:last-child { border-bottom: none; }
  .track-num { font-family: 'Fraunces', serif; font-weight: 600; font-size: 15px; color: var(--ink-faint); font-variant-numeric: tabular-nums; width: 24px; flex-shrink: 0; padding-top: 2px; }
  .track-body h3 { font-size: 16px; color: var(--paper); margin-bottom: 4px; }
  .track-body p { font-size: 13.5px; color: var(--ink-soft); margin: 0; line-height: 1.5; }

  .player { background: var(--paper); border-radius: 18px; padding: 20px; color: var(--paper-ink); box-shadow: 0 20px 50px rgba(0,0,0,0.35); }
  .player-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
  .player-head .led { display: flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--paper-ink-soft); }
  .player-head .led .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--rec); animation: pulse 1.6s infinite ease-in-out; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
  .chat-titulo { font-size: 17px; font-weight: 700; margin: 0 0 3px; }
  .chat-sub { font-size: 12.5px; color: var(--paper-ink-soft); margin: 0 0 14px; }

  #mensajes { max-height: 50vh; overflow-y: auto; padding: 2px 2px 4px; margin-bottom: 12px; }
  .msg { padding: 10px 14px; border-radius: 14px; margin: 6px 0; font-size: 14.5px; line-height: 1.45; white-space: pre-wrap; }
  .msg.bot { background: rgba(36,26,16,0.06); color: var(--paper-ink); border-bottom-left-radius: 4px; max-width: 92%; }
  .msg.user { background: var(--ink); color: var(--paper); margin-left: auto; border-bottom-right-radius: 4px; max-width: 85%; }

  input[type=text] { width: 100%; padding: 18px 16px; border-radius: 12px; border: 1px solid rgba(36,26,16,0.15); font-size: 16px; font-family: 'Work Sans', sans-serif; background: #fff; }
  .fila-input { display: flex; flex-direction: column; gap: 10px; }
  .fila-input input { margin-bottom: 0; }
  button { padding: 16px; border-radius: 12px; border: none; background: var(--ink); color: var(--paper); font-size: 15px; font-weight: 700; cursor: pointer; font-family: 'Work Sans', sans-serif; }
  button:disabled { opacity: 0.4; cursor: default; }
  .fila-input button { width: 100%; }

  @keyframes rebotar { 0%, 100% { transform: translateY(0); } 30% { transform: translateY(-6px); } 50% { transform: translateY(0); } 65% { transform: translateY(-3px); } 80% { transform: translateY(0); } }
  .fila-input button.rebote { animation: rebotar 0.6s ease; }

  .msg.escribiendo { display: flex; align-items: center; gap: 4px; padding: 14px; }
  .punto { width: 6px; height: 6px; border-radius: 50%; background: var(--paper-ink-soft); animation: punto 1.2s infinite ease-in-out; }
  .punto:nth-child(2) { animation-delay: 0.2s; }
  .punto:nth-child(3) { animation-delay: 0.4s; }
  @keyframes punto { 0%, 60%, 100% { opacity: 0.3; transform: scale(0.85); } 30% { opacity: 1; transform: scale(1); } }

  #pago-box, #estado-box, #descarga-box { display: none; text-align: center; }
  #pago-box a, #descarga-box a { display: inline-block; margin-top: 12px; padding: 15px 28px; background: var(--rec); color: #fff5ee; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 15px; }
  .spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid rgba(36,26,16,0.15); border-top-color: var(--rec); border-radius: 50%; animation: girar 0.8s linear infinite; vertical-align: middle; margin-right: 8px; }
  @keyframes girar { to { transform: rotate(360deg); } }

  .reaction { padding: 18px 0; border-bottom: 1px dashed var(--line); }
  .reaction:last-child { border-bottom: none; }
  .reaction-quote { font-family: 'Fraunces', serif; font-size: 17px; line-height: 1.4; color: var(--paper); margin: 0 0 10px; font-style: italic; }
  .reaction-quote::before { content: "\\201C"; color: var(--amber); }
  .reaction-quote::after { content: "\\201D"; color: var(--amber); }
  .reaction-who { font-size: 12.5px; color: var(--ink-soft); }
  .reaction-who b { color: var(--paper); font-weight: 700; }
  .reaction-note { font-size: 12px; color: var(--ink-faint); margin-top: 24px; padding-top: 14px; border-top: 1px solid var(--line); line-height: 1.5; }

  .sample-list { display: flex; flex-direction: column; }
  .sample { display: grid; grid-template-columns: 46px 1fr auto; align-items: center; gap: 14px; padding: 12px 0; border-bottom: 1px dashed var(--line); }
  .sample:last-child { border-bottom: none; }
  .sample img { width: 46px; height: 46px; border-radius: 8px; object-fit: cover; display: block; }
  .sample-name { font-size: 14.5px; font-weight: 600; color: var(--paper); margin: 0 0 2px; }
  .sample-genre { font-size: 12px; color: var(--ink-faint); margin: 0; }
  .sample audio { height: 30px; width: 108px; }
  .sample.soon { opacity: 0.55; }
  .sample-soon-tag { font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--ink-faint); border: 1px dashed var(--line); border-radius: 6px; padding: 5px 8px; white-space: nowrap; }

  .note { padding: 16px 0; border-bottom: 1px dashed var(--line); }
  .note:last-child { border-bottom: none; }
  .note-q { font-size: 15px; font-weight: 700; color: var(--paper); margin: 0 0 5px; }
  .note-a { font-size: 13.5px; color: var(--ink-soft); margin: 0; line-height: 1.55; }

  footer { text-align: center; font-size: 12px; color: var(--ink-faint); padding: 30px 0 46px; }
  footer a { color: var(--ink-soft); text-decoration: underline; text-underline-offset: 2px; }
  footer .fbrand { font-family: 'Fraunces', serif; font-weight: 700; color: var(--ink-soft); }
</style>
</head>
<body>
<div class="wrap">

  <div class="hero">
    <div class="brand-row">
      <span class="brand-dot"></span>
      <span class="brand-name">___BRAND___</span>
    </div>

    <div class="cassette-stage">
      <svg class="cassette" viewBox="0 0 230 148" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="1" y="1" width="228" height="146" rx="14" fill="#e4d7ba" stroke="#241a10" stroke-opacity="0.15" stroke-width="1.5"/>
        <rect x="16" y="16" width="198" height="62" rx="6" fill="#241a10"/>
        <circle cx="66" cy="47" r="20" fill="#e4d7ba" opacity="0.9"/>
        <circle cx="164" cy="47" r="20" fill="#e4d7ba" opacity="0.9"/>
        <g class="reel" style="transform-origin: 66px 47px;">
          <circle cx="66" cy="47" r="20" fill="none" stroke="#241a10" stroke-width="1" stroke-opacity="0.5"/>
          <circle cx="66" cy="47" r="6" fill="#241a10"/>
          <circle cx="66" cy="47" r="14" fill="none" stroke="#241a10" stroke-opacity="0.35" stroke-width="6" stroke-dasharray="2 5"/>
        </g>
        <g class="reel" style="transform-origin: 164px 47px;">
          <circle cx="164" cy="47" r="20" fill="none" stroke="#241a10" stroke-width="1" stroke-opacity="0.5"/>
          <circle cx="164" cy="47" r="6" fill="#241a10"/>
          <circle cx="164" cy="47" r="14" fill="none" stroke="#241a10" stroke-opacity="0.35" stroke-width="6" stroke-dasharray="2 5"/>
        </g>
        <line x1="86" y1="47" x2="144" y2="47" stroke="#7d715d" stroke-width="1"/>
        <rect x="16" y="90" width="198" height="42" rx="4" fill="#f6efdd" stroke="#241a10" stroke-opacity="0.1" stroke-width="1"/>
        <text x="115" y="112" text-anchor="middle" font-family="Caveat, cursive" font-size="17" fill="#c0392b" transform="rotate(-1 115 112)">for the one you love</text>
        <line x1="30" y1="122" x2="200" y2="122" stroke="#241a10" stroke-opacity="0.12" stroke-width="1"/>
        <circle cx="10" cy="10" r="2.4" fill="#241a10" opacity="0.3"/>
        <circle cx="220" cy="10" r="2.4" fill="#241a10" opacity="0.3"/>
        <circle cx="10" cy="138" r="2.4" fill="#241a10" opacity="0.3"/>
        <circle cx="220" cy="138" r="2.4" fill="#241a10" opacity="0.3"/>
      </svg>
    </div>

    <h1>A gift that's<br><em>never existed</em><br>until now.</h1>
    <p class="sub">The most unique gift you'll ever give - a real song written and sung from your story. You approve every lyric before you pay a cent.</p>

    <div class="price-row">
      <span class="price-was">$39.90</span>
      <span class="price-now">$27</span>
      <span class="price-label">launch price</span>
    </div>

    <div class="odometer">
      <p class="odo-caption" style="position:absolute; margin-top:-26px;">launch price ends in</p>
      <div class="odo-unit"><div class="odo-digits"><span class="odo-digit" id="od-d0">0</span><span class="odo-digit" id="od-d1">0</span></div><span class="odo-label">days</span></div>
      <span class="odo-sep">:</span>
      <div class="odo-unit"><div class="odo-digits"><span class="odo-digit" id="od-h0">0</span><span class="odo-digit" id="od-h1">0</span></div><span class="odo-label">hrs</span></div>
      <span class="odo-sep">:</span>
      <div class="odo-unit"><div class="odo-digits"><span class="odo-digit" id="od-m0">0</span><span class="odo-digit" id="od-m1">0</span></div><span class="odo-label">min</span></div>
      <span class="odo-sep">:</span>
      <div class="odo-unit"><div class="odo-digits"><span class="odo-digit" id="od-s0">0</span><span class="odo-digit" id="od-s1">0</span></div><span class="odo-label">sec</span></div>
    </div>

    <div class="trust-row">
      <span class="trust-pill">Approved before you pay</span>
      <span class="trust-pill">Ready in minutes</span>
    </div>

    <div class="tag-row">
      <span class="tag">for her</span>
      <span class="tag">for him</span>
      <span class="tag">anniversary</span>
      <span class="tag">birthday</span>
      <span class="tag">just because</span>
    </div>
  </div>

  <section id="pasos-compact">
    <span class="kicker">Side A</span>
    <h2 class="section-title">How this actually works</h2>
    <div class="track">
      <div class="track-num">01</div>
      <div class="track-body"><h3>Tell us everything</h3><p>Who it's for, the inside jokes, the little things only you'd know.</p></div>
    </div>
    <div class="track">
      <div class="track-num">02</div>
      <div class="track-body"><h3>Read the lyrics first</h3><p>We write it, you approve it - line by line, before any money moves.</p></div>
    </div>
    <div class="track">
      <div class="track-num">03</div>
      <div class="track-body"><h3>It gets recorded</h3><p>Real vocals, real instruments, built around your exact words.</p></div>
    </div>
    <div class="track">
      <div class="track-num">04</div>
      <div class="track-body"><h3>Press play together</h3><p>Download it, send it, watch their face when they realize what it is.</p></div>
    </div>
  </section>

  <section id="chat-section">
    <span class="kicker">Now recording</span>
    <h2 class="section-title">Let's write it</h2>

    <div class="player" id="chat">
      <div class="player-head">
        <span class="led"><span class="dot"></span>Live</span>
        <span class="led">___BRAND___</span>
      </div>
      <p class="chat-titulo">Who's this song for?</p>
      <p class="chat-sub">Takes about 2 minutes. No account, no commitment yet.</p>
      <div id="mensajes"></div>
      <div class="fila-input">
        <input type="text" id="input-mensaje" placeholder="Type here..." disabled>
        <button id="btn-enviar" disabled>Send</button>
      </div>
    </div>

    <div class="player" id="pago-box">
      <p style="margin-top:0;">✅ Your lyrics are ready! Once you pay, we start recording.</p>
      <a id="link-pago" href="#" target="_blank" rel="noopener">Pay $27 &amp; Create My Song</a>
      <p style="font-size:12px; color:var(--paper-ink-soft); margin-top:14px; margin-bottom:0;">
        Opens in a new tab — don't close this one, your song will land right here.
      </p>
    </div>

    <div class="player" id="estado-box">
      <p style="margin-top:0;"><span class="spinner"></span>Recording your song — this takes a few minutes...</p>
      <p style="font-size:12px; color:var(--paper-ink-soft); margin-bottom:0;">
        We'll also email it to you, so you're covered even if you close this tab.
      </p>
    </div>

    <div class="player" id="descarga-box">
      <p style="margin-top:0;">🎉 It's ready!</p>
      <div id="links-descarga"></div>
      <p style="font-size:12px; color:var(--paper-ink-soft); margin-top:14px; margin-bottom:0;">
        We also sent it to your email as a backup.
      </p>
    </div>
  </section>

  <section id="reactions">
    <span class="kicker">Fresh off the tape</span>
    <h2 class="section-title">First reactions</h2>
    <div class="reaction">
      <p class="reaction-quote">It said what I wanted to say almost word for word. It didn't feel like a gift someone made for me — it felt like something I would've written myself, if I could write like that.</p>
      <p class="reaction-who"><b>Ana</b>, tried the flow before launch</p>
    </div>
    <div class="reaction">
      <p class="reaction-quote">I've given a lot of gifts. I've never given one that made someone go quiet like that. It felt entirely ours.</p>
      <p class="reaction-who"><b>Miguel</b>, tried the flow before launch</p>
    </div>
    <p class="reaction-note">Ana and Miguel tested ___BRAND___ before public launch — not a paid purchase, just two of the first people to go through the real flow and hear the result.</p>
  </section>

  <section id="samples">
    <span class="kicker">Side B</span>
    <h2 class="section-title">Six sounds, one story</h2>
    <p style="font-size:13.5px; color:var(--ink-soft); margin:-10px 0 20px;">Whatever their taste, we can write and record it that way. Samples landing soon for each style.</p>
    <div class="sample-list">
      <div class="sample soon">
        <img src="/static/rock.jpg" alt="Hip-Hop / R&amp;B">
        <div><p class="sample-name">Hip-Hop / R&amp;B</p><p class="sample-genre">America's #1 streamed genre</p></div>
        <span class="sample-soon-tag">Sample soon</span>
      </div>
      <div class="sample soon">
        <img src="/static/rock.jpg" alt="Pop / Rock">
        <div><p class="sample-name">Pop / Rock</p><p class="sample-genre">Anthemic · Radio-ready</p></div>
        <span class="sample-soon-tag">Sample soon</span>
      </div>
      <div class="sample soon">
        <img src="/static/bachata.jpg" alt="Latin">
        <div><p class="sample-name">Latin</p><p class="sample-genre">Reggaetón-flavored</p></div>
        <span class="sample-soon-tag">Sample soon</span>
      </div>
      <div class="sample soon">
        <img src="/static/bachata.jpg" alt="Country">
        <div><p class="sample-name">Country</p><p class="sample-genre">Storytelling at its core</p></div>
        <span class="sample-soon-tag">Sample soon</span>
      </div>
      <div class="sample soon">
        <img src="/static/rock.jpg" alt="Metal">
        <div><p class="sample-name">Metal</p><p class="sample-genre">Heavy · Unapologetic</p></div>
        <span class="sample-soon-tag">Sample soon</span>
      </div>
      <div class="sample soon">
        <img src="/static/balada.jpg" alt="Big Band">
        <div><p class="sample-name">Big Band</p><p class="sample-genre">Sinatra-style crooner</p></div>
        <span class="sample-soon-tag">Sample soon</span>
      </div>
    </div>
  </section>

  <section id="faq">
    <span class="kicker">Before you ask</span>
    <h2 class="section-title">Liner notes</h2>
    <div class="note"><p class="note-q">What if I don't like the lyrics?</p><p class="note-a">You see the full lyrics before you pay anything. Want changes? We rewrite it together — as many times as it takes.</p></div>
    <div class="note"><p class="note-q">How fast will it actually arrive?</p><p class="note-a">Usually within a few minutes of paying. It shows up right on this page, plus a backup copy by email.</p></div>
    <div class="note"><p class="note-q">Is it really one-of-a-kind?</p><p class="note-a">Yes — every song is written from scratch, based on your story. No templates, no stock lyrics, no reused lines.</p></div>
    <div class="note"><p class="note-q">What does it cost?</p><p class="note-a">$27 for a limited launch window (see the price above). You only pay once you've approved the lyrics.</p></div>
  </section>

  <footer>
    <span class="fbrand">___BRAND___</span> · <a href="/terms">Terms &amp; Conditions</a> · <a href="/privacy">Privacy Notice</a>
  </footer>
</div>

<script>
let sessionId = null;
let pollTimer = null;
const $ = (id) => document.getElementById(id);

// Countdown atado a la fecha REAL de fin del precio de lanzamiento
// (config.py -> LAUNCH_PRICE_ENDS_AT), inyectada por el servidor - el precio
// que se muestra contando y el precio que realmente se cobra (get_precio_pais
// en config.py) son siempre el mismo numero.
const LAUNCH_PRICE_ENDS_AT = new Date("___LAUNCH_PRICE_ENDS_AT_ISO___");

function actualizarOdometro() {
  const restante = Math.max(0, LAUNCH_PRICE_ENDS_AT - Date.now());
  const dias = Math.floor(restante / 86400000);
  const horas = Math.floor((restante % 86400000) / 3600000);
  const min = Math.floor((restante % 3600000) / 60000);
  const seg = Math.floor((restante % 60000) / 1000);
  const pad = (n) => String(n).padStart(2, "0");
  const partes = { d: pad(Math.min(dias, 99)), h: pad(horas), m: pad(min), s: pad(seg) };
  const setDigits = (prefix, value) => {
    const [a, b] = value.split("");
    const elA = $(prefix + "0"), elB = $(prefix + "1");
    if (elA) elA.textContent = a;
    if (elB) elB.textContent = b;
  };
  setDigits("od-d", partes.d);
  setDigits("od-h", partes.h);
  setDigits("od-m", partes.m);
  setDigits("od-s", partes.s);
  if (restante <= 0 && pollTimerOdo) clearInterval(pollTimerOdo);
}
let pollTimerOdo = setInterval(actualizarOdometro, 1000);
actualizarOdometro();

function leerCookie(nombre) {
  const match = document.cookie.match(new RegExp("(?:^|; )" + nombre + "=([^;]*)"));
  return match ? decodeURIComponent(match[1]) : null;
}

function agregarMensaje(texto, quien) {
  const div = document.createElement("div");
  div.className = "msg " + quien;
  div.textContent = texto;
  $("mensajes").appendChild(div);
  $("mensajes").scrollTop = $("mensajes").scrollHeight;
}

async function iniciar() {
  const params = new URLSearchParams(window.location.search);
  const sessionExistente = params.get("session_id");
  if (sessionExistente) {
    sessionId = sessionExistente;
    $("chat-section").style.display = "none";
    const ok = await retomarSesion();
    if (ok) return;
    $("chat-section").style.display = "block";
  }
  const source = params.get("source") || null;
  const country = params.get("country") || null;
  const fbclid = params.get("fbclid") || null;
  const fbp = leerCookie("_fbp");
  const resp = await fetch("/web/session", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({source, country, fbclid, fbp, lang: "en"}),
  });
  const data = await resp.json();
  sessionId = data.session_id;
  $("input-mensaje").disabled = false;
  $("btn-enviar").disabled = false;
  await enviarTurno("");
}

async function retomarSesion() {
  const resp = await fetch("/web/status?session_id=" + encodeURIComponent(sessionId));
  if (!resp.ok) return false;
  const data = await resp.json();
  if (data.delivered && data.audio_urls && data.audio_urls.length) { mostrarDescarga(data.audio_urls); return true; }
  if (data.step === "generando" || data.paid) { $("estado-box").style.display = "block"; iniciarPolling(); return true; }
  if (data.step === "esperando_pago" && data.payment_url) { $("link-pago").href = data.payment_url; $("pago-box").style.display = "block"; iniciarPolling(); return true; }
  return false;
}

function mostrarDescarga(audioUrls) {
  $("estado-box").style.display = "none";
  $("pago-box").style.display = "none";
  const cont = $("links-descarga");
  cont.innerHTML = "";
  audioUrls.forEach((url, i) => {
    const a = document.createElement("a");
    a.href = url; a.target = "_blank"; a.rel = "noopener";
    a.textContent = audioUrls.length > 1 ? ("Download version " + (i + 1)) : "Download my song";
    cont.appendChild(a);
    cont.appendChild(document.createElement("br"));
  });
  $("descarga-box").style.display = "block";
}

function mostrarEscribiendo() {
  const div = document.createElement("div");
  div.className = "msg bot escribiendo";
  div.id = "indicador-escribiendo";
  div.innerHTML = '<span class="punto"></span><span class="punto"></span><span class="punto"></span>';
  $("mensajes").appendChild(div);
  $("mensajes").scrollTop = $("mensajes").scrollHeight;
}
function ocultarEscribiendo() { const el = document.getElementById("indicador-escribiendo"); if (el) el.remove(); }

async function enviarTurno(texto) {
  if (texto) agregarMensaje(texto, "user");
  $("btn-enviar").disabled = true;
  mostrarEscribiendo();
  let data;
  try {
    const resp = await fetch("/web/chat", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({session_id: sessionId, message: texto}),
    });
    data = await resp.json();
  } finally { ocultarEscribiendo(); }
  (data.mensajes || []).forEach((m) => agregarMensaje(m, "bot"));
  if (data.listo_para_pagar && data.payment_url) {
    $("link-pago").href = data.payment_url;
    $("pago-box").style.display = "block";
    $("chat").style.display = "none";
    iniciarPolling();
  }
  $("btn-enviar").disabled = false;
}

setInterval(() => {
  const btn = $("btn-enviar");
  if (btn.disabled) return;
  btn.classList.add("rebote");
  setTimeout(() => btn.classList.remove("rebote"), 650);
}, 4000);

function iniciarPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    const resp = await fetch("/web/status?session_id=" + encodeURIComponent(sessionId));
    const data = await resp.json();
    if (data.step === "generando" || data.paid) { $("pago-box").style.display = "none"; $("estado-box").style.display = "block"; }
    if (data.delivered && data.audio_urls && data.audio_urls.length) { clearInterval(pollTimer); mostrarDescarga(data.audio_urls); }
  }, 5000);
}

$("btn-enviar").addEventListener("click", () => {
  const val = $("input-mensaje").value.trim();
  if (!val) return;
  $("input-mensaje").value = "";
  enviarTurno(val);
});
$("input-mensaje").addEventListener("keydown", (e) => { if (e.key === "Enter") $("btn-enviar").click(); });

document.querySelectorAll("audio").forEach((audio) => {
  audio.addEventListener("play", () => {
    document.querySelectorAll("audio").forEach((otro) => { if (otro !== audio) otro.pause(); });
  });
});

iniciar();
</script>
</body>
</html>
"""

LANDING_HTML_EN = LANDING_HTML_EN.replace("___META_PIXEL_SCRIPT___", _META_PIXEL_SCRIPT_EN)
LANDING_HTML_EN = LANDING_HTML_EN.replace("___JSON_LD___", _JSON_LD_EN)
LANDING_HTML_EN = LANDING_HTML_EN.replace("___CANONICAL_URL___", f"{BASE_URL}/")
LANDING_HTML_EN = LANDING_HTML_EN.replace("___LAUNCH_PRICE_ENDS_AT_ISO___", LAUNCH_PRICE_ENDS_AT)
LANDING_HTML_EN = LANDING_HTML_EN.replace("___BRAND___", BRAND_NAME_EN)
