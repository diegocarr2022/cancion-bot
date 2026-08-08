"""
*** NO SE USA POR AHORA ***
El flujo actual usa un link de pago FIJO (ver app/config.py:CLIP_PAYMENT_LINK)
y confirmacion manual via el comando /confirmar. Este archivo queda como
referencia por si mas adelante conectas la API de Clip para automatizar
tambien la confirmacion de pago (webhook en vez de confirmacion manual).

Cliente minimo para la API de Checkout de Clip (developer.clip.mx).

IMPORTANTE: valida el nombre exacto de los campos contra tu cuenta antes de
usarlo en produccion - Clip puede pedir campos adicionales segun tu tipo de
cuenta (KYC, moneda, etc). Esto es un punto de partida funcional, no la
documentacion oficial completa.
"""
import httpx

from app.config import CLIP_API_KEY, BASE_URL

CLIP_API_BASE = "https://api.clip.mx/v2"


async def create_payment_link(amount_centavos: int, description: str, external_reference: str) -> dict:
    """
    Crea un link de pago y le dice a Clip que nos avise (webhook_url) cuando
    se pague. `external_reference` es nuestro propio id (usamos el chat_id
    de Telegram) para poder reconciliar la notificacion despues.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{CLIP_API_BASE}/checkout",
            headers={"Authorization": f"Bearer {CLIP_API_KEY}"},
            json={
                "amount": amount_centavos,
                "currency": "MXN",
                "purchase_description": description,
                "external_reference": external_reference,
                "webhook_url": f"{BASE_URL}/clip/webhook",
                "redirection_url": {
                    "success": f"{BASE_URL}/pago-exitoso",
                    "error": f"{BASE_URL}/pago-fallido",
                },
            },
        )
        resp.raise_for_status()
        return resp.json()
