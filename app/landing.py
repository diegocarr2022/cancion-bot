"""
Landing page /cancion: la version "sin fricciones" que reemplaza al link a
Telegram para el trafico de anuncios (Marketplace, etc.). Todo en un solo
archivo HTML+CSS+JS embebido, servido como string (mismo patron que
/admin y /pago-exitoso en main.py) - no hace falta un build step ni
archivos estaticos aparte.

Flujo en el navegador:
1. Pide el correo (para poder mandar la cancion por correo como respaldo).
2. Abre el chat con Claude (mismo motor conversacional que el bot de
   Telegram) para reunir los detalles y aprobar la letra.
3. Cuando la letra queda aprobada, aparece el boton de pago (se abre en una
   pestaña NUEVA a proposito, para que esta pestaña se quede viva haciendo
   polling de /web/status).
4. En cuanto el pago se confirma y la cancion esta lista, aparece el link de
   descarga directo aca mismo - sin necesidad de instalar nada.
"""

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
    color: #292018; margin: 0; padding: 24px 16px 60px;
    min-height: 100vh;
  }
  .wrap { max-width: 560px; margin: 0 auto; }
  h1 { font-size: 24px; text-align: center; margin: 8px 0 4px; }
  .sub { text-align: center; color: #7c6f5f; font-size: 15px; margin-bottom: 24px; }
  .card {
    background: white; border-radius: 16px; padding: 20px;
    box-shadow: 0 4px 20px rgba(180,120,60,0.10); margin-bottom: 16px;
  }
  input[type=email], input[type=text] {
    width: 100%; padding: 13px 14px; border-radius: 10px; border: 1px solid #e7dccb;
    font-size: 16px; margin-bottom: 12px;
  }
  button {
    width: 100%; padding: 14px; border-radius: 10px; border: none;
    background: linear-gradient(135deg, #e8813a, #d96b2b); color: white;
    font-size: 16px; font-weight: 700; cursor: pointer;
  }
  button:disabled { opacity: 0.55; cursor: default; }
  #chat { display: none; }
  #mensajes { max-height: 60vh; overflow-y: auto; padding: 4px 2px; margin-bottom: 12px; }
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
</style>
</head>
<body>
<div class="wrap">
  <h1>🎵 Tu canción personalizada</h1>
  <p class="sub">Cuéntanos la historia y en minutos tienes tu canción única, lista para descargar aquí mismo.</p>

  <div class="card" id="inicio">
    <label for="email" style="font-size:14px; color:#6b5b45; display:block; margin-bottom:6px;">
      ¿A qué correo te la mandamos como respaldo?
    </label>
    <input type="email" id="email" placeholder="tucorreo@ejemplo.com" required>
    <button id="btn-empezar">Empezar</button>
  </div>

  <div class="card" id="chat">
    <div id="mensajes"></div>
    <div class="fila-input">
      <input type="text" id="input-mensaje" placeholder="Escribe aquí...">
      <button id="btn-enviar">Enviar</button>
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

async function empezar() {
  const email = $("email").value.trim();
  if (!email || !email.includes("@")) { alert("Ingresa un correo válido"); return; }
  $("btn-empezar").disabled = true;
  $("btn-empezar").textContent = "Un momento...";

  const params = new URLSearchParams(window.location.search);
  const source = params.get("source") || null;

  const resp = await fetch("/web/session", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({email, source}),
  });
  const data = await resp.json();
  sessionId = data.session_id;

  $("inicio").style.display = "none";
  $("chat").style.display = "block";
  await enviarTurno("");
}

async function enviarTurno(texto) {
  if (texto) agregarMensaje(texto, "user");
  $("btn-enviar").disabled = true;

  const resp = await fetch("/web/chat", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({session_id: sessionId, message: texto}),
  });
  const data = await resp.json();
  (data.mensajes || []).forEach((m) => agregarMensaje(m, "bot"));

  if (data.listo_para_pagar && data.payment_url) {
    $("link-pago").href = data.payment_url;
    $("pago-box").style.display = "block";
    $("chat").style.display = "none";
    iniciarPolling();
  }
  $("btn-enviar").disabled = false;
}

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
      $("estado-box").style.display = "none";
      $("pago-box").style.display = "none";
      const cont = $("links-descarga");
      cont.innerHTML = "";
      data.audio_urls.forEach((url, i) => {
        const a = document.createElement("a");
        a.href = url; a.target = "_blank"; a.rel = "noopener";
        a.textContent = data.audio_urls.length > 1 ? ("Descargar versión " + (i + 1)) : "Descargar mi canción";
        cont.appendChild(a);
        cont.appendChild(document.createElement("br"));
      });
      $("descarga-box").style.display = "block";
    }
  }, 5000);
}

$("btn-empezar").addEventListener("click", empezar);
$("btn-enviar").addEventListener("click", () => {
  const val = $("input-mensaje").value.trim();
  if (!val) return;
  $("input-mensaje").value = "";
  enviarTurno(val);
});
$("input-mensaje").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("btn-enviar").click();
});
</script>
</body>
</html>
"""
