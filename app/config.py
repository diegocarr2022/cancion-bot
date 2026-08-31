import logging
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

log = logging.getLogger("cancion-bot")

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
ACEDATACLOUD_API_TOKEN = os.environ["ACEDATACLOUD_API_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
DB_PATH = os.environ.get("DB_PATH", "/data/orders.db")

# --- dLocal Go ---
DLOCAL_API_KEY = os.environ["DLOCAL_API_KEY"]
DLOCAL_SECRET_KEY = os.environ["DLOCAL_SECRET_KEY"]
# "sandbox" mientras pruebas con tarjetas de prueba, "live" para cobrar de verdad
DLOCAL_ENV = os.environ.get("DLOCAL_ENV", "sandbox")
DLOCAL_BASE_URL = (
    "https://api.dlocalgo.com" if DLOCAL_ENV == "live" else "https://api-sbx.dlocalgo.com"
)

PRECIO_MXN = float(os.environ.get("PRECIO_MXN", "197"))
PRECIO_TEXTO = os.environ.get("PRECIO_TEXTO", "$197 MXN")

# --- Precios por pais (solo landing web - Telegram sigue solo en Mexico) ---
# Cada pais tiene un dict de "tiers" (por ahora casi todos tienen un unico
# tier "song" - EE.UU. es el unico con un segundo tier "song_video", el
# upsell de video, ver ENABLE_VIDEO_TIER mas abajo). Precios configurables
# por environment (por si cambia el tipo de cambio) con un default ya
# calculado - todos terminan en el digito "7" a proposito (la misma
# convencion que ya usabamos en Mexico: 197 en vez de 199 - un influencer que
# vende mucho le recomendo a Diego este patron). El pais se elige con el
# parametro ?country=<codigo> en el link del anuncio (ver app/landing.py) -
# sin ese parametro, el default sigue siendo Mexico.
PAISES_SOPORTADOS = {
    "MX": {
        "currency": "MXN",
        "tiers": {"song": {"amount": PRECIO_MXN, "texto": PRECIO_TEXTO}},
    },
    "PE": {
        "currency": "PEN",
        "tiers": {
            "song": {
                "amount": float(os.environ.get("PRECIO_PEN", "37")),
                "texto": os.environ.get("PRECIO_TEXTO_PEN", "S/ 37"),
            }
        },
    },
    "CO": {
        "currency": "COP",
        "tiers": {
            "song": {
                "amount": float(os.environ.get("PRECIO_COP", "36727")),
                "texto": os.environ.get("PRECIO_TEXTO_COP", "$36,727 COP"),
            }
        },
    },
    # EE.UU. (ago 2026): no se puede cobrar via dLocal Go ni Mercado Pago -
    # ninguno de los dos acepta compradores fisicamente en EE.UU., solo
    # metodos de pago locales de LatAm. Se paga via PayPal (ver
    # app/paypal_client.py). "song_video" es el upsell de video (Fase 2,
    # detras de ENABLE_VIDEO_TIER) - cancion + video hecho con 3-5 fotos del
    # cliente sincronizado al audio.
    "US": {
        "currency": "USD",
        "tiers": {
            # Precio de LANZAMIENTO (ver LAUNCH_PRICE_ENDS_AT mas abajo) - el
            # precio real que se cobra despues de esa fecha es
            # PRECIO_USD_SONG_REGULAR, resuelto dinamicamente en
            # get_precio_pais(), no aca (este dict se arma una sola vez al
            # importar el modulo, no puede depender de "que hora es ahora").
            "song": {
                "amount": float(os.environ.get("PRECIO_USD_SONG", "27")),
                "texto": os.environ.get("PRECIO_TEXTO_USD_SONG", "$27 USD"),
            },
            "song_video": {
                "amount": float(os.environ.get("PRECIO_USD_VIDEO", "49")),
                "texto": os.environ.get("PRECIO_TEXTO_USD_VIDEO", "$49 USD"),
            },
        },
    },
}
PAIS_DEFAULT = "MX"

# --- Precio de lanzamiento (EE.UU., tier "song") ---
# Fecha CALENDARIO fija (no relativa al momento en que arranca el proceso -
# ver _precio_lanzamiento_vigente) hasta la cual rige el precio de
# lanzamiento ($27). Despues de esta fecha, el precio real cobrado sube solo
# a PRECIO_USD_SONG_REGULAR - automaticamente, sin tocar codigo. El timer
# retro de la landing (landing.py) muestra esta MISMA fecha, asi que lo que
# el visitante ve contando y lo que realmente se le cobra son siempre el
# mismo numero - nunca una cuenta regresiva decorativa que no corresponde a
# nada real (ver discusion sobre countdowns falsos y la FTC).
#
# IMPORTANTE: actualiza esta variable en Render (env var LAUNCH_PRICE_ENDS_AT)
# para que coincida con la fecha real en la que arranca la campaña de Google
# Ads - el default de aca abajo es solo un placeholder de 14 dias.
LAUNCH_PRICE_ENDS_AT = os.environ.get("LAUNCH_PRICE_ENDS_AT", "2026-08-30T23:59:59+00:00")
PRECIO_USD_SONG_REGULAR = float(os.environ.get("PRECIO_USD_SONG_REGULAR", "39.90"))
PRECIO_TEXTO_USD_SONG_REGULAR = os.environ.get("PRECIO_TEXTO_USD_SONG_REGULAR", "$39.90 USD")


def _precio_lanzamiento_vigente() -> bool:
    try:
        limite = datetime.fromisoformat(LAUNCH_PRICE_ENDS_AT)
    except ValueError:
        return True  # fecha mal formada -> preferimos no subir el precio por error de config
    if limite.tzinfo is None:
        limite = limite.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < limite


def get_precio_pais(country_code: str | None, tier: str = "song") -> dict:
    """Devuelve {"currency", "amount", "texto"} para el codigo de pais y tier
    dados (ej. country_code="US", tier="song_video"). Si el pais no es uno de
    los soportados (o viene vacio/mal armado), cae de vuelta a Mexico por
    seguridad - preferimos cobrar en un pais soportado de mas que fallar o
    cobrar mal. Si el tier no existe para ese pais (ej. "song_video" en
    Mexico), cae de vuelta al tier "song" - todos los paises lo tienen.

    EE.UU./song es el unico caso con precio dependiente de la fecha (precio
    de lanzamiento vs. regular, ver LAUNCH_PRICE_ENDS_AT) - se resuelve aca,
    evaluado en cada llamada, para que siempre refleje la fecha real."""
    codigo = (country_code or "").strip().upper()
    pais = PAISES_SOPORTADOS.get(codigo, PAISES_SOPORTADOS[PAIS_DEFAULT])
    datos_tier = pais["tiers"].get(tier, pais["tiers"]["song"])

    if codigo == "US" and tier == "song" and not _precio_lanzamiento_vigente():
        return {
            "currency": pais["currency"],
            "amount": PRECIO_USD_SONG_REGULAR,
            "texto": PRECIO_TEXTO_USD_SONG_REGULAR,
        }

    return {
        "currency": pais["currency"],
        "amount": datos_tier["amount"],
        "texto": datos_tier["texto"],
    }


# --- Precio en pesos para visitantes en Mexico en la landing en ingles ---
# ago 2026: tunecraft.studio esta detras de Cloudflare, que manda gratis el
# pais real del visitante en el header CF-IPCountry (sin llamar a ningun
# servicio externo de geolocalizacion, sin limite de rate) - ver su uso en
# main.py (/cancion y /web/session). Un visitante que entra a la landing en
# INGLES y es detectado en Mexico ve/paga este precio en MXN en vez del USD
# normal - mismo patron que ya usa al menos un competidor investigado
# (songlygift.com: precio redondo en pesos mostrado directo, no una
# conversion). A diferencia de Adaptive Pricing de Stripe (se probo y se
# revirtio antes, ver el comentario largo en crear_link_pago en
# web_conversation.py): esto es un tipo de cambio FIJO que Diego controla a
# mano (no uno de mercado en vivo, y no pasa por el servicio de conversion
# de Stripe con su comision de 2-4%) - el Checkout Session se crea directo
# en MXN por este monto ya fijado, sin conversion de por medio. El pais de
# la orden en si (gateway=Stripe, "US") NO cambia con esto - solo la
# moneda/monto que se muestra y se cobra.
PRECIO_TIPO_CAMBIO_MXN_EN = float(os.environ.get("PRECIO_TIPO_CAMBIO_MXN_EN", "17"))


def get_precio_en_mx(tier: str = "song") -> dict:
    """Precio en MXN para un visitante de la landing en ingles detectado en
    Mexico - se deriva automaticamente del precio en USD vigente (respeta
    precio de lanzamiento vs. regular, ver get_precio_pais/_precio_lanzamiento_vigente
    arriba) multiplicado por PRECIO_TIPO_CAMBIO_MXN_EN, redondeado a un
    numero entero limpio (sin centavos, como el resto de precios de
    Tunecraft)."""
    precio_usd = get_precio_pais("US", tier)
    monto = round(precio_usd["amount"] * PRECIO_TIPO_CAMBIO_MXN_EN)
    return {"currency": "MXN", "amount": float(monto), "texto": f"${monto:,} MXN"}


def get_precio_en_mx_was() -> str:
    """Version 'tachada' (precio regular, antes del descuento de
    lanzamiento) del precio en MXN de arriba - solo para el badge de
    descuento de la landing en ingles cuando se le muestra el precio en
    pesos a un visitante detectado en Mexico."""
    monto = round(PRECIO_USD_SONG_REGULAR * PRECIO_TIPO_CAMBIO_MXN_EN)
    return f"${monto:,} MXN"


def resolve_precio_orden(country_code: str | None, tier: str = "song", price_override: str | None = None) -> dict:
    """Envoltorio sobre get_precio_pais que respeta el override de precio de
    una orden YA CREADA (ver columna price_override en web_orders, db.py).
    Usar esta funcion (no get_precio_pais directo) en cualquier punto que
    recalcule el precio de una orden en curso (finalizar letra, recuperar
    pedido por correo, etc.) para que nunca se desincronice del precio que
    ya se le mostro/cobro originalmente en /web/session - la razon completa
    de por que esto importa esta en el comentario sobre Adaptive Pricing en
    crear_link_pago (web_conversation.py)."""
    if price_override == "mx_en":
        return get_precio_en_mx(tier)
    if price_override == "recovery":
        return get_precio_recovery(tier)
    return get_precio_pais(country_code, tier)


# --- Cupon de recuperacion de carrito abandonado (ago 2026) ---
# Pedidos que llegaron a aprobar la letra (ya se genero un link de pago) pero
# nunca pagaron, con correo - se les manda un correo con un precio especial
# de una sola vez para tratar de rescatar la venta (ver poll_recovery_email_loop
# en main.py). Diego ya pago el clic de publicidad que trajo a este visitante -
# cualquier venta que se rescate con este precio menor sigue siendo ganancia
# neta, no hace falta que iguale el precio normal. Solo tier "song" (el unico
# que existe en la practica hoy) y solo el flujo en ingles/Stripe, mismo
# criterio que el resto de features nuevas de esta sesion.
PRECIO_RECOVERY_USD = float(os.environ.get("PRECIO_RECOVERY_USD", "19.99"))
PRECIO_TEXTO_RECOVERY_USD = os.environ.get("PRECIO_TEXTO_RECOVERY_USD", "$19.99 USD")
# Horas minimas desde la ultima actualizacion del pedido antes de mandar el
# correo de recuperacion - suficiente margen para que el cliente no este
# todavia a mitad de pagar (ver poll_recovery_email_loop en main.py).
RECOVERY_EMAIL_MIN_HOURS = float(os.environ.get("RECOVERY_EMAIL_MIN_HOURS", "2"))


def get_precio_recovery(tier: str = "song") -> dict:
    return {"currency": "USD", "amount": PRECIO_RECOVERY_USD, "texto": PRECIO_TEXTO_RECOVERY_USD}


# Tu chat_id de Telegram (el del administrador). Se usa para el comando
# /confirmar de respaldo (por si el webhook de dLocal Go fallara) y para que
# te avisen de pedidos nuevos. Lo obtienes hablandole a @userinfobot en Telegram.
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Contraseña para entrar al panel de admin en /admin (ver main.py). El
# usuario no importa (podes poner cualquier cosa al loguearte), solo se
# valida la contraseña. Si no la configuras, el panel queda deshabilitado
# por seguridad (nunca lo dejamos abierto por defecto).
ADMIN_PANEL_PASSWORD = os.environ.get("ADMIN_PANEL_PASSWORD", "")

# --- Mailgun (envio de la cancion por correo, para los pedidos de la landing
# web) ---
# ago 2026: reemplaza a Gmail SMTP - Diego no tiene el dominio
# tunecraft.studio conectado a una cuenta de Gmail/Workspace, y Gmail SMTP
# tampoco esta pensado para correo transaccional automatizado de un negocio
# real (limite bajo, riesgo de que lo marquen como sospechoso). Mailgun
# permite mandar desde una direccion del dominio propio sin necesitar un
# buzon de correo real - solo verificar el dominio con unos registros DNS.
# MAILGUN_API_KEY: se genera en app.mailgun.com -> Sending -> Domain
# settings -> API keys. ES SECRETA.
# MAILGUN_DOMAIN: el dominio (o subdominio, ej. "mg.tunecraft.studio") que
# se verifico en Mailgun con esos registros DNS. No es secreto.
# MAILGUN_FROM_EMAIL: la direccion completa que va a ver el cliente como
# remitente, ej. "Tunecraft <hello@mg.tunecraft.studio>" - tiene que ser
# una direccion del MAILGUN_DOMAIN de arriba (Mailgun no deja mandar "from"
# de un dominio que no verificaste). Si no se configura, se arma un default
# razonable a partir de MAILGUN_DOMAIN (ver email_client.py).
# Si no se configuran API_KEY/DOMAIN, el envio de correo se salta
# silenciosamente (se loguea una advertencia) - el link de descarga sigue
# apareciendo en el chat web de todas formas, asi que no bloquea la entrega.
MAILGUN_API_KEY = os.environ.get("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.environ.get("MAILGUN_DOMAIN", "")
MAILGUN_FROM_EMAIL = os.environ.get("MAILGUN_FROM_EMAIL", "")

# --- Intervalo de los loops de fondo (segundos) ---
# Subidos temporalmente (de 20/30s a 60/90s por default) mientras se
# diagnostica una fuga de memoria en Render (ago 2026) - menos vueltas por
# minuto = menos presion de memoria mientras encontramos la causa real.
# Configurable por environment para poder ajustarlo sin tocar codigo.
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))
POLL_INTERVAL_STUCK_SECONDS = int(os.environ.get("POLL_INTERVAL_STUCK_SECONDS", "90"))

