"""
Cliente para PayPal (pagos EE.UU./USD). Mismo patron que dlocal_client.py:
httpx crudo (sin SDK), sandbox/live por env var, y la notificacion del
webhook dispara una consulta a la API real antes de confiar en el estado.

ACTUALIZACION (ago 2026): Stripe (app/stripe_client.py) reemplazo a PayPal
como pasarela para pedidos NUEVOS en el flujo EN/US - la redireccion
completa de PayPal (y el paso extra de "abre una cuenta y paga ahora" en su
checkout de invitado) resulto ser friccion real con trafico pagado en vivo.
Este archivo se queda intacto y sigue en uso solo para pedidos viejos que ya
hayan quedado con gateway=="paypal" pendientes en la base de datos.

Flujo (a diferencia de dLocal Go, que confirma el pago solo con el webhook):
1. create_order() -> se redirige al cliente al link de aprobacion de PayPal.
2. El cliente aprueba en PayPal y vuelve al return_url
   (/pago-exitoso/web/{session_id} en main.py).
3. Ahi mismo se llama capture_order() para efectivamente cobrar - PayPal
   requiere este paso explicito, "aprobado" todavia no es "cobrado".
4. El webhook de PAYMENT.CAPTURE.COMPLETED / CHECKOUT.ORDER.APPROVED queda
   como red de seguridad, por si el cliente cierra la pestaña antes de que
   el return_url termine de cargar (mismo rol que el webhook de dLocal Go).
"""
import httpx

from app.config import PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_BASE_URL, PAYPAL_WEBHOOK_ID


async def _get_access_token() -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{PAYPAL_BASE_URL}/v1/oauth2/token",
            auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def create_order(
    amount: float,
    currency: str,
    order_id: str,
    description: str,
    return_url: str,
    cancel_url: str,
) -> dict:
    """Devuelve {"redirect_url": ..., "id": ...} - mismo shape que
    dlocal_client.create_payment(), para que web_conversation.py pueda
    tratar ambas pasarelas de forma intercambiable."""
    token = await _get_access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{PAYPAL_BASE_URL}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "reference_id": order_id,
                        "custom_id": order_id,
                        "description": description,
                        "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
                    }
                ],
                "application_context": {
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                    "user_action": "PAY_NOW",
                    "shipping_preference": "NO_SHIPPING",
                    # Sin esto PayPal muestra primero la pantalla de login y
                    # deja "pagar con tarjeta sin cuenta" como link chiquito
                    # abajo - mal para trafico frio de Google Ads que en su
                    # mayoria no tiene cuenta de PayPal. "BILLING" abre
                    # directo el formulario de tarjeta (sigue habiendo un
                    # link para loguearse, por si si tienen cuenta).
                    "landing_page": "BILLING",
                },
            },
        )
        resp.raise_for_status()
        data = resp.json()
        approve_url = next(link["href"] for link in data["links"] if link["rel"] == "approve")
        return {"redirect_url": approve_url, "id": data["id"]}


async def capture_order(paypal_order_id: str) -> dict:
    """Cobra de verdad una orden ya aprobada por el cliente. Si la orden ya
    estaba capturada, PayPal devuelve un error 422 UNPROCESSABLE_ENTITY con
    issue "ORDER_ALREADY_CAPTURED" - el llamador debe tolerarlo (ver
    /pago-exitoso/web/{session_id} en main.py, que puede recibir esta misma
    orden dos veces: una del webhook y otra del propio return_url)."""
    token = await _get_access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{PAYPAL_BASE_URL}/v2/checkout/orders/{paypal_order_id}/capture",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


async def get_order(paypal_order_id: str) -> dict:
    token = await _get_access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{PAYPAL_BASE_URL}/v2/checkout/orders/{paypal_order_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        return resp.json()


async def verify_webhook_signature(headers: dict, raw_body: dict) -> bool:
    """A diferencia de dLocal Go (HMAC-SHA256 calculado localmente, ver
    dlocal_client.verify_signature), PayPal exige verificar la firma
    llamando a su propia API: se le manda de vuelta el evento crudo junto
    con los headers que PayPal agrego a la notificacion, y ellos confirman
    si es legitimo. `headers` debe venir en minusculas (los headers HTTP no
    distinguen mayusculas/minusculas, pero los nombres de campo que espera
    PayPal si son exactos)."""
    if not PAYPAL_WEBHOOK_ID:
        return False
    token = await _get_access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{PAYPAL_BASE_URL}/v1/notifications/verify-webhook-signature",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "auth_algo": headers.get("paypal-auth-algo"),
                "cert_url": headers.get("paypal-cert-url"),
                "transmission_id": headers.get("paypal-transmission-id"),
                "transmission_sig": headers.get("paypal-transmission-sig"),
                "transmission_time": headers.get("paypal-transmission-time"),
                "webhook_id": PAYPAL_WEBHOOK_ID,
                "webhook_event": raw_body,
            },
        )
        resp.raise_for_status()
        return resp.json().get("verification_status") == "SUCCESS"
