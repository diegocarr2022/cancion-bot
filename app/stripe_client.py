"""
Cliente para Stripe (pagos EE.UU./USD, reemplaza a PayPal para el flujo web
en ingles - ver app/paypal_client.py, que se deja intacto por si quedan
pedidos viejos pendientes con ese gateway). Mismo patron que dlocal_client.py
y paypal_client.py: httpx crudo, sin el SDK oficial de Stripe, para no salirse
del estilo del resto del repo.

ACTUALIZACION (ago 2026): pedidos NUEVOS pasaron de la Payment Intents API a
la Checkout Sessions API (ui_mode="elements", create_checkout_session() mas
abajo) - necesario para poder activar Adaptive Pricing (deja pagar con
tarjetas de otros paises en su propia moneda; Stripe documenta textualmente
que "Adaptive Pricing isn't supported on the Payment Intents API") y porque
Stripe sugirio que mejora la aceptacion de American Express, que con
Payment Intents estaba fallando del lado del navegador (0 intentos
registrados con 2 tarjetas Amex reales de EE.UU. - ver conversacion). Sigue
siendo 100% embebido, sin redireccion, y la confirmacion real sigue
llegando por webhook - ahora checkout.session.completed en vez de
payment_intent.succeeded (ver app/main.py). create_payment_intent() y
get_payment_intent() se dejan intactas: siguen usandose para cualquier
pedido viejo que haya quedado con un payment_request_id tipo "pi_..." de
antes de este cambio (los nuevos son "cs_...").
"""
import hashlib
import hmac
import json
import logging
import time

import httpx

from app.config import STRIPE_SECRET, BASE_URL

log = logging.getLogger("cancion-bot")

STRIPE_BASE_URL = "https://api.stripe.com/v1"

# La cuenta de Stripe de Diego tiene fijada una version de API mas vieja que
# no soporta ui_mode="elements" - confirmado con el error real de Stripe:
# "Invalid ui_mode: elements. In order to use ui_mode: elements, you must
# upgrade to Stripe API version 2026-03-25.dahlia." Se manda este header
# SOLO en las llamadas de Checkout Sessions (create/get, mas abajo) en vez
# de cambiar la version default de toda la cuenta en el dashboard - asi no
# se arriesga a cambiar el comportamiento de ninguna otra integracion que
# use la cuenta sin querer.
STRIPE_API_VERSION = "2026-03-25.dahlia"

# Tolerancia recomendada por Stripe contra ataques de repeticion (nunca 0 -
# ver docs.stripe.com/webhooks#verify-manually).
WEBHOOK_TOLERANCE_SECONDS = 300


async def create_checkout_session(
    amount: float, currency: str, session_id: str, description: str, customer_email: str | None = None
) -> dict:
    """Devuelve {"client_secret": ..., "id": ...} - el "id" ahora es un
    Checkout Session id (formato "cs_..."), no un PaymentIntent id
    ("pi_..."). Mismo shape que create_payment_intent() para no tener que
    tocar el resto del flujo (web_conversation.py sigue guardando
    payment.get("client_secret")/payment["id"] igual que antes).

    customer_email: precarga el correo en la sesion (recibo, etc.) - PERO
    esto solo no alcanza para poder confirmar el pago del lado del
    navegador. Checkout Sessions (a diferencia del PaymentIntent viejo)
    exige que el frontend llame actions.updateEmail(...) antes de
    actions.confirm() o tira "An email address is required..." -
    confirmado con un error real de Stripe. Por eso ademas de mandarlo aca,
    /web/status y /web/chat devuelven "email" para que landing.py se lo
    pase a updateEmail() (ver montarStripe en LANDING_HTML_EN).

    ui_mode="elements" (no "embedded"): es el unico modo compatible con el
    Currency Selector Element que requiere Adaptive Pricing, y el que deja
    montar el Payment Element donde queramos en la pagina en vez de la caja
    preconstruida de Stripe. return_url es obligatorio aunque en este modo
    casi nunca se llega a usar (solo si el cliente elige un metodo de pago
    que si redirige, ej. algun banco) - reusa la misma pagina de retorno que
    ya existe para PayPal.

    Adaptive Pricing se activo a nivel cuenta en el dashboard
    (dashboard.stripe.com/settings/adaptive-pricing, hecho por Diego) - no
    se manda un parametro por sesion aca porque el primer intento con
    adaptive_pricing[enabled] dio 400 Bad Request y todavia no se confirmo
    el nombre/formato exacto del parametro contra un error real de Stripe
    (ver log agregado abajo). Si Adaptive Pricing no aparece solo con el
    toggle de cuenta, retomar esto."""
    amount_cents = int(round(amount * 100))
    data = {
        "mode": "payment",
        "ui_mode": "elements",
        "line_items[0][price_data][currency]": currency.lower(),
        "line_items[0][price_data][product_data][name]": description,
        "line_items[0][price_data][unit_amount]": amount_cents,
        "line_items[0][quantity]": 1,
        "return_url": f"{BASE_URL}/pago-exitoso/web/{session_id}",
        # metadata.session_id es como el webhook (checkout.session.completed)
        # recupera a que pedido de web_orders corresponde - mismo rol que
        # custom_id en PayPal / metadata.session_id en el PaymentIntent viejo.
        "metadata[session_id]": session_id,
    }
    if customer_email:
        data["customer_email"] = customer_email
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{STRIPE_BASE_URL}/checkout/sessions",
            headers={
                "Authorization": f"Bearer {STRIPE_SECRET}",
                "Stripe-Version": STRIPE_API_VERSION,
            },
            data=data,
        )
        if resp.status_code >= 400:
            # Stripe manda el motivo real del rechazo en el cuerpo (ej.
            # parametro invalido, capacidad no habilitada) - httpx no lo
            # incluye en el mensaje de raise_for_status(), y sin esto el
            # log solo dice "400 Bad Request" sin decir por que.
            log.error("Stripe rechazo la creacion de la Checkout Session: %s", resp.text)
        resp.raise_for_status()
        data = resp.json()
        return {"client_secret": data["client_secret"], "id": data["id"]}