# Cuantas horas se sigue reintentando un pago que quedo "pendiente" sin que
# dLocal Go nunca lo mueva a un estado final (PAID/REJECTED/CANCELLED/
# EXPIRED) - pasa cuando alguien abre el link de pago y lo abandona sin
# completar ni cancelar nada. Sin este limite, los loops de polling
# reconsultan esos mismos pagos abandonados PARA SIEMPRE, generando
# llamadas HTTP repetidas sin fin - ver el diagnostico de fuga de memoria
# de ago 2026.
PENDING_PAYMENT_MAX_HORAS = int(os.environ.get("PENDING_PAYMENT_MAX_HORAS", "48"))

# Backoff: durante la primera hora de un pago pendiente se revisa en CADA
# vuelta del loop (POLL_INTERVAL_SECONDS) porque es cuando es mas probable
# que el cliente realmente termine de pagar. Pasada esa hora, se espacia a
# revisar cada PENDING_PAYMENT_BACKOFF_MINUTOS minutos en vez de cada
# vuelta - asi, si se acumulan varios pedidos abandonados al mismo tiempo
# (ej. una campana con mucho trafico), no se multiplica el numero de
# llamadas HTTP por cada uno de ellos cada minuto.
PENDING_PAYMENT_BACKOFF_HORAS = float(os.environ.get("PENDING_PAYMENT_BACKOFF_HORAS", "1"))
PENDING_PAYMENT_BACKOFF_MINUTOS = int(os.environ.get("PENDING_PAYMENT_BACKOFF_MINUTOS", "30"))

