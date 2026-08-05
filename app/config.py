import os
from dotenv import load_dotenv

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
# Cada pais tiene su propio monto/moneda/texto, configurable por environment
# (por si cambia el tipo de cambio y hay que ajustar) con un default ya
# calculado - todos los precios terminan en el digito "7" a proposito (la
# misma convencion que ya usabamos en Mexico: 197 en vez de 199 - un
# influencer que vende mucho le recomendo a Diego este patron). El pais se
# elige con el parametro ?country=<codigo> en el link del anuncio (ver
# app/landing.py) - sin ese parametro, el default sigue siendo Mexico.
PAISES_SOPORTADOS = {
    "MX": {
        "currency": "MXN",
        "amount": PRECIO_MXN,
        "texto": PRECIO_TEXTO,
    },
    "PE": {
        "currency": "PEN",
        "amount": float(os.environ.get("PRECIO_PEN", "37")),
        "texto": os.environ.get("PRECIO_TEXTO_PEN", "S/ 37"),
    },
    "CO": {
        "currency": "COP",
        "amount": float(os.environ.get("PRECIO_COP", "36727")),
        "texto": os.environ.get("PRECIO_TEXTO_COP", "$36,727 COP"),
    },
}
PAIS_DEFAULT = "MX"


def get_precio_pais(country_code: str | None) -> dict:
    """Devuelve {"currency", "amount", "texto"} para el codigo de pais dado
    (ej. "PE", "CO", "MX"). Si el codigo no es uno de los soportados (o viene
    vacio/mal armado), cae de vuelta a Mexico por seguridad - preferimos
    cobrar en un pais soportado de mas que fallar o cobrar mal."""
    codigo = (country_code or "").strip().upper()
    return PAISES_SOPORTADOS.get(codigo, PAISES_SOPORTADOS[PAIS_DEFAULT])

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

# --- Gmail (envio de la cancion por correo, para los pedidos de la landing web) ---
# GMAIL_USER: la cuenta de Gmail/Workspace desde la que se manda el correo.
# GMAIL_APP_PASSWORD: una "contraseña de aplicacion" generada en la
# configuracion de seguridad de esa cuenta de Google (NO la contraseña
# normal - Gmail no acepta la contraseña normal para SMTP de apps externas).
# Si no se configuran, el envio de correo se salta silenciosamente (se loguea
# una advertencia) - el link de descarga sigue apareciendo en el chat web de
# todas formas, asi que no bloquea la entrega.
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
