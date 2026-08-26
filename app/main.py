import asyncio
import html
import logging
import resource
import secrets
import uuid

import httpx
import re
from datetime import datetime

from fastapi import FastAPI, Request, Header, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import (
    TELEGRAM_WEBHOOK_SECRET,
    BASE_URL,
    ADMIN_CHAT_ID,
    ADMIN_PANEL_PASSWORD,
    get_precio_pais,
    POLL_INTERVAL_SECONDS,
    POLL_INTERVAL_STUCK_SECONDS,
    PENDING_PAYMENT_MAX_HORAS,
    PENDING_PAYMENT_BACKOFF_HORAS,
    PENDING_PAYMENT_BACKOFF_MINUTOS,
    ENABLE_VIDEO_TIER,
    BRAND_NAME_EN,
    GOOGLE_ADS_CONVERSION_ID,
    GOOGLE_ADS_CONVERSION_LABEL,
    TRUSTPILOT_REVIEW_URL,
    STRIPE_WEBHOOK_SECRET,
)
from app.conversation import handle_message
from app.dlocal_client import verify_signature, get_payment
from app.email_client import enviar_cancion_por_correo, enviar_recordatorio_resena
from app.landing import LANDING_HTML_ES, LANDING_HTML_EN, pixel_script, google_ads_script
from app.legal import TERMINOS_HTML, PRIVACIDAD_HTML, TERMS_HTML_EN, PRIVACY_HTML_EN
from app.payment_confirm import confirmar_pago, confirmar_pago_web
from app.pdf_client import build_lyrics_pdf
from app.paypal_client import (
    capture_order as paypal_capture_order,
    get_order as paypal_get_order,
    verify_webhook_signature as paypal_verify_webhook_signature,
)
from app.stripe_client import verify_webhook_signature as stripe_verify_webhook_signature
from app.suno_client import get_task_status, generate_custom_song, extract_ready_items
from app.telegram_client import send_document_by_url, send_message, set_webhook, get_me
from app.web_conversation import handle_web_chat, crear_link_pago

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


def _horas_desde(iso_timestamp: str) -> float:
    try:
        entonces = datetime.fromisoformat(iso_timestamp)
    except (TypeError, ValueError):
        return 0.0
    return (datetime.utcnow() - entonces).total_seconds() / 3600


def _debe_chequear_pago(order: dict) -> bool:
    """Decide si toca consultar dLocal Go en esta vuelta del loop, o si
    conviene esperar (backoff). Durante la primera hora se chequea siempre
    (PENDING_PAYMENT_BACKOFF_HORAS); despues, solo si paso al menos
    PENDING_PAYMENT_BACKOFF_MINUTOS desde el ultimo chequeo real - asi varios
    pedidos abandonados acumulados no multiplican las llamadas HTTP por
    minuto sin limite."""
    if _horas_desde(order["updated_at"]) < PENDING_PAYMENT_BACKOFF_HORAS:
        return True
    ultimo_chequeo = order.get("last_checked_at")
    if not ultimo_chequeo:
        return True
    minutos_desde_chequeo = _horas_desde(ultimo_chequeo) * 60
    return minutos_desde_chequeo >= PENDING_PAYMENT_BACKOFF_MINUTOS


