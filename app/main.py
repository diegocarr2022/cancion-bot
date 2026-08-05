import asyncio
import logging
import secrets
import uuid

import re

from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import TELEGRAM_WEBHOOK_SECRET, BASE_URL, ADMIN_CHAT_ID, ADMIN_PANEL_PASSWORD
from app.conversation import handle_message
from app.dlocal_client import verify_signature, get_payment
from app.email_client import enviar_cancion_por_correo
from app.landing import LANDING_HTML
from app.legal import TERMINOS_HTML, PRIVACIDAD_HTML
from app.payment_confirm import confirmar_pago, confirmar_pago_web
from app.suno_client import get_task_status, generate_custom_song, extract_ready_items
from app.telegram_client import send_document_by_url, send_message, set_webhook, get_me
from app.web_conversation import handle_web_chat

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cancion-bot")

app = FastAPI(title="Cancion Bot")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Se llena una vez al arrancar (ver startup) con el username del bot, para
# poder armar el link t.me/... del boton de la pagina de pago exitoso.
BOT_USERNAME = ""

# IMPORTANTE: asyncio solo guarda una referencia DEBIL a las tareas creadas
# con asyncio.create_task(). Si no guardamos nosotros mismos una referencia
# fuerte en algun lado, el recolector de basura de Python puede destruir la
# tarea en cualquier momento SIN ningun error ni log - el loop de background
# simplemente deja de correr en silencio. Por eso guardamos todas las tareas
# de fondo aca, para que nunca se recolecten mientras el proceso este vivo.
_background_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


@app.on_event("startup")
async def startup():
    global BOT_USERNAME
    db.init_db()
    if BASE_URL:
        result = await set_webhook(BASE_URL, TELEGRAM_WEBHOOK_SECRET)
        log.info("Telegram setWebhook: %s", result)
    me = await get_me()
    BOT_USERNAME = me.get("username", "")
    _spawn(poll_suno_tasks_loop())
    _spawn(poll_pending_payments_loop())
    _spawn(poll_stuck_generation_loop())
    _spawn(poll_web_suno_tasks_loop())
    _spawn(poll_web_pending_payments_loop())
    log.info(
        "Loops de background arrancados: poll_suno_tasks_loop, "
        "poll_pending_payments_loop, poll_stuck_generation_loop, "
        "poll_web_suno_tasks_loop, poll_web_pending_payments_loop"
    )


@app.get("/")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Link intermedio de tracking: en vez de poner en tus anuncios el link de
# Telegram directo, poné https://tu-app.onrender.com/ir/<source> (ej.
# /ir/marketplace, /ir/instagram, /ir/tiktok). Esto registra el clic REAL
# (Telegram no nos avisa si alguien abre el chat sin presionar "Iniciar",
# asi que esta es la unica forma de medir eso) y despues redirige a Telegram
# ya con el origen etiquetado, para que quede guardado en el pedido si la
# persona llega a escribirle al bot.
# ---------------------------------------------------------------------------
_SOURCE_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


@app.get("/ir/{source}")
async def ir_a_telegram(source: str, request: Request):
    if not _SOURCE_RE.match(source):
        raise HTTPException(status_code=400, detail="Origen invalido")
    if not BOT_USERNAME:
        raise HTTPException(status_code=503, detail="Bot todavia no esta listo")

    user_agent = request.headers.get("user-agent", "")
    ip = request.client.host if request.client else None
    fbclid = request.query_params.get("fbclid")
    db.log_click(source, user_agent=user_agent, ip=ip, fbclid=fbclid)
    log.info(
        "[/ir/%s] clic registrado (ip=%s, ua=%s, fbclid=%s)",
        source, ip, user_agent, fbclid,
    )
    return RedirectResponse(url=f"https://t.me/{BOT_USERNAME}?start={source}", status_code=302)