# --- Meta Pixel / Conversions API ---
# META_PIXEL_ID: identificador del Pixel dedicado a cancion-bot (no es
# secreto, se usa tambien del lado del navegador en landing.py).
# META_CAPI_ACCESS_TOKEN: token generado en Events Manager > Configuracion >
# Conversions API > Generar token de acceso - ESTE SI ES SECRETO, solo va
# como variable de entorno (nunca en el codigo ni en el chat). Si falta,
# el envio de eventos a Meta se salta silenciosamente (se loguea una
# advertencia) - no bloquea la entrega de la cancion.
META_PIXEL_ID = os.environ.get("META_PIXEL_ID", "")
META_CAPI_ACCESS_TOKEN = os.environ.get("META_CAPI_ACCESS_TOKEN", "")

# --- Google Analytics 4 / Google Ads conversion tracking ---
# GA_MEASUREMENT_ID: ID de la propiedad de GA4 (formato "G-XXXXXXXXXX"),
# Admin > Flujos de datos > tu flujo web > "ID de medicion". No es secreto.
# GOOGLE_ADS_CONVERSION_ID: ID de la cuenta de Google Ads (formato
# "AW-XXXXXXXXXX"), aparece al crear cualquier accion de conversion.
# GOOGLE_ADS_CONVERSION_LABEL: el label especifico de la accion de
# conversion de "Compra" (Herramientas > Conversiones > tu accion >
# "Configuracion de la etiqueta"). Ninguno de los 3 es secreto (van del lado
# del navegador igual que META_PIXEL_ID) - si falta alguno, la landing sigue
# funcionando igual, simplemente sin ese tracking especifico (ver
# google_ads_script() en landing.py).
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "")
GOOGLE_ADS_CONVERSION_ID = os.environ.get("GOOGLE_ADS_CONVERSION_ID", "")
GOOGLE_ADS_CONVERSION_LABEL = os.environ.get("GOOGLE_ADS_CONVERSION_LABEL", "")
# Codigo de prueba opcional (pestaña "Test Events" en Events Manager) - solo
# se usa mientras se esta verificando que los eventos lleguen bien.
META_CAPI_TEST_EVENT_CODE = os.environ.get("META_CAPI_TEST_EVENT_CODE", "")