def _memoria_mb() -> float:
    """Memoria pico (RSS) usada por el proceso hasta ahora, en MB - via el
    modulo estandar `resource` (Linux), sin depender de librerias externas
    como psutil. OJO: ru_maxrss es un maximo acumulado, nunca baja durante la
    vida del proceso - lo usamos solo para ver la TENDENCIA entre ticks de
    los loops de fondo mientras se diagnostica la fuga de memoria reportada
    en Render (ago 2026), no como memoria "actual" exacta."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


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
    _spawn(poll_review_reminder_loop())
    log.info(
        "Loops de background arrancados: poll_suno_tasks_loop, "
        "poll_pending_payments_loop, poll_stuck_generation_loop, "
        "poll_web_suno_tasks_loop, poll_web_pending_payments_loop, "
        "poll_review_reminder_loop"
    )


@app.get("/healthz")
async def health():
    return {"status": "ok"}


# La raiz del dominio ES la landing en ingles directamente (ago 2026: EE.UU.
# es ahora el mercado principal, ver expansion en la conversacion) - no un
# redirect ni un JSON de health-check (eso se movio a /healthz, ver
# healthCheckPath en render.yaml). Root URL limpia (tunecraft.studio a
# secas) para usar como Final URL en Google Ads: nada mas corto ni mas claro
# para Quality Score. Default ingles salvo que pidan español explicito
# (?lang=es) o el navegador lo indique (Accept-Language) - al reves de como
# era antes, cuando el default era español y EE.UU. la excepcion.
@app.get("/", response_class=HTMLResponse)
async def raiz(request: Request, lang: str | None = None):
    resolved_lang = (lang or "").strip().lower()
    return LANDING_HTML_ES if resolved_lang == "es" else LANDING_HTML_EN


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
async def cancion_landing(lang: str | None = None):
    # ?lang=en/es en el link del anuncio decide el idioma - mismo mecanismo
    # que ?source=/?country= (ver iniciar() en landing.py). Sin el parametro,
    # /cancion es la URL historica en espanol (Telegram, enlaces viejos) -
    # default a ES, sin adivinar por Accept-Language (ese respaldo causaba
    # que navegadores en ingles vieran EN incluso entrando a /cancion sin
    # parametro - mismo bug que ya se habia corregido en la raiz "/").
    resolved_lang = (lang or "").strip().lower()
    return LANDING_HTML_EN if resolved_lang == "en" else LANDING_HTML_ES



# Requeridas por las politicas de anuncios de Facebook/Google (cualquier
# landing que pida datos o cobre dinero tiene que enlazar estas paginas).
@app.get("/terminos", response_class=HTMLResponse)
async def terminos():
    return TERMINOS_HTML


@app.get("/privacidad", response_class=HTMLResponse)
async def privacidad():
    return PRIVACIDAD_HTML


# Version en ingles, para la landing de EE.UU. (ver LANDING_HTML_EN) - las
# rutas en espanol de arriba quedan intactas para el trafico de MX/PE/CO.
@app.get("/terms", response_class=HTMLResponse)
async def terms():
    return TERMS_HTML_EN


@app.get("/privacy", response_class=HTMLResponse)
async def privacy():
    return PRIVACY_HTML_EN


@app.post("/web/session")
async def web_session(request: Request):
    # Ya no se pide el correo en una pantalla aparte (era un click extra de
    # friccion antes de siquiera empezar a chatear) - Claude lo pide el mismo
    # como parte natural de la charla y lo guarda al llamar finalizar_letra
    # (ver web_conversation.py). Aca solo se crea la sesion.
    body = await request.json() if await request.body() else {}
    source = body.get("source")

    # ?lang=en/es en el link del anuncio (ver /cancion arriba y iniciar() en
    # landing.py) - default espanol si no viene o viene algo invalido.
    lang = (body.get("lang") or "").strip().lower()
    if lang not in ("es", "en"):
        lang = "es"

    # ?country=<codigo> en el link del anuncio decide el pais/moneda de este
    # pedido (ver PAISES_SOPORTADOS en config.py). Si viene un codigo no
    # soportado (o no viene), ya NO cae siempre en Mexico: si el idioma es
    # ingles se asume EE.UU. (dLocal Go/Mercado Pago no pueden cobrar ahi -
    # ver app/paypal_client.py - por eso EE.UU. no puede caer accidentalmente
    # en el default de Mexico, quedaria cobrando mal).
    country_code = (body.get("country") or "").strip().upper()
    if country_code not in ("MX", "PE", "CO", "US"):
        country_code = "US" if lang == "en" else "MX"

    # tier: el upsell de video ("song_video") solo existe para EE.UU. y solo
    # mientras ENABLE_VIDEO_TIER este activo (Fase 2) - cualquier otra
    # combinacion cae en el tier "song" normal, sin excepciones silenciosas.
    tier = (body.get("tier") or "song").strip().lower()
    if country_code != "US" or tier not in ("song", "song_video") or not ENABLE_VIDEO_TIER:
        tier = "song"

    precio = get_precio_pais(country_code, tier)

    # fbclid/fbp: se leen del lado del navegador (landing.py, del URL y de la
    # cookie _fbp del propio Pixel de Meta) y se mandan aca para poder
    # reenviarselos a Meta en el evento Purchase server-side cuando se
    # confirme el pago (ver app/meta_capi.py) - sin esto Meta no puede
    # atribuir la venta a la campaña que la genero.
    fbclid = body.get("fbclid")
    fbp = body.get("fbp")
    client_ip = request.client.host if request.client else None
    client_user_agent = request.headers.get("user-agent")

    # utm_*/gclid: parametros estandar de Google Ads (gclid = su version de
    # fbclid, para atribucion) - antes solo se guardaba el "source" custom,
    # sin forma de saber de que campana/grupo de anuncios especifico vino
    # cada sesion. Se guardan tal cual vienen en la URL, sin validar valores.
    utm_source = body.get("utm_source")
    utm_medium = body.get("utm_medium")
    utm_campaign = body.get("utm_campaign")
    utm_content = body.get("utm_content")
    utm_term = body.get("utm_term")
    gclid = body.get("gclid")

    session_id = uuid.uuid4().hex
    db.create_web_order(
        session_id, source=source, country=country_code, currency=precio["currency"],
        fbclid=fbclid, fbp=fbp, client_ip=client_ip, client_user_agent=client_user_agent,
        language=lang, tier=tier,
        utm_source=utm_source, utm_medium=utm_medium, utm_campaign=utm_campaign,
        utm_content=utm_content, utm_term=utm_term, gclid=gclid,
    )
    log.info(
        "[web] nueva sesion %s (source=%s, country=%s, currency=%s, lang=%s, tier=%s)",
        session_id, source, country_code, precio["currency"], lang, tier,
    )
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
        "payment_url": order.get("payment_url"),
        "stripe_client_secret": order.get("stripe_client_secret"),
        "gateway": order.get("gateway"),
        "final_title": order.get("final_title"),
        # tier/video_status/video_url: usados por el frontend en ingles para
        # saber si tiene que mostrar el widget de subida de fotos y, mas
        # adelante, el link de descarga del video (Fase 2 - ver
        # app/video_client.py). video_status queda en "none" para pedidos
        # tier="song", asi que la landing en espanol nunca ve estos campos
        # con un valor distinto al que ya ignora hoy.
        "tier": order.get("tier", "song"),
        "video_status": order.get("video_status", "none"),
        "video_url": order.get("video_url"),
    }


@app.post("/web/review-click")
async def web_review_click(request: Request):
    """Registra que el cliente le dio clic al link de reseña de Trustpilot
    en la pantalla de descarga - asi poll_review_reminder_loop sabe que no
    hace falta mandarle el correo de recordatorio despues."""
    body = await request.json() if await request.body() else {}
    session_id = body.get("session_id")
    if session_id:
        db.mark_review_link_clicked(session_id)
    return {"ok": True}


@app.get("/web/lyrics-pdf/{session_id}")
async def web_lyrics_pdf(session_id: str):
    """Genera al vuelo el PDF de la letra aprobada (ver app/pdf_client.py) -
    se ofrece junto al link de audio en cuanto la cancion queda entregada."""
    order = db.get_web_order(session_id)
    if not order or not order.get("final_lyric"):
        raise HTTPException(status_code=404, detail="No hay letra todavia para esta sesion")
    pdf_bytes = build_lyrics_pdf(
        order.get("final_title") or "Your song",
        order["final_lyric"],
    )
    slug = re.sub(r"[^a-z0-9]+", "-", (order.get("final_title") or "tunecraft-song").lower()).strip("-") or "tunecraft-song"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{slug}-lyrics.pdf"'},
    )


# ---------------------------------------------------------------------------
# Pagina a la que dLocal Go redirige al cliente en su navegador despues de
# pagar (success_url). No hace falta que haga nada - la confirmacion real
# del pago llega por webhook/polling - es solo para que el cliente no vea un
# JSON crudo y sepa que puede volver a Telegram.
# ---------------------------------------------------------------------------
# Version web (ES/dLocal): el link de pago abre en una pestaña NUEVA para que
# la pestaña original con el chat siga viva haciendo polling a /web/status.
# (La version EN/PayPal ya NO abre pestaña nueva - ver el boton de pago en
# LANDING_HTML_EN y el manejo de esta misma ruta mas abajo, que redirige de
# vuelta al chat en la misma pestaña para no perder continuidad.)
# El session_id va en el PATH (no en query string) porque no todos los
# gateways de pago preservan query params custom al armar la redireccion
# final - un segmento de path es mucho mas dificil de perder. Con el
# session_id en la URL, ademas, podemos reconocer al cliente y darle un link
# de regreso directo a su chat (por si cierra esta pestaña o la perdio de
# algun modo).
@app.get("/pago-exitoso/web/{session_id}", response_class=HTMLResponse)
async def pago_exitoso_web(session_id: str):
    order = db.get_web_order(session_id) or {}

    # PayPal (EE.UU.), a diferencia de dLocal Go, no confirma el pago solo
    # con llegar aca - "aprobado" todavia no es "cobrado", hace falta
    # capturar la orden explicitamente. Si el webhook ya la marco pagada
    # (order["paid"]) no se vuelve a capturar - capture_order() tolera el
    # error "ORDER_ALREADY_CAPTURED" si de todos modos llegara a pasar.
    if order.get("gateway") == "paypal" and not order.get("paid"):
        try:
            await paypal_capture_order(order["payment_request_id"])
            await confirmar_pago_web(session_id)
            order = db.get_web_order(session_id) or order
        except Exception:
            log.exception("Error capturando la orden de PayPal para session_id=%s", session_id)
            # El link de pago que tenia este pedido probablemente ya quedo
            # muerto (una orden de PayPal no se puede volver a capturar
            # despues de un fallo en la mayoria de los casos) - se genera uno
            # NUEVO de una vez, para que el cliente vea un boton que SI
            # funciona al volver a la pantalla, sin tener que chatear para
            # pedir ayuda. Ver Diego: "necesita el bot saber si el pago fue
            # rechazado" - este caso (fallo en el capture, que vemos nosotros
            # mismos en el momento) no necesita esperar al bot ni a un
            # webhook, se resuelve aca directo.
            try:
                precio = get_precio_pais(order.get("country"), order.get("tier", "song"))
                await crear_link_pago(session_id, order, precio)
                order = db.get_web_order(session_id) or order
                await send_message(
                    ADMIN_CHAT_ID,
                    f"⚠️ Falló el cobro de PayPal para session_id={session_id} "
                    f"(pago aprobado pero el capture fue rechazado). Se genero un link "
                    f"de pago nuevo automaticamente.",
                )
            except Exception:
                log.exception(
                    "Tambien fallo la regeneracion del link de pago para session_id=%s",
                    session_id,
                )

    # Evento "Purchase" del Pixel de Meta (lado del navegador) - se dispara
    # en cuanto el cliente aterriza aca de vuelta desde la pasarela, que solo
    # pasa tras un checkout aprobado. Es la unica forma de medir conversion
    # que tenemos habilitada por ahora (ver pixel_script() en landing.py: la
    # Conversions API server-side quedo bloqueada por una restriccion vieja
    # en la cuenta de Meta Business de Diego, sin resolver todavia).
    pixel_html = pixel_script(
        "fbq('track', 'Purchase', {value: %s, currency: %s}, {eventID: %s});"
        % (
            repr(float(order.get("amount_mxn") or 0)),
            repr(order.get("currency") or "MXN"),
            repr(f"web-{session_id}"),
        ),
        noscript_ev="Purchase",
    )

    # Evento de conversion de Google (GA4 "purchase" + conversion de Google
    # Ads, si esta configurada) - mismo momento/logica que el pixel de Meta
    # de arriba. GA_MEASUREMENT_ID/GOOGLE_ADS_CONVERSION_ID vacios ya hacen
    # que google_ads_script() no imprima nada (ver landing.py), asi que este
    # bloque es seguro de dejar siempre activo aunque todavia no este
    # configurado ningun ID.
    _google_calls = (
        "gtag('event', 'purchase', {transaction_id: %s, value: %s, currency: %s});"
        % (
            repr(f"web-{session_id}"),
            repr(float(order.get("amount_mxn") or 0)),
            repr(order.get("currency") or "MXN"),
        )
    )
    if GOOGLE_ADS_CONVERSION_ID and GOOGLE_ADS_CONVERSION_LABEL:
        _google_calls += (
            "gtag('event', 'conversion', {send_to: %s, value: %s, currency: %s, transaction_id: %s});"
            % (
                repr(f"{GOOGLE_ADS_CONVERSION_ID}/{GOOGLE_ADS_CONVERSION_LABEL}"),
                repr(float(order.get("amount_mxn") or 0)),
                repr(order.get("currency") or "MXN"),
                repr(f"web-{session_id}"),
            )
        )
    google_html = google_ads_script(_google_calls)

    if order.get("language") == "en":
        # Este pago ocurre en la misma pestana (el boton de pago ya no abre
        # target=_blank) - en vez de dejar al cliente en una pagina estatica
        # separada de "pago recibido" pidiendole que vuelva el solo a la otra
        # pestana, disparamos el pixel de conversion y lo regresamos de una
        # directo al chat/estado de su cancion (retomarSesion() en el JS de
        # la raiz ya sabe leer ?session_id= y mostrar el estado correcto).
        return f"""
        <html>
          <head><meta charset="utf-8"><title>{BRAND_NAME_EN} — Payment received</title>{pixel_html}{google_html}</head>
          <body style="font-family: sans-serif; text-align: center; padding: 60px 20px;">
            <p style="font-weight:800; color:#d96b2b; margin-bottom:4px;">{BRAND_NAME_EN}</p>
            <h1>🎵 Payment received!</h1>
            <p>Taking you back to your song…</p>
            <a href="/?session_id={session_id}" id="volver">Continue</a>
          </body>
          <script>
            setTimeout(function() {{ window.location.replace("/?session_id={session_id}"); }}, 600);
          </script>
        </html>
        """

    return f"""
    <html>
      <head><meta charset="utf-8"><title>Pago recibido</title>{pixel_html}{google_html}</head>
      <body style="font-family: sans-serif; text-align: center; padding: 60px 20px;">
        <h1>🎵 ¡Pago recibido!</h1>
        <p>Ya puedes cerrar esta pestaña y volver a la otra donde estaba tu canción -
        en un par de minutos vas a ver el link de descarga ahí mismo.</p>
        <p style="color:#9a8b73; font-size:14px; margin-top:20px;">
          ¿Cerraste esa pestaña por error? Puedes volver aquí:
        </p>
        <a href="/cancion?session_id={session_id}"
           style="display:inline-block; margin-top:8px; padding:14px 28px;
                  background:linear-gradient(135deg, #e8813a, #d96b2b); color:white;
                  text-decoration:none; border-radius:8px; font-size:16px; font-weight:bold;">
          ↩️ Ver el estado de mi canción
        </a>
      </body>
    </html>
    """


@app.get("/pago-exitoso", response_class=HTMLResponse)
async def pago_exitoso():
    # Version Telegram (sin session_id en la URL - dLocal Go la usa igual
    # para esos pagos). No hace falta que haga nada - la confirmacion real
    # del pago llega por webhook/polling - es solo para que el cliente no
    # vea un JSON crudo y sepa que puede volver a Telegram.
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


def _extraer_texto_contenido(content) -> str:
    """Convierte el campo 'content' de un mensaje (formato API de Anthropic -
    string simple, o lista de bloques text/tool_use/tool_result) en texto
    legible para mostrar en el panel de admin, escapado para HTML."""
    if isinstance(content, str):
        return html.escape(content)
    if not isinstance(content, list):
        return ""
    fragmentos = []
    for bloque in content:
        if not isinstance(bloque, dict):
            continue
        tipo = bloque.get("type")
        if tipo == "text":
            texto = html.escape(bloque.get("text", "")).strip()
            if texto:
                fragmentos.append(texto)
        elif tipo == "tool_use":
            fragmentos.append(f"<em style='color:#9ca3af;'>→ usó herramienta: {html.escape(bloque.get('name', ''))}</em>")
        elif tipo == "tool_result":
            sub = bloque.get("content")
            if isinstance(sub, list):
                sub_texto = " ".join(
                    html.escape(b.get("text", "")) for b in sub if isinstance(b, dict) and b.get("type") == "text"
                )
            else:
                sub_texto = html.escape(str(sub or ""))
            sub_texto = sub_texto.strip()
            if sub_texto:
                fragmentos.append(f"<span style='color:#9ca3af;'>{sub_texto}</span>")
    return "<br>".join(fragmentos)


def _render_transcript_html(messages: list) -> str:
    """Pinta el historial completo de la conversacion (mismo 'messages' que
    se le manda a Claude) como burbujas de chat, para poder reconstruir
    exactamente que se pidio/aprobo/cambio si hay algun reclamo."""
    partes = []
    for m in messages:
        role = m.get("role", "?")
        texto = _extraer_texto_contenido(m.get("content"))
        if not texto:
            continue
        es_usuario = role == "user"
        alineacion = "left" if es_usuario else "right"
        fondo = "#f3f4f6" if es_usuario else "#fff7ed"
        etiqueta = "Cliente" if es_usuario else "Claude"
        partes.append(f"""
        <div style="margin:10px 0; text-align:{alineacion};">
          <div style="display:inline-block; max-width:80%; text-align:left; background:{fondo};
                      padding:10px 14px; border-radius:10px; font-size:14px; white-space:pre-wrap;">
            <div style="font-size:11px; font-weight:700; color:#9ca3af; margin-bottom:4px;">{etiqueta}</div>
            {texto}
          </div>
        </div>
        """)
    return "".join(partes) or "<p style='color:#9ca3af;'>Sin conversación registrada.</p>"


_ADMIN_DETALLE_CSS = """
body { font-family: -apple-system, system-ui, sans-serif; background:#f9fafb; color:#111827; margin:0; padding:32px 24px; }
.card { background:white; border-radius:12px; padding:20px 24px; box-shadow:0 1px 3px rgba(0,0,0,0.08); margin-bottom:20px; max-width:720px; }
a.volver { color:#c2410c; font-weight:600; text-decoration:none; }
h2 { font-size:13px; text-transform:uppercase; letter-spacing:0.04em; color:#6b7280; margin:0 0 12px; }
"""


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(_: bool = Depends(_verificar_admin)):
    stats = db.get_stats()
    orders = db.get_all_orders(limit=300)
    canales = db.get_click_stats()
    bots_filtrados = db.get_bot_clicks_total()
    web_stats = db.get_web_stats()
    web_orders = db.get_all_web_orders(limit=300)
    entregas_recientes = db.get_recent_deliveries()
    # Ingresos web separados por moneda (no se pueden sumar MXN + PEN + COP
    # como si fueran la misma unidad) - se muestran uno junto al otro.
    ingresos_web_texto = " + ".join(
        f"${fila['total']:.0f} {fila['currency']}" for fila in web_stats["ingresos_por_moneda"]
    ) or "$0"

    filas_entregas = ""
    for e in entregas_recientes:
        canal_label = "📱 Telegram" if e["canal"] == "telegram" else "🌐 Web"
        detalle_href = f"/admin/orden/{e['canal']}/{e['id']}"
        titulo_e = e.get("titulo") or "—"
        monto_e = f"${e['monto']:.0f} {e['moneda']}" if e.get("monto") else "—"
        filas_entregas += f"""
        <tr>
          <td>{canal_label}</td>
          <td><a href="{detalle_href}" style="color:#c2410c; font-weight:600;">{titulo_e}</a></td>
          <td>{monto_e}</td>
          <td style="color:#6b7280; font-size:13px;">{(e.get('updated_at') or '')[:16].replace('T', ' ')}</td>
        </tr>
        """

    filas_web = ""
    for o in web_orders:
        label, color = _ESTADO_LABELS.get(o["step"], (o["step"], "#9ca3af"))
        monto = f"${o['amount_mxn']:.0f}" if o.get("amount_mxn") else "—"
        nombre = o.get("customer_name") or "—"
        correo = o.get("email") or "—"
        pais = o.get("country") or "MX"
        monto_txt = f"{monto} {o.get('currency') or ''}".strip() if o.get("amount_mxn") else "—"
        # Canal: idioma + pasarela + tier, para distinguir de un vistazo los
        # pedidos EN/PayPal (con precio de lanzamiento, ver config.py) de los
        # ES/dLocal de siempre - ver expansion a EE.UU. (ago 2026).
        idioma = (o.get("language") or "es").upper()
        gateway = o.get("gateway") or "—"
        tier = o.get("tier") or "song"
        canal = f"{idioma} · {gateway}" + (" · +video" if tier == "song_video" else "")
        filas_web += f"""
        <tr>
          <td>{nombre}</td>
          <td>{correo}</td>
          <td>{pais}</td>
          <td style="color:#6b7280; font-size:12.5px;">{canal}</td>
          <td><span style="background:{color}22; color:{color}; padding:3px 10px;
              border-radius:999px; font-size:13px; font-weight:600;">{label}</span></td>
          <td>{monto_txt}</td>
          <td style="color:#6b7280; font-size:13px;">{o['created_at'][:16].replace('T', ' ')}</td>
          <td><a href="/admin/orden/web/{o['session_id']}" style="color:#c2410c; font-weight:600;">Ver</a></td>
        </tr>
        """

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
          <td><a href="/admin/orden/telegram/{o['chat_id']}" style="color:#c2410c; font-weight:600;">Ver</a></td>
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
        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
          <h1>🎵 Panel de ventas — Cancion Bot</h1>
          <form method="post" action="/admin/reset-all"
                onsubmit="return confirm('¿Borrar TODO el historial (Telegram + web + clicks)? Esto no se puede deshacer.');">
            <button type="submit" style="background:#ef4444; color:white; border:none;
                    padding:8px 16px; border-radius:8px; font-size:13px; font-weight:600;
                    cursor:pointer;">🗑️ Borrar todo el historial</button>
          </form>
        </div>

        <h2 style="font-size:16px; margin: 0 0 4px;">📱 Telegram (México)</h2>
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
            <div class="value">{ingresos_web_texto}</div></div>
        </div>

        <h2 style="font-size:16px; margin: 32px 0 4px;">🎵 Últimas entregas (todos los canales)</h2>
        <table style="margin-bottom:32px;">
          <thead>
            <tr><th>Canal</th><th>Canción</th><th>Monto</th><th>Entregado</th></tr>
          </thead>
          <tbody>
            {filas_entregas or '<tr><td colspan="4" style="text-align:center; color:#9ca3af;">Sin entregas todavía</td></tr>'}
          </tbody>
        </table>

        <p style="font-size:12px; color:#9ca3af; margin:-20px 0 12px;">
          Nombre y correo capturados en el chat de la landing - utiles para armar
          audiencias similares (lookalike) en Meta Ads.
        </p>
        <table style="margin-bottom:32px;">
          <thead>
            <tr><th>Nombre</th><th>Correo</th><th>País</th><th>Canal</th><th>Estado</th><th>Monto</th><th>Creado</th><th></th></tr>
          </thead>
          <tbody>
            {filas_web or '<tr><td colspan="8" style="text-align:center; color:#9ca3af;">Sin pedidos web todavía</td></tr>'}
          </tbody>
        </table>

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
            <tr><th>Chat ID</th><th>Canción</th><th>Estado</th><th>Monto</th><th>Creado</th><th></th></tr>
          </thead>
          <tbody>
            {filas or '<tr><td colspan="6" style="text-align:center; color:#9ca3af;">Sin pedidos todavía</td></tr>'}
          </tbody>
        </table>
      </body>
    </html>
    """


@app.post("/admin/reset-all")
async def admin_reset_all(_: bool = Depends(_verificar_admin)):
    db.reset_all()
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/admin/orden/web/{session_id}", response_class=HTMLResponse)
async def admin_orden_web(session_id: str, _: bool = Depends(_verificar_admin)):
    order = db.get_web_order(session_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    transcripcion = _render_transcript_html(db.get_web_messages(session_id))
    letra = html.escape(order.get("final_lyric") or "")
    voz_pedida = {"f": "Femenina", "m": "Masculina"}.get(order.get("final_gender"), "Sin preferencia especificada")
    return f"""
    <html>
      <head><meta charset="utf-8"><title>Pedido web {session_id[:8]}</title>
        <style>{_ADMIN_DETALLE_CSS}</style>
      </head>
      <body>
        <a class="volver" href="/admin">← Volver al panel</a>
        <h1 style="font-size:20px; margin:16px 0;">Pedido web — {html.escape(order.get('customer_name') or 'sin nombre')}</h1>
        <div class="card">
          <h2>Datos</h2>
          <p><strong>Correo:</strong> {html.escape(order.get('email') or '—')}</p>
          <p><strong>País / idioma:</strong> {html.escape(order.get('country') or '—')} · {html.escape(order.get('language') or 'es')}</p>
          <p><strong>Pasarela:</strong> {html.escape(order.get('gateway') or '—')}</p>
          <p><strong>ID de orden de pago:</strong> {html.escape(order.get('payment_request_id') or '—')}</p>
          <p><strong>Estado:</strong> {html.escape(order.get('step') or '—')} · pagado: {'sí' if order.get('paid') else 'no'} · entregado: {'sí' if order.get('delivered') else 'no'}</p>
          <p><strong>Creado:</strong> {(order.get('created_at') or '')[:16].replace('T', ' ')}</p>
        </div>
        <div class="card">
          <h2>Origen / atribución</h2>
          <p><strong>Source:</strong> {html.escape(order.get('source') or '—')}</p>
          <p><strong>UTM:</strong> {html.escape(order.get('utm_source') or '—')} / {html.escape(order.get('utm_medium') or '—')} / {html.escape(order.get('utm_campaign') or '—')}</p>
          <p><strong>UTM content / term:</strong> {html.escape(order.get('utm_content') or '—')} / {html.escape(order.get('utm_term') or '—')}</p>
          <p><strong>gclid:</strong> {html.escape(order.get('gclid') or '—')} · <strong>fbclid:</strong> {html.escape(order.get('fbclid') or '—')}</p>
        </div>
        <div class="card">
          <h2>Letra aprobada</h2>
          <p><strong>Título:</strong> {html.escape(order.get('final_title') or '—')}</p>
          <p><strong>Estilo:</strong> {html.escape(order.get('final_style') or '—')}</p>
          <p><strong>Voz pedida:</strong> {voz_pedida}</p>
          <div style="white-space:pre-wrap; font-size:14px; line-height:1.6; margin-top:10px;">{letra or '<span style="color:#9ca3af;">Sin letra aprobada todavía.</span>'}</div>
        </div>
        <div class="card">
          <h2>Conversación completa</h2>
          {transcripcion}
        </div>
      </body>
    </html>
    """


@app.get("/admin/orden/telegram/{chat_id}", response_class=HTMLResponse)
async def admin_orden_telegram(chat_id: int, _: bool = Depends(_verificar_admin)):
    order = db.get_order(chat_id)
    if not order:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    transcripcion = _render_transcript_html(db.get_messages(chat_id))
    letra = html.escape(order.get("final_lyric") or "")
    return f"""
    <html>
      <head><meta charset="utf-8"><title>Pedido Telegram {chat_id}</title>
        <style>{_ADMIN_DETALLE_CSS}</style>
      </head>
      <body>
        <a class="volver" href="/admin">← Volver al panel</a>
        <h1 style="font-size:20px; margin:16px 0;">Pedido Telegram — chat_id {chat_id}</h1>
        <div class="card">
          <h2>Estado</h2>
          <p><strong>Estado:</strong> {html.escape(order.get('step') or '—')} · pagado: {'sí' if order.get('paid') else 'no'} · entregado: {'sí' if order.get('delivered') else 'no'}</p>
          <p><strong>Creado:</strong> {(order.get('created_at') or '')[:16].replace('T', ' ')}</p>
        </div>
        <div class="card">
          <h2>Letra aprobada</h2>
          <p><strong>Título:</strong> {html.escape(order.get('final_title') or '—')}</p>
          <p><strong>Estilo:</strong> {html.escape(order.get('final_style') or '—')}</p>
          <div style="white-space:pre-wrap; font-size:14px; line-height:1.6; margin-top:10px;">{letra or '<span style="color:#9ca3af;">Sin letra aprobada todavía.</span>'}</div>
        </div>
        <div class="card">
          <h2>Mandar mensaje manual</h2>
          <p style="font-size:13px; color:#6b7280;">Se manda directo por el bot a este chat_id - no hace falta que el cliente escriba primero.</p>
          <form method="post" action="/admin/orden/telegram/{chat_id}/mensaje">
            <textarea name="texto" rows="4" style="width:100%; box-sizing:border-box; font-family:inherit; font-size:14px; padding:8px;" placeholder="Escribe el mensaje..."></textarea>
            <button type="submit" style="margin-top:8px; padding:8px 16px; background:#c2410c; color:#fff; border:none; border-radius:6px; font-weight:600; cursor:pointer;">Enviar</button>
          </form>
        </div>
        <div class="card">
          <h2>Conversación completa</h2>
          {transcripcion}
        </div>
      </body>
    </html>
    """


@app.post("/admin/orden/telegram/{chat_id}/mensaje")
async def admin_enviar_mensaje_telegram(
    chat_id: int, texto: str = Form(...), _: bool = Depends(_verificar_admin)
):
    texto = texto.strip()
    if texto:
        await send_message(chat_id, texto)
    return RedirectResponse(url=f"/admin/orden/telegram/{chat_id}", status_code=303)


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


@app.post("/paypal/webhook")
async def paypal_webhook(request: Request):
    # PayPal verifica la firma llamando a su propia API (a diferencia del
    # HMAC local de dLocal Go) - ver paypal_client.verify_webhook_signature.
    # Le pasamos los headers en minusculas porque asi es como PayPal nombra
    # los campos que espera de vuelta.
    headers_lower = {k.lower(): v for k, v in request.headers.items()}
    raw_body = await request.json()

    try:
        firma_valida = await paypal_verify_webhook_signature(headers_lower, raw_body)
    except Exception:
        log.exception("Error verificando la firma del webhook de PayPal")
        firma_valida = False

    if not firma_valida:
        log.warning("Firma invalida en webhook de PayPal")
        raise HTTPException(status_code=401, detail="Invalid signature")

    event_type = raw_body.get("event_type")
    log.info("PayPal webhook event_type=%s", event_type)

    if event_type in ("PAYMENT.CAPTURE.COMPLETED", "CHECKOUT.ORDER.APPROVED"):
        resource = raw_body.get("resource", {})
        # custom_id se seteo en create_order() (paypal_client.py) como el
        # session_id de web_orders - reference_id tambien lo trae por si el
        # tipo de evento no incluye custom_id directamente en el resource.
        session_id = resource.get("custom_id") or resource.get("reference_id")
        if not session_id and resource.get("purchase_units"):
            session_id = resource["purchase_units"][0].get("custom_id") or resource["purchase_units"][0].get("reference_id")

        if session_id:
            order = db.get_web_order(session_id)
            if order and not order["paid"]:
                await confirmar_pago_web(session_id)

    return {"ok": True}


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(default="")):
    # Stripe firma con HMAC-SHA256 local (a diferencia de PayPal, que exige
    # llamar a su propia API) - ver stripe_client.verify_webhook_signature.
    # Necesita el cuerpo CRUDO sin parsear (la firma se calcula sobre esos
    # bytes exactos), por eso se lee con request.body() y no request.json().
    raw_body = await request.body()
    event = stripe_verify_webhook_signature(raw_body, stripe_signature, STRIPE_WEBHOOK_SECRET)

    if event is None:
        log.warning("Firma invalida en webhook de Stripe")
        raise HTTPException(status_code=401, detail="Invalid signature")

    event_type = event.get("type")
    log.info("Stripe webhook event_type=%s", event_type)

    if event_type == "payment_intent.succeeded":
        payment_intent = (event.get("data") or {}).get("object") or {}
        session_id = (payment_intent.get("metadata") or {}).get("session_id")
        if session_id:
            order = db.get_web_order(session_id)
            if order and not order["paid"]:
                await confirmar_pago_web(session_id)

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
            log.info(
                "[poll_suno_tasks_loop] tick - %d pedido(s) en generacion - mem=%.1fMB",
                len(pending), _memoria_mb(),
            )
            for order in pending:
                await check_and_deliver(order)
        except Exception:
            log.exception("Error en el loop de polling de Suno")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


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
            log.info(
                "[poll_pending_payments_loop] tick - %d pago(s) pendiente(s) - mem=%.1fMB",
                len(pending), _memoria_mb(),
            )
            for order in pending:
                await check_payment_status(order)
        except Exception:
            log.exception("Error en el loop de polling de pagos")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def check_payment_status(order: dict):
    # Si el cliente abrio el link de pago y lo abandono (nunca pago ni lo
    # cancelo), dLocal Go puede quedarse indefinidamente en un estado "no
    # final" sin avisar - sin este corte, este pago se reconsultaria PARA
    # SIEMPRE, cada minuto, generando llamadas HTTP sin fin (ver diagnostico
    # de fuga de memoria de ago 2026).
    if _horas_desde(order["updated_at"]) > PENDING_PAYMENT_MAX_HORAS:
        db.update_order(order["chat_id"], step="pago_fallido")
        log.info(
            "Pago abandonado (mas de %sh sin resolverse) para chat_id=%s - se deja de reintentar.",
            PENDING_PAYMENT_MAX_HORAS, order["chat_id"],
        )
        return

    if not _debe_chequear_pago(order):
        return  # todavia no toca (backoff) - se revisa de nuevo mas adelante

    try:
        payment = await get_payment(order["payment_request_id"])
        db.touch_last_checked(order["chat_id"], datetime.utcnow().isoformat())
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
            log.info(
                "[poll_stuck_generation_loop] tick - %d generacion(es) atascada(s) - mem=%.1fMB",
                len(stuck), _memoria_mb(),
            )
            for order in stuck:
                await reintentar_generacion_automatica(order)
        except Exception:
            log.exception("Error en el loop de polling de generaciones atascadas")
        await asyncio.sleep(POLL_INTERVAL_STUCK_SECONDS)


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
            log.info(
                "[poll_web_pending_payments_loop] tick - %d pago(s) web pendiente(s) - mem=%.1fMB",
                len(pending), _memoria_mb(),
            )
            for order in pending:
                await check_web_payment_status(order)
        except Exception:
            log.exception("Error en el loop de polling de pagos web")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


REVIEW_REMINDER_POLL_SECONDS = 3600  # cada hora alcanza sobra - no es urgente
REVIEW_REMINDER_MIN_HOURS = 48


async def poll_review_reminder_loop():
    """Recordatorio de reseña de Trustpilot por correo - solo para quien NO
    le dio clic al link en la pantalla de descarga (ver web_review_click) en
    las primeras 48h. El pedido principal es en el momento de la entrega;
    esto es unicamente el respaldo. No hace nada si TRUSTPILOT_REVIEW_URL no
    esta configurado."""
    while True:
        try:
            if TRUSTPILOT_REVIEW_URL:
                pendientes = db.find_web_orders_pending_review_reminder(REVIEW_REMINDER_MIN_HOURS)
                log.info(
                    "[poll_review_reminder_loop] tick - %d recordatorio(s) de reseña pendiente(s)",
                    len(pendientes),
                )
                for order in pendientes:
                    enviado = await enviar_recordatorio_resena(
                        order["email"], order.get("final_title") or "Your song", TRUSTPILOT_REVIEW_URL,
                    )
                    if enviado:
                        db.update_web_order(order["session_id"], review_email_sent=1)
        except Exception:
            log.exception("Error en el loop de recordatorio de reseña")
        await asyncio.sleep(REVIEW_REMINDER_POLL_SECONDS)


# PayPal invalida sola una orden no aprobada unas horas despues de creada -
# le damos el mismo margen antes de marcarla fallida por un 404 (en vez de
# esperar el corte general de PENDING_PAYMENT_MAX_HORAS).
PAYPAL_ORDER_NOT_FOUND_GRACIA_HORAS = 3


async def check_web_payment_status(order: dict):
    # Mismo corte que en Telegram (ver check_payment_status) - evita
    # reconsultar para siempre un checkout que el cliente abrio y abandono.
    if _horas_desde(order["updated_at"]) > PENDING_PAYMENT_MAX_HORAS:
        db.update_web_order(order["session_id"], step="pago_fallido")
        log.info(
            "Pago web abandonado (mas de %sh sin resolverse) para session_id=%s - se deja de reintentar.",
            PENDING_PAYMENT_MAX_HORAS, order["session_id"],
        )
        return

    if not _debe_chequear_pago(order):
        return  # todavia no toca (backoff) - se revisa de nuevo mas adelante

    # Camino de respaldo, igual que con dLocal Go - la confirmacion real pasa
    # por el webhook (y, en el caso de PayPal, tambien por la captura al
    # volver a /pago-exitoso/web/{session_id}); esto es solo por si ambos
    # fallaran. Cada gateway tiene su propia forma de consultar el estado -
    # ver order["gateway"], seteado al crear el pago en web_conversation.py.
    try:
        if order.get("gateway") == "paypal":
            paypal_order = await paypal_get_order(order["payment_request_id"])
            db.touch_last_checked_web(order["session_id"], datetime.utcnow().isoformat())
            paypal_status = paypal_order.get("status")  # CREATED|APPROVED|COMPLETED|VOIDED
            if paypal_status == "COMPLETED":
                await confirmar_pago_web(order["session_id"])
            elif paypal_status == "VOIDED":
                db.update_web_order(order["session_id"], step="pago_fallido")
                log.warning(
                    "El pago web (PayPal) de session_id=%s quedó en estado %s.",
                    order["session_id"], paypal_status,
                )
            return

        payment = await get_payment(order["payment_request_id"])
        db.touch_last_checked_web(order["session_id"], datetime.utcnow().isoformat())
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            # La orden ya no existe del lado del gateway - tipicamente una
            # orden de PayPal no aprobada que expira sola unas horas despues
            # de creada. Le damos el mismo margen que PayPal antes de darla
            # por fallida (en vez del corte general de 48h) - un 404
            # temprano podria ser un hipo pasajero, no necesariamente que ya
            # expiro. Si el cliente regresa, la herramienta de recuperacion
            # le genera una orden nueva (ver _buscar_pedido_por_correo en
            # web_conversation.py).
            if _horas_desde(order["created_at"]) > PAYPAL_ORDER_NOT_FOUND_GRACIA_HORAS:
                db.update_web_order(order["session_id"], step="pago_fallido")
                log.info(
                    "Orden de pago no encontrada (404) para session_id=%s tras "
                    "%sh - probablemente expiro sin aprobarse. Se marca como fallida.",
                    order["session_id"], PAYPAL_ORDER_NOT_FOUND_GRACIA_HORAS,
                )
            else:
                log.info(
                    "Orden de pago no encontrada (404) para session_id=%s, todavia "
                    "dentro del margen de %sh - se sigue reintentando.",
                    order["session_id"], PAYPAL_ORDER_NOT_FOUND_GRACIA_HORAS,
                )
        else:
            log.exception("Error consultando pago web pendiente para session_id=%s", order["session_id"])
        return
    except Exception:
        log.exception("Error consultando pago web pendiente para session_id=%s", order["session_id"])
        return

    status = payment.get("status")
    if status == "PAID":
        await confirmar_pago_web(order["session_id"])
        return

    if status in ("REJECTED", "CANCELLED", "EXPIRED"):
        db.update_web_order(order["session_id"], step="pago_fallido")
        log.warning(
            "El pago web de session_id=%s (email=%s) quedó en estado %s.",
            order["session_id"], order.get("email"), status,
        )


async def poll_web_suno_tasks_loop():
    while True:
        try:
            pending = db.find_unfinished_web_suno_tasks()
            log.info(
                "[poll_web_suno_tasks_loop] tick - %d pedido(s) web en generacion - mem=%.1fMB",
                len(pending), _memoria_mb(),
            )
            for order in pending:
                await check_and_deliver_web(order)
        except Exception:
            log.exception("Error en el loop de polling de Suno (web)")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


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
        language = order.get("language", "es")
        titulo_default = "Your song" if language == "en" else "Tu canción"
        lyrics_pdf_url = (
            f"{BASE_URL}/web/lyrics-pdf/{order['session_id']}"
            if language == "en" and order.get("final_lyric")
            else None
        )
        enviado = await enviar_cancion_por_correo(
            order["email"], order.get("final_title") or titulo_default, audio_urls,
            language=language, lyrics_pdf_url=lyrics_pdf_url,
        )
        if enviado:
            db.update_web_order(order["session_id"], delivered_email=1)
