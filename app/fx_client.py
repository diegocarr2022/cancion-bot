"""
Tipo de cambio USD->MXN en tiempo real, usado SOLO para armar el precio en
pesos que se le manda a Stripe en el checkout de EE.UU. (ver
web_conversation.crear_link_pago) - Adaptive Pricing exige que el precio
este en una moneda de liquidacion real de la cuenta (MXN, en el caso de
Diego), asi que el monto en pesos tiene que corresponder de verdad al
precio en dolares que se promociona ($27 USD), o el cliente termina pagando
de mas o de menos cuando Adaptive Pricing hace la conversion real al pagar.

Un tipo de cambio fijo en una variable de entorno se desactualiza solo con
el tiempo (exactamente lo que paso: se puso 18.5 "al aire" y la tasa real
resulto ser ~16.95, una diferencia de mas de $2 USD de mas por pedido) - en
vez de eso, esto consulta una tasa real en cada checkout nuevo, con cache
de 1 hora en memoria (no tiene sentido pedirla en cada request, la tasa no
se mueve tan rapido) y con la variable de entorno USD_TO_MXN_RATE (ver
config.py) como respaldo si la consulta fallara por cualquier motivo -
nunca debe bloquear la creacion de un pedido por esto.

frankfurter.app: servicio gratuito basado en tasas del Banco Central
Europeo, sin necesidad de API key (a diferencia de la mayoria de las
alternativas) - suficiente para esto, no hace falta nada mas preciso ya que
Stripe de todas formas hace su propia conversion final al momento del pago.
"""
import logging
import time

import httpx

from app.config import USD_TO_MXN_RATE as _TASA_RESPALDO

log = logging.getLogger("cancion-bot")

# .app redirige (301) a este dominio - se usa el destino final directo para
# no depender de que httpx siga redirecciones (no lo hace por default).
FX_API_URL = "https://api.frankfurter.dev/v1/latest"
CACHE_SEGUNDOS = 3600  # 1 hora - la tasa no se mueve tan rapido como para pedirla mas seguido

_cache: dict = {"tasa": None, "consultada_en": 0.0}


async def get_usd_to_mxn_rate() -> float:
    """Devuelve cuantos MXN vale 1 USD ahora mismo. Cachea en memoria por
    CACHE_SEGUNDOS - si la consulta en vivo falla (red caida, respuesta
    inesperada), usa USD_TO_MXN_RATE de config.py como respaldo y lo loguea
    como advertencia, pero NUNCA lanza una excepcion - un pedido no se debe
    caer por no poder consultar el tipo de cambio."""
    ahora = time.time()
    if _cache["tasa"] is not None and (ahora - _cache["consultada_en"]) < CACHE_SEGUNDOS:
        return _cache["tasa"]

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(FX_API_URL, params={"base": "USD", "symbols": "MXN"})
            resp.raise_for_status()
            data = resp.json()
            tasa = float(data["rates"]["MXN"])
    except Exception:
        log.warning(
            "No se pudo consultar el tipo de cambio USD->MXN en vivo - usando el "
            "respaldo de USD_TO_MXN_RATE=%s. Si esto pasa seguido, revisar "
            "frankfurter.app o cambiar de proveedor.",
            _TASA_RESPALDO,
        )
        return _TASA_RESPALDO

    _cache["tasa"] = tasa
    _cache["consultada_en"] = ahora
    return tasa
