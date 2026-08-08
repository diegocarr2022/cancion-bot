"""
Cliente para la API de dLocal Go (docs.dlocalgo.com/integration-api).

Flujo:
1. create_payment() crea un cobro por pedido y devuelve un redirect_url
   (el link de pago que le mandamos al cliente) y un id.
2. Cuando el cliente paga, dLocal Go llama a nuestro notification_url con
   {"payment_id": "..."} (firmado con HMAC-SHA256).
3. Nosotros verificamos la firma con verify_signature() y despues llamamos
   get_payment() para confirmar el status real ("PAID", "REJECTED", etc.)
   - la notificacion en si NO trae el status, solo avisa que "algo cambio".
"""
import hashlib
import hmac

import httpx

from app.config import DLOCAL_API_KEY, DLOCAL_SECRET_KEY, DLOCAL_BASE_URL

AUTH_HEADER = f"Bearer {DLOCAL_API_KEY}:{DLOCAL_SECRET_KEY}"


async def create_payment(
    amount: float,
    currency: str,
    country: str,
    order_id: str,
    description: str,
    notification_url: str,
    success_url: str = "",
    back_url: str = "",
) -> dict:
    body = {
        "amount": amount,
        "currency": currency,
        "country": country,
        "order_id": order_id,
        "description": description,
        "notification_url": notification_url,
    }
    if success_url:
        body["success_url"] = success_url
    if back_url:
        body["back_url"] = back_url

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{DLOCAL_BASE_URL}/v1/payments",
            headers={"Authorization": AUTH_HEADER, "Content-Type": "application/json"},
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


async def get_payment(payment_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{DLOCAL_BASE_URL}/v1/payments/{payment_id}",
            headers={"Authorization": AUTH_HEADER},
        )
        resp.raise_for_status()
        return resp.json()


def verify_signature(raw_body: bytes, signature_header: str) -> bool:
    """
    raw_body: el cuerpo EXACTO (bytes) que mando dLocal Go, sin re-parsear/
    re-serializar (la firma se calcula sobre el string tal cual se envio).
    signature_header: el valor del header Authorization que manda dLocal Go,
    con forma "V2-HMAC-SHA256, Signature: <hex>".
    """
    if not signature_header or "Signature:" not in signature_header:
        return False

    received_signature = signature_header.split("Signature:")[-1].strip()

    message = DLOCAL_API_KEY + raw_body.decode("utf-8")
    expected_signature = hmac.new(
        DLOCAL_SECRET_KEY.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_signature, received_signature)
