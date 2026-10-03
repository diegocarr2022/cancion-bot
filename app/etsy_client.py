"""Canje de pedidos de Etsy (oct 2026): el Worker de Cloudflare de la tienda de
Etsy valida el numero de pedido contra Etsy y lleva los creditos. Este modulo
solo le habla a ese Worker (POST /api/redeem), servidor a servidor, con la llave
ETSY_REDEEM_KEY - la llave nunca llega al navegador.

check()   -> el pedido es valido y cuantos creditos le quedan (no gasta nada).
consume() -> gasta UN credito para esta sesion (idempotente: misma sesion, mismo
             credito; un reintento no cobra dos veces).
Ambos devuelven un dict {"ok": bool, "error": str|None, ...}; nunca lanzan.
"""
import logging

import httpx

from app.config import ETSY_WORKER_URL, ETSY_REDEEM_KEY, ETSY_SONG_PRODUCT

log = logging.getLogger("cancion-bot")


async def _redeem(action: str, order_number: str, session_id: str | None = None) -> dict:
    payload = {"action": action, "order_number": order_number, "product": ETSY_SONG_PRODUCT}
    if session_id:
        payload["session_id"] = session_id
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{ETSY_WORKER_URL}/api/redeem",
                headers={"x-redeem-key": ETSY_REDEEM_KEY},
                json=payload,
            )
        data = r.json()
    except Exception:
        log.exception("No se pudo hablar con el Worker de Etsy (%s)", action)
        return {"ok": False, "error": "unavailable"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "unavailable"}
    return data


async def check(order_number: str) -> dict:
    return await _redeem("check", order_number)


async def consume(order_number: str, session_id: str) -> dict:
    return await _redeem("consume", order_number, session_id)