# --- Trustpilot (solo flujo EN/EE.UU. - ver Diego: "en EE.UU. Trustpilot es
# muy importante") ---
# URL publica de "escribir una reseña" del perfil de Tunecraft, formato
# https://www.trustpilot.com/evaluate/tunecraft.studio - se consigue al crear
# el perfil de empresa en business.trustpilot.com. No es secreto. Si esta
# vacio, no se muestra ningun pedido de reseña ni se manda el recordatorio -
# la entrega funciona igual sin esto configurado.
TRUSTPILOT_REVIEW_URL = os.environ.get("TRUSTPILOT_REVIEW_URL", "")

# --- PayPal (pagos en USD para EE.UU. - ver app/paypal_client.py) ---
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "")
# ID del webhook configurado en el Developer Dashboard de PayPal - necesario
# para verify_webhook_signature() (PayPal exige verificar contra su propia
# API, a diferencia de dLocal Go que se verifica con HMAC local).
PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID", "")
# "sandbox" mientras pruebas con cuentas de prueba, "live" para cobrar de verdad
PAYPAL_ENV = os.environ.get("PAYPAL_ENV", "sandbox")
PAYPAL_BASE_URL = (
    "https://api-m.paypal.com" if PAYPAL_ENV == "live" else "https://api-m.sandbox.paypal.com"
)

