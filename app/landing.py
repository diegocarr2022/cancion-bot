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
"""

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
SAMPLE_STYLES: list[dict] = [
    {"nombre": "Bachata", "imagen": "/static/bachata.png", "audio": "/static/bachata.mp3"},
    {"nombre": "Corrido Tumbado", "imagen": "/static/corrido_tumbado.png", "audio": "/static/corrido_tumbado.mp3"},
    {"nombre": "Norteño", "imagen": "/static/nortena.png", "audio": "/static/nortena.mp3"},
    {"nombre": "Cumbia", "imagen": "/static/cumbia.png", "audio": "/static/cumbia.mp3"},
    {"nombre": "Rock/Pop", "imagen": "/static/rock.png", "audio": "/static/rock.mp3"},
    {"nombre": "Balada", "imagen": "/static/balada.png", "audio": "/static/balada.mp3"},
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

# NOTA: LANDING_HTML es un string NORMAL (no f-string) a proposito - tiene
# mucho CSS/JS con llaves "{ }" sueltas que romperian un f-string. El bloque
# de pasos/muestras se inserta con un .replace() simple sobre un marcador
# unico (___PASOS_Y_MUESTRAS___), ver el final del archivo.
LANDING_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tu canción personalizada</title>
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

  const resp = await fetch("/web/session", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({source, country}),
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

LANDING_HTML = LANDING_HTML.replace(
    "___PASOS_Y_MUESTRAS___", _PASOS_HTML + _ESTILOS_HTML + _MUESTRAS_HTML
)