async def get_checkout_session(checkout_session_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{STRIPE_BASE_URL}/checkout/sessions/{checkout_session_id}",
            headers={
                "Authorization": f"Bearer {STRIPE_SECRET}",
                "Stripe-Version": STRIPE_API_VERSION,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def create_payment_intent(amount: float, currency: str, session_id: str, description: str) -> dict:
    """LEGACY (ago 2026) - pedidos nuevos usan create_checkout_session() de
    arriba. Se deja sin borrar solo para que web_conversation.py pudiera
    revertir facil si hiciera falta; ya no se llama desde ningun lado nuevo.

    Devuelve {"client_secret": ..., "id": ...}. El monto va en la unidad
    minima de la moneda (centavos para USD) - a diferencia de PayPal/dLocal
    que reciben el monto "normal" con decimales."""
    amount_cents = int(round(amount * 100))
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{STRIPE_BASE_URL}/payment_intents",
            headers={"Authorization": f"Bearer {STRIPE_SECRET}"},
            data={
                "amount": amount_cents,
                "currency": currency.lower(),
                "description": description,
                "automatic_payment_methods[enabled]": "true",
                # metadata.session_id es como el webhook (payment_intent.succeeded)
                # recupera a que pedido de web_orders corresponde - mismo rol
                # que custom_id en PayPal.
                "metadata[session_id]": session_id,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return {"client_secret": data["client_secret"], "id": data["id"]}


async def get_payment_intent(payment_intent_id: str) -> dict:
    """LEGACY (ago 2026) - se mantiene solo para el polling de respaldo de
    pedidos con payment_request_id tipo "pi_..." creados antes de migrar a
    Checkout Sessions (ver check_web_payment_status en app/main.py, que
    ramifica por prefijo "pi_" vs "cs_"). Pedidos nuevos usan
    get_checkout_session()."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{STRIPE_BASE_URL}/payment_intents/{payment_intent_id}",
            headers={"Authorization": f"Bearer {STRIPE_SECRET}"},
        )
        resp.raise_for_status()
        return resp.json()


def verify_webhook_signature(raw_body: bytes, sig_header: str, webhook_secret: str) -> dict | None:
    """Verifica la firma de un webhook de Stripe manualmente (algoritmo
    documentado en docs.stripe.com/webhooks#verify-manually, confirmado
    palabra por palabra antes de escribir esto):
    1. El header Stripe-Signature trae "t=<timestamp>,v1=<firma>[,v0=...]".
    2. signed_payload = "{timestamp}.{raw_body}" (concatenacion literal).
    3. HMAC-SHA256(webhook_secret, signed_payload) debe igualar la firma v1,
       comparado con tiempo constante.
    4. El timestamp no debe ser mas viejo que WEBHOOK_TOLERANCE_SECONDS (evita
       ataques de repeticion).

    Devuelve el dict ya parseado del evento si la firma es valida, o None si
    no lo es (firma invalida, timestamp vencido, o header mal formado)."""
    if not webhook_secret or not sig_header:
        return None

    partes = dict(
        item.split("=", 1) for item in sig_header.split(",") if "=" in item
    )
    timestamp = partes.get("t")
    firma_recibida = partes.get("v1")
    if not timestamp or not firma_recibida:
        return None

    if abs(time.time() - int(timestamp)) > WEBHOOK_TOLERANCE_SECONDS:
        return None

    signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
    firma_esperada = hmac.new(
        webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(firma_esperada, firma_recibida):
        return None

    return json.loads(raw_body)