# --- Stripe (pagos en USD para EE.UU. - reemplaza a PayPal, ver
# app/stripe_client.py) - checkout EMBEBIDO en la misma landing, sin
# redireccion, a diferencia de PayPal. Nombres de variable elegidos por Diego
# al crearlas en Render, se respetan tal cual (no renombrar).
STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")  # publishable key (pk_...), no es secreta, va al navegador
STRIPE_SECRET = os.environ.get("STRIPE_SECRET", "")  # secret key (sk_...), servidor unicamente
STRIPE_ENVIROMENT = os.environ.get("STRIPE_ENVIROMENT", "SANDBOX").strip().upper()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# A diferencia de PAYPAL_ENV/DLOCAL_ENV, Stripe no necesita esta variable
# para funcionar - el tipo de clave (sk_test_ vs sk_live_) ya determina el
# modo. Se usa solo como chequeo de seguridad extra: si no coincide con el
# ambiente declarado, es exactamente el mismo tipo de mezcla que causo el
# problema de PAYPAL_ENV/DLOCAL_ENV mas temprano hoy (env pisado sin que las
# credenciales coincidieran) - mejor detectarlo temprano en el log que
# descubrirlo con un cliente real atorado.
if STRIPE_SECRET:
    _es_live_key = STRIPE_SECRET.startswith("sk_live_")
    _deberia_ser_live = STRIPE_ENVIROMENT == "LIVE"
    if _es_live_key != _deberia_ser_live:
        log.warning(
            "STRIPE_ENVIROMENT=%s pero STRIPE_SECRET %s de tipo live (%s...) - "
            "revisa que ambas variables correspondan al mismo ambiente.",
            STRIPE_ENVIROMENT, "SI es" if _es_live_key else "NO es", STRIPE_SECRET[:12],
        )

# --- Marca (ago 2026) ---
# Nombre de marca para el lado en ingles/EE.UU. (dominio tunecraft.studio) -
# el lado en espanol (Telegram + landing MX/PE/CO) se queda sin cambios por
# ahora, se va a renombrar aparte mas adelante. Constante compartida (en vez
# de hardcodear el string en cada archivo) para que ese proximo rename sea
# un solo lugar a tocar, no una busqueda y reemplazo por todo el repo.
BRAND_NAME_EN = "Tunecraft"

# --- Upsell de video (Fase 2 - fotos del cliente + cancion = video slideshow) ---
# Apagado por default: se activa una vez que el flujo base en ingles (solo
# cancion, via PayPal) ya este vendiendo. Ver app/video_client.py.
ENABLE_VIDEO_TIER = os.environ.get("ENABLE_VIDEO_TIER", "false").lower() == "true"
MEDIA_DIR = os.environ.get("MEDIA_DIR", "/data/media")
