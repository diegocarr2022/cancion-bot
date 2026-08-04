import asyncio
import logging
import secrets

from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app import db
from app.config import TELEGRAM_WEBHOOK_SECRET, BASE_URL, ADMIN_CHAT_ID, ADMIN_PANEL_PASSWORD
from app.conversation import handle_message
from app.dlocal_client import verify_signature, get_payment
from app.payment_confirm import confirmar_pago
from app.suno_client import get_task_status, generate_custom_song
from app.telegram_client import send_document_by_url, send_message, set_webhook, get_me

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cancion-bot")

app = FastAPI(title="Cancion Bot")

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
    log.info(
        "Loops de background arrancados: poll_suno_tasks_loop, "
        "poll_pending_payments_loop, poll_stuck_generation_loop"
    )


@app.get("/")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Pagina a la que dLocal Go redirige al cliente en su navegador despues de
# pagar (success_url). No hace falta que haga nada - la confirmacion real
# del pago llega por webhook/polling - es solo para que el cliente no vea un
# JSON crudo y sepa que puede volver a Telegram.
# ---------------------------------------------------------------------------
@app.get("/pago-exitoso", response_class=HTMLResponse)
async def pago_exitoso():
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
    if not order or order["paid"]:
        return {"ok": True}

    await confirmar_pago(order["chat_id"])
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
    response = task.get("response") or {}
    success = response.get("success")
    items = response.get("data") or []
    total_items = len(items)

    # IMPORTANTE (descubierto en produccion, con el error real de un 400 de
    # Telegram al intentar entregar): "state" a nivel de la tarea y
    # "response.success" NO son confiables (llegan None en la practica).
    # Cada elemento de "data" es una variante (Suno SIEMPRE genera 2 por
    # pedido, dos versiones distintas de la misma cancion) y TIENE SU PROPIO
    # "audio_url" que aparece MUY TEMPRANO - es un endpoint de streaming que
    # existe desde que arranca la generacion, no cuando termina. La senal
    # real de que una variante ya esta completamente renderizada (y por lo
    # tanto es un archivo valido para mandarle a Telegram) es que ademas
    # tenga "duration" (numero de segundos) - ese campo se queda en None
    # mientras se sigue generando.
    #
    # Como las 2 variantes ya estan pagadas (el cliente paga por la
    # generacion, no por una sola version), esperamos a que TODAS las
    # variantes que no hayan fallado terminen, y se las entregamos ambas -
    # asi el cliente se queda con las 2 versiones distintas que genero Suno.
    ready_items = []
    failed_count = 0
    for item in items:
        item_state = (item.get("state") or "").lower()
        if item_state in ("error", "failed"):
            failed_count += 1
            continue
        if item.get("audio_url") and item.get("duration"):
            ready_items.append(item)

    pendientes = total_items - failed_count - len(ready_items)

    log.info(
        "Suno task %s (chat_id=%s): state=%s success=%s listas=%d/%d fallidas=%d raw=%s",
        order["suno_task_id"], order["chat_id"], state, success,
        len(ready_items), total_items, failed_count, task,
    )

    if success is False or (total_items > 0 and failed_count == total_items):
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