# ---------------------------------------------------------------------------
# Landing web /cancion: alternativa sin friccion al link de Telegram para
# trafico de anuncios (Marketplace, etc.) - todo el flujo (chat con Claude,
# pago, entrega) pasa dentro de la misma pestana del navegador, sin pedir
# instalar ninguna app. Ver app/landing.py y app/web_conversation.py.
# ---------------------------------------------------------------------------
@app.get("/cancion", response_class=HTMLResponse)
async def cancion_landing():
    return LANDING_HTML


# Requeridas por las politicas de anuncios de Facebook/Google (cualquier
# landing que pida datos o cobre dinero tiene que enlazar estas paginas).
@app.get("/terminos", response_class=HTMLResponse)
async def terminos():
    return TERMINOS_HTML


@app.get("/privacidad", response_class=HTMLResponse)
async def privacidad():
    return PRIVACIDAD_HTML


@app.post("/web/session")
async def web_session(request: Request):
    # Ya no se pide el correo en una pantalla aparte (era un click extra de
    # friccion antes de siquiera empezar a chatear) - Claude lo pide el mismo
    # como parte natural de la charla y lo guarda al llamar finalizar_letra
    # (ver web_conversation.py). Aca solo se crea la sesion.
    body = await request.json() if await request.body() else {}
    source = body.get("source")

    session_id = uuid.uuid4().hex
    db.create_web_order(session_id, source=source)
    log.info("[web] nueva sesion %s (source=%s)", session_id, source)
    return {"session_id": session_id}


@app.post("/web/chat")
async def web_chat(request: Request):
    body = await request.json()
    session_id = body.get("session_id")
    message = body.get("message", "")
    if not session_id:
        raise HTTPException(status_code=400, detail="Falta session_id")

    try:
        resultado = await handle_web_chat(session_id, message)
    except ValueError:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")
    return resultado


@app.get("/web/status")
async def web_status(session_id: str):
    order = db.get_web_order(session_id)
    if not order:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")
    import json as _json
    audio_urls = _json.loads(order["audio_urls"]) if order.get("audio_urls") else []
    return {
        "step": order["step"],
        "paid": bool(order["paid"]),
        "delivered": bool(order["delivered"]),
        "audio_urls": audio_urls,
    }


# ---------------------------------------------------------------------------
# Pagina a la que dLocal Go redirige al cliente en su navegador despues de
# pagar (success_url). No hace falta que haga nada - la confirmacion real
# del pago llega por webhook/polling - es solo para que el cliente no vea un
# JSON crudo y sepa que puede volver a Telegram.
# ---------------------------------------------------------------------------
@app.get("/pago-exitoso", response_class=HTMLResponse)
async def pago_exitoso(web: str = "", session_id: str = ""):
    # El flujo web (landing /cancion) abre el link de pago en una pestaña
    # NUEVA para que la pestaña original con el chat siga viva haciendo
    # polling a /web/status - aca solo confirmamos y pedimos volver a esa
    # otra pestaña, sin nada de Telegram.
    if web:
        return """
        <html>
          <head><meta charset="utf-8"><title>Pago recibido</title></head>
          <body style="font-family: sans-serif; text-align: center; padding: 60px 20px;">
            <h1>🎵 ¡Pago recibido!</h1>
            <p>Ya puedes cerrar esta pestaña y volver a la otra donde estaba tu canción -
            en un par de minutos vas a ver el link de descarga ahí mismo.</p>
          </body>
        </html>
        """

    boton = ""
    if BOT_USERNAME:
        boton = f"""
        <a href="https://t.me/{BOT_USERNAME}"
           style="display:inline-block; margin-top:24px; padding:14px 28px;
                  background:#2AABEE; color:white; text-decoration:none;
                  border-radius:8px; font-size:18px; font-weight:bold;">
          ↩️ Volver a Telegram
        </a>
        """
    return f"""
    <html>
      <head><meta charset="utf-8"><title>Pago recibido</title></head>
      <body style="font-family: sans-serif; text-align: center; padding: 60px 20px;">
        <h1>🎵 ¡Pago recibido!</h1>
        <p>Ya puedes volver a Telegram para seguir con tu canción.</p>
        {boton}
      </body>
    </html>
    """


