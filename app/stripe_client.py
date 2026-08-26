"""
Cliente para Stripe (pagos EE.UU./USD, reemplaza a PayPal para el flujo web
en ingles - ver app/paypal_client.py, que se deja intacto por si quedan
pedidos viejos pendientes con ese gateway). Mismo patron que dlocal_client.py
y paypal_client.py: httpx crudo, sin el SDK oficial de Stripe, para no salirse
del estilo del resto del repo.

A diferencia de PayPal (redireccion completa fuera del sitio, con un paso
extra de "capture" al volver), Stripe se usa aca en modo EMBEBIDO: se crea un
PaymentIntent, se le manda su client_secret al frontend, y el cliente paga
sin salir nunca de la pagina (Stripe Payment Element + confirmPayment con
redirect: 'if_required'). La confirmacion real de que el pago se completo
sigue llegando por webhook, igual que con dLocal/PayPal - ver
payment_intent.succeeded en app/main.py.
"""
import hashlib
import hmac
import json
import time

import httpx

from app.config import STRIPE_SECRET

STRIPE_BASE_URL = "https://api.stripe.com/v1"

# Tolerancia recomendada por Stripe contra ataques de repeticion (nunca 0 -
# ver docs.stripe.com/webhooks#verify-manually).
WEBHOOK_TOLERANCE_SECONDS = 300


async def create_payment_intent(amount: float, currency: str, session_id: str, description: str) -> dict:
    """Devuelve {"client_secret": ..., "id": ...}. El monto va en la unidad
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
