import asyncio
import logging

from fastapi import FastAPI, Request, Header, HTTPException

from app import db
from app.config import TELEGRAM_WEBHOOK_SECRET, BASE_URL, ADMIN_CHAT_ID
from app.conversation import handle_message
from app.dlocal_client import verify_signature, get_payment
from app.payment_confirm import confirmar_pago
from app.suno_client import get_task_status, generate_custom_song
from app.telegram_client import send_document_by_url, send_message, set_webhook

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("cancion-bot")

app = FastAPI(title="Cancion Bot")


@app.on_event("startup")
async def startup():
    db.init_db()
    if BASE_URL:
        result = await set_webhook(BASE_URL, TELEGRAM_WEBHOOK_SECRET)
        log.info("Telegram setWebhook: %s", result)
    asyncio.create_task(poll_suno_tasks_loop())
    asyncio.create_task(poll_pending_payments_loop())
    asyncio.create_task(poll_stuck_generation_loop())


@app.get("/")
async def health():
    return {"status": "ok"}


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
    asyncio.create_task(handle_message(chat_id, text))
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

    # IMPORTANTE (descubierto en produccion, con el error real de un 400 de
    # Telegram al intentar entregar): "state" a nivel de la tarea y
    # "response.success" NO son confiables (llegan None en la practica).
    # Cada elemento de "data" es una variante (Suno genera 2 por pedido) y
    # TIENE SU PROPIO "audio_url" que aparece MUY TEMPRANO - es un endpoint
    # de streaming que existe desde que arranca la generacion, no cuando
    # termina. La senal real de que una variante ya esta completamente
    # renderizada (y por lo tanto es un archivo valido para mandarle a
    # Telegram) es que ademas tenga "duration" (numero de segundos) - ese
    # campo se queda en None mientras se sigue generando. Si entregamos en
    # cuanto aparece audio_url sin esperar "duration", Telegram puede
    # rechazar el archivo con 400 porque todavia esta a medio generar.
    ready_item = None
    hubo_error_en_variante = False
    for item in items:
        item_state = (item.get("state") or "").lower()
        if item_state in ("error", "failed"):
            hubo_error_en_variante = True
        if item.get("audio_url") and item.get("duration"):
            ready_item = item
            break

    log.info(
        "Suno task %s (chat_id=%s): state=%s success=%s lista=%s raw=%s",
        order["suno_task_id"], order["chat_id"], state, success, bool(ready_item), task,
    )

    if success is False or (hubo_error_en_variante and not ready_item):
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

    if not ready_item:
        return  # todavia se esta generando/transmitiendo - no esta lista de verdad

    audio_url = ready_item["audio_url"]

    enviado_ok = await send_document_by_url(
        order["chat_id"],
        audio_url,
        caption="🎵 ¡Tu canción personalizada está lista!",
        title=order.get("final_title") or "Tu canción",
    )
    if not enviado_ok:
        # Telegram rechazo el archivo (por ejemplo, 400 porque la URL
        # todavia no es un archivo completo y valido). NO marcamos como
        # entregado - asi el loop de polling lo vuelve a intentar solo en
        # 20 segundos, sin que nadie tenga que hacer nada manualmente.
        log.warning(
            "Telegram rechazo el archivo de Suno para chat_id=%s, se reintentara solo.",
            order["chat_id"],
        )
        return

    # Ademas del reproductor, mandamos el link directo como texto. El
    # reproductor de audio de Telegram no siempre deja claro como descargar
    # (en desktop hace falta click derecho, y no todos lo saben) - un link de
    # texto es inequivoco: se toca/clickea y listo, se abre o descarga solo.
    await send_message(
        order["chat_id"],
        "👇 Si quieres descargarla directo a tu teléfono o computadora, toca este link:\n"
        f"{audio_url}",
    )
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