# ---------------------------------------------------------------------------
# Panel de admin: resumen de ventas y lista de pedidos, protegido con
# contrasena (HTTP Basic Auth). El usuario no importa, solo la contrasena
# (ADMIN_PANEL_PASSWORD). Si esa variable no esta configurada, el panel
# devuelve 404 - preferimos que quede invisible/deshabilitado por defecto en
# vez de exponerlo sin proteccion por accidente.
# ---------------------------------------------------------------------------
_basic_auth = HTTPBasic()


def _verificar_admin(credentials: HTTPBasicCredentials = Depends(_basic_auth)):
    if not ADMIN_PANEL_PASSWORD:
        raise HTTPException(status_code=404)
    # compare_digest evita timing attacks al comparar la contrasena
    if not secrets.compare_digest(credentials.password, ADMIN_PANEL_PASSWORD):
        raise HTTPException(
            status_code=401,
            detail="Contraseña incorrecta",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


_ESTADO_LABELS = {
    "creando_pago": ("Creando pago", "#9ca3af"),
    "esperando_pago": ("Esperando pago", "#f59e0b"),
    "pago_fallido": ("Pago fallido", "#ef4444"),
    "charlando": ("Armando la letra", "#3b82f6"),
    "generando": ("Generando canción", "#8b5cf6"),
    "entregado": ("Entregado ✅", "#22c55e"),
}


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(_: bool = Depends(_verificar_admin)):
    stats = db.get_stats()
    orders = db.get_all_orders(limit=300)
    canales = db.get_click_stats()
    bots_filtrados = db.get_bot_clicks_total()
    web_stats = db.get_web_stats()

    filas_canales = ""
    for c in canales:
        tasa_inicio = f"{(c['inicios_telegram'] / c['clics'] * 100):.0f}%" if c["clics"] else "—"
        filas_canales += f"""
        <tr>
          <td><strong>{c['source']}</strong></td>
          <td>{c['clics']}</td>
          <td>{c['inicios_telegram']} <span style="color:#9ca3af; font-size:12px;">({tasa_inicio})</span></td>
          <td>{c['pagados']}</td>
          <td>${c['ingresos_mxn']:.0f} MXN</td>
        </tr>
        """

    filas = ""
    for o in orders:
        label, color = _ESTADO_LABELS.get(o["step"], (o["step"], "#9ca3af"))
        monto = f"${o['amount_mxn']:.0f}" if o.get("amount_mxn") else "—"
        titulo = o.get("final_title") or "—"
        filas += f"""
        <tr>
          <td>{o['chat_id']}</td>
          <td>{titulo}</td>
          <td><span style="background:{color}22; color:{color}; padding:3px 10px;
              border-radius:999px; font-size:13px; font-weight:600;">{label}</span></td>
          <td>{monto}</td>
          <td style="color:#6b7280; font-size:13px;">{o['created_at'][:16].replace('T', ' ')}</td>
        </tr>
        """

    return f"""
    <html>
      <head>
        <meta charset="utf-8">
        <title>Panel de ventas — Cancion Bot</title>
        <style>
          body {{ font-family: -apple-system, system-ui, sans-serif; background:#f9fafb;
                  color:#111827; margin:0; padding:32px 24px; }}
          h1 {{ font-size:22px; margin-bottom:24px; }}
          .cards {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:32px; }}
          .card {{ background:white; border-radius:12px; padding:18px 22px;
                    box-shadow:0 1px 3px rgba(0,0,0,0.08); min-width:150px; }}
          .card .label {{ font-size:13px; color:#6b7280; margin-bottom:6px; }}
          .card .value {{ font-size:26px; font-weight:700; }}
          table {{ width:100%; border-collapse:collapse; background:white;
                    border-radius:12px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.08); }}
          th {{ text-align:left; font-size:12px; text-transform:uppercase; color:#6b7280;
                padding:12px 16px; border-bottom:1px solid #e5e7eb; }}
          td {{ padding:12px 16px; border-bottom:1px solid #f3f4f6; font-size:14px; }}
          tr:last-child td {{ border-bottom:none; }}
        </style>
      </head>
      <body>
        <h1>🎵 Panel de ventas — Cancion Bot</h1>
        <div class="cards">
          <div class="card"><div class="label">Ingresos totales</div>
            <div class="value">${stats['ingresos_mxn']:.0f} MXN</div></div>
          <div class="card"><div class="label">Ingresos hoy</div>
            <div class="value">${stats['ingresos_hoy_mxn']:.0f} MXN</div></div>
          <div class="card"><div class="label">Pedidos pagados</div>
            <div class="value">{stats['pagados']}</div></div>
          <div class="card"><div class="label">Entregados</div>
            <div class="value">{stats['entregados']}</div></div>
          <div class="card"><div class="label">En curso (pagado, sin entregar)</div>
            <div class="value">{stats['en_curso']}</div></div>
          <div class="card"><div class="label">Esperando pago</div>
            <div class="value">{stats['esperando_pago']}</div></div>
          <div class="card"><div class="label">Pagos fallidos</div>
            <div class="value">{stats['fallidos']}</div></div>
          <div class="card"><div class="label">Total de pedidos</div>
            <div class="value">{stats['total']}</div></div>
        </div>

        <h2 style="font-size:16px; margin: 32px 0 4px;">🌐 Landing web (/cancion)</h2>
        <div class="cards" style="margin-bottom:32px;">
          <div class="card"><div class="label">Sesiones totales</div>
            <div class="value">{web_stats['total']}</div></div>
          <div class="card"><div class="label">Pagados</div>
            <div class="value">{web_stats['pagados']}</div></div>
          <div class="card"><div class="label">Entregados</div>
            <div class="value">{web_stats['entregados']}</div></div>
          <div class="card"><div class="label">Ingresos</div>
            <div class="value">${web_stats['ingresos_mxn']:.0f} MXN</div></div>
        </div>

        <h2 style="font-size:16px; margin: 32px 0 4px;">📊 Por canal (link de tracking /ir/&lt;origen&gt;)</h2>
        <p style="font-size:12px; color:#9ca3af; margin:0 0 12px;">
          Ya se filtraron {bots_filtrados} clic(s) que parecían bots/crawlers
          (de Meta, Telegram, etc. generando la vista previa del link) - no
          son personas reales, no están contados abajo.
        </p>
        <table style="margin-bottom:32px;">
          <thead>
            <tr><th>Canal</th><th>Clics reales</th><th>Iniciaron en Telegram</th>
                <th>Pagaron</th><th>Ingresos</th></tr>
          </thead>
          <tbody>
            {filas_canales or '<tr><td colspan="5" style="text-align:center; color:#9ca3af;">Todavía no hay clics registrados con /ir/&lt;origen&gt;</td></tr>'}
          </tbody>
        </table>

        <table>
          <thead>
            <tr><th>Chat ID</th><th>Canción</th><th>Estado</th><th>Monto</th><th>Creado</th></tr>
          </thead>
          <tbody>
            {filas or '<tr><td colspan="5" style="text-align:center; color:#9ca3af;">Sin pedidos todavía</td></tr>'}
          </tbody>
        </table>
      </body>
    </html>
    """


# ---------------------------------------------------------------------------
# Telegram: recibe cada mensaje del cliente y avanza la conversacion
# ---------------------------------------------------------------------------
@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    if TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret token")

    update = await request.json()
    message = update.get("message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]

    if "text" in message:
        text = message["text"]
    elif "photo" in message or "document" in message:
        # El cliente mando una imagen/archivo (ej. captura del comprobante de
        # pago). No procesamos el archivo en si - el admin lo revisa
        # directamente en Telegram - pero igual avanzamos la conversacion
        # como si hubiera mandado un mensaje de texto.
        text = "[comprobante enviado]"
    else:
        return {"ok": True}

    # IMPORTANTE: no hacemos "await" de handle_message aca. Si el procesamiento
    # tarda (por ejemplo, la llamada a dLocal Go o a Claude), Telegram no
    # espera indefinidamente una respuesta - si no le contestamos rapido,
    # reenvia el mismo mensaje, y eso puede disparar acciones duplicadas
    # (pagos duplicados, mensajes repetidos). Por eso confirmamos de una
    # vez con {"ok": True} y seguimos procesando en segundo plano.
    # Usamos _spawn (no asyncio.create_task directo) para que la tarea no
    # se pierda por garbage collection antes de terminar.
    _spawn(handle_message(chat_id, text))
    return {"ok": True}


# ---------------------------------------------------------------------------
# dLocal Go: notificacion de cambio de estado de un pago.
# El body solo trae {"payment_id": "..."} - hay que consultar get_payment()
# para saber el status real, y verificar la firma antes de confiar en nada.
# ---------------------------------------------------------------------------
@app.post("/dlocal/webhook")
async def dlocal_webhook(request: Request, authorization: str = Header(default="")):
    raw_body = await request.body()

    if not verify_signature(raw_body, authorization):
        log.warning("Firma invalida en webhook de dLocal Go")
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    payment_id = payload.get("payment_id")
    if not payment_id:
        return {"ok": True}

    payment = await get_payment(payment_id)
    log.info("dLocal Go payment %s status=%s", payment_id, payment.get("status"))

    if payment.get("status") != "PAID":
        return {"ok": True}

    order = db.find_by_payment_request_id(payment_id)
    if order and not order["paid"]:
        await confirmar_pago(order["chat_id"])
        return {"ok": True}

    web_order = db.find_web_by_payment_request_id(payment_id)
    if web_order and not web_order["paid"]:
        await confirmar_pago_web(web_order["session_id"])

    return {"ok": True}


# ---------------------------------------------------------------------------
# Loop de fondo: revisa periodicamente si las canciones ya estan listas
# y las entrega por Telegram apenas lo estan.
# ---------------------------------------------------------------------------
async def poll_suno_tasks_loop():
    while True:
        try:
            pending = db.find_unfinished_suno_tasks()
            # "Latido" visible en el log: confirma que el loop sigue vivo en
            # cada vuelta, aunque no haya nada pendiente. Sin esto, un log
            # silencioso por horas se puede confundir con un loop muerto.
            log.info("[poll_suno_tasks_loop] tick - %d pedido(s) en generacion", len(pending))
            for order in pending:
                await check_and_deliver(order)
        except Exception:
            log.exception("Error en el loop de polling de Suno")
        await asyncio.sleep(20)


async def check_and_deliver(order: dict):
    try:
        task = await get_task_status(order["suno_task_id"])
    except Exception:
        log.exception("Error consultando estado de Suno para chat_id=%s", order["chat_id"])
        return

    state = task.get("state")
    info = extract_ready_items(task)
    ready_items = info["ready_items"]
    failed_count = info["failed_count"]
    total_items = info["total_items"]
    pendientes = info["pendientes"]

    log.info(
        "Suno task %s (chat_id=%s): state=%s success=%s listas=%d/%d fallidas=%d raw=%s",
        order["suno_task_id"], order["chat_id"], state, info["success"],
        len(ready_items), total_items, failed_count, task,
    )

    if info["fallo_total"]:
        response = (task.get("response") or {})
        log.error("La generacion de Suno fallo para chat_id=%s: %s", order["chat_id"], response)
        db.update_order(order["chat_id"], step="charlando", suno_task_id=None)
        await send_message(
            order["chat_id"],
            "Hubo un problema generando tu canción. Ya lo estamos revisando, en un momento seguimos.",
        )
        await send_message(
            ADMIN_CHAT_ID, f"⚠️ Suno reportó 'failed' para chat_id {order['chat_id']}: {response}"
        )
        return

    if pendientes > 0 or not ready_items:
        return  # todavia falta alguna variante por terminar de generar

    # Ya estan todas las variantes que van a estar listas - se entregan todas.
    titulo = order.get("final_title") or "Tu canción"
    entregadas_ok = 0
    for idx, item in enumerate(ready_items, start=1):
        audio_url = item["audio_url"]
        multiple = len(ready_items) > 1
        caption = (
            f"🎵 ¡Tu canción está lista! (Versión {idx} de {len(ready_items)})"
            if multiple
            else "🎵 ¡Tu canción personalizada está lista!"
        )
        enviado_ok = await send_document_by_url(
            order["chat_id"],
            audio_url,
            caption=caption,
            title=f"{titulo} (v{idx})" if multiple else titulo,
        )
        if not enviado_ok:
            log.warning(
                "Telegram rechazo la variante %d de Suno para chat_id=%s, se reintentara solo.",
                idx, order["chat_id"],
            )
            continue

        entregadas_ok += 1
        # Ademas del reproductor, mandamos el link directo como texto. El
        # reproductor de audio de Telegram no siempre deja claro como
        # descargar (en desktop hace falta click derecho, y no todos lo
        # saben) - un link de texto es inequivoco.
        etiqueta_version = f" (Versión {idx})" if multiple else ""
        await send_message(
            order["chat_id"],
            f"👇 Descarga directa{etiqueta_version}:\n{audio_url}",
        )

    if entregadas_ok < len(ready_items):
        # Al menos una variante no se pudo mandar - NO marcamos como
        # entregado, asi el loop de polling reintenta TODAS de nuevo en 20
        # segundos (puede duplicar alguna que si se mando bien, pero es
        # preferible a dejar al cliente sin una de sus 2 versiones).
        return

    # CRITICO: hay que mover el step a "entregado" ademas de marcar delivered=1.
    # Si no, el pedido se queda "generando" para siempre y cualquier mensaje
    # posterior del cliente (incluso un simple "gracias") recibe la respuesta
    # fija de "tu cancion se esta generando" en conversation.py, sin importar
    # que ya se le haya entregado.
    db.update_order(order["chat_id"], delivered=1, step="entregado")


# ---------------------------------------------------------------------------
# Loop de fondo: chequea pagos pendientes. Esto hace que la confirmacion de
# pago sea autonoma incluso si el webhook de dLocal Go fallara por algun
# motivo - vos (admin) solo te enteras si el pago realmente fallo
# (rechazado/cancelado/expirado), nunca por el camino feliz.
# ---------------------------------------------------------------------------
async def poll_pending_payments_loop():
    while True:
        try:
            pending = db.find_pending_payments()
            log.info("[poll_pending_payments_loop] tick - %d pago(s) pendiente(s)", len(pending))
            for order in pending:
                await check_payment_status(order)
        except Exception:
            log.exception("Error en el loop de polling de pagos")
        await asyncio.sleep(20)


async def check_payment_status(order: dict):
    try:
        payment = await get_payment(order["payment_request_id"])
    except Exception:
        log.exception("Error consultando pago pendiente para chat_id=%s", order["chat_id"])
        return

    status = payment.get("status")

    if status == "PAID":
        await confirmar_pago(order["chat_id"])
        return

    if status in ("REJECTED", "CANCELLED", "EXPIRED") and order["step"] != "pago_fallido":
        db.update_order(order["chat_id"], step="pago_fallido")
        await send_message(
            order["chat_id"],
            "Parece que hubo un problema con tu pago (quedó como "
            f"{status.lower()}). Contame y te genero un nuevo link, o dime "
            "si tienes dudas sobre cómo pagar.",
        )
        await send_message(
            ADMIN_CHAT_ID,
            f"⚠️ El pago de chat_id {order['chat_id']} quedó en estado {status}.",
        )


# ---------------------------------------------------------------------------
# Loop de fondo: si una cancion se quedo "a medias" (la letra ya se aprobo,
# pero nunca se le mando a Suno o el proceso se corto a mitad de camino - por
# ejemplo por un redeploy) la reintenta sola. Asi no hace falta ningun
# comando manual para el caso mas comun de fallo.
# ---------------------------------------------------------------------------
async def poll_stuck_generation_loop():
    while True:
        try:
            stuck = db.find_stuck_generation()
            log.info("[poll_stuck_generation_loop] tick - %d generacion(es) atascada(s)", len(stuck))
            for order in stuck:
                await reintentar_generacion_automatica(order)
        except Exception:
            log.exception("Error en el loop de polling de generaciones atascadas")
        await asyncio.sleep(30)


async def reintentar_generacion_automatica(order: dict):
    chat_id = order["chat_id"]
    log.info("Reintentando automaticamente la generacion atascada de chat_id=%s", chat_id)
    try:
        result = await generate_custom_song(
            lyric=order["final_lyric"], title=order["final_title"], style=order["final_style"]
        )
        task_id = result.get("task_id") or result.get("id")
        db.update_order(chat_id, suno_task_id=task_id)
    except Exception:
        log.exception("Volvio a fallar el reintento automatico de Suno para chat_id=%s", chat_id)
        await send_message(
            ADMIN_CHAT_ID,
            f"⚠️ La generación de la canción de chat_id {chat_id} sigue fallando "
            "después de un reintento automático. Puede necesitar revisión manual.",
        )


# ---------------------------------------------------------------------------
# Loops de fondo para los pedidos web (landing /cancion) - misma logica que
# los de Telegram, en paralelo, sobre la tabla web_orders. Aca no hay
# Telegram al que mandarle mensajes: el cliente se entera por el polling de
# /web/status en su propia pestana (ver app/landing.py) y por el correo de
# respaldo (ver app/email_client.py).
# ---------------------------------------------------------------------------
async def poll_web_pending_payments_loop():
    while True:
        try:
            pending = db.find_pending_web_payments()
            log.info("[poll_web_pending_payments_loop] tick - %d pago(s) web pendiente(s)", len(pending))
            for order in pending:
                await check_web_payment_status(order)
        except Exception:
            log.exception("Error en el loop de polling de pagos web")
        await asyncio.sleep(20)


async def check_web_payment_status(order: dict):
    try:
        payment = await get_payment(order["payment_request_id"])
    except Exception:
        log.exception("Error consultando pago web pendiente para session_id=%s", order["session_id"])
        return

    status = payment.get("status")
    if status == "PAID":
        await confirmar_pago_web(order["session_id"])
        return

    if status in ("REJECTED", "CANCELLED", "EXPIRED"):
        log.warning(
            "El pago web de session_id=%s (email=%s) quedó en estado %s.",
            order["session_id"], order.get("email"), status,
        )


async def poll_web_suno_tasks_loop():
    while True:
        try:
            pending = db.find_unfinished_web_suno_tasks()
            log.info("[poll_web_suno_tasks_loop] tick - %d pedido(s) web en generacion", len(pending))
            for order in pending:
                await check_and_deliver_web(order)
        except Exception:
            log.exception("Error en el loop de polling de Suno (web)")
        await asyncio.sleep(20)


async def check_and_deliver_web(order: dict):
    import json as _json

    try:
        task = await get_task_status(order["suno_task_id"])
    except Exception:
        log.exception("Error consultando estado de Suno para session_id=%s (web)", order["session_id"])
        return

    info = extract_ready_items(task)
    ready_items = info["ready_items"]

    log.info(
        "Suno task %s (session_id=%s, web): listas=%d/%d fallidas=%d",
        order["suno_task_id"], order["session_id"],
        len(ready_items), info["total_items"], info["failed_count"],
    )

    if info["fallo_total"]:
        log.error(
            "La generacion de Suno fallo para session_id=%s (web): %s",
            order["session_id"], task.get("response"),
        )
        db.update_web_order(order["session_id"], suno_task_id=None)
        await send_message(
            ADMIN_CHAT_ID,
            f"⚠️ Suno reportó 'failed' para un pedido web (email={order.get('email')}, "
            f"session_id={order['session_id']}).",
        )
        return

    if info["pendientes"] > 0 or not ready_items:
        return

    audio_urls = [item["audio_url"] for item in ready_items]
    db.update_web_order(
        order["session_id"],
        delivered=1,
        step="entregado",
        audio_urls=_json.dumps(audio_urls),
    )

    if order.get("email"):
        enviado = await enviar_cancion_por_correo(
            order["email"], order.get("final_title") or "Tu canción", audio_urls
        )
        if enviado:
            db.update_web_order(order["session_id"], delivered_email=1)
