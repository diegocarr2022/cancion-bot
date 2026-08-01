import asyncio
import logging

from fastapi import FastAPI, Request, Header, HTTPException

from app import db
from app.config import TELEGRAM_WEBHOOK_SECRET, BASE_URL
from app.conversation import handle_message
from app.dlocal_client import verify_signature, get_payment
from app.payment_confirm import confirmar_pago
from app.suno_client import get_task_status
from app.telegram_client import send_document_by_url, set_webhook

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
    task = await get_task_status(order["suno_task_id"])
    state = task.get("state") or task.get("status")

    if state not in ("succeeded", "completed", "finished"):
        return

    audio_url = None
    for item in task.get("data", []) or task.get("result", []):
        audio_url = item.get("audio_url") or item.get("url")
        if audio_url:
            break

    if not audio_url:
        return

    await send_document_by_url(
        order["chat_id"], audio_url, caption="🎵 ¡Tu canción personalizada está lista!"
    )
    db.update_order(order["chat_id"], delivered=1)
