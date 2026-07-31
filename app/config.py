import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
ACEDATACLOUD_API_TOKEN = os.environ["ACEDATACLOUD_API_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
BASE_URL = os.environ["BASE_URL"].rstrip("/")
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

# Tu chat_id de Telegram (el del administrador). Se usa para el comando
# /confirmar de respaldo (por si el webhook de dLocal Go fallara) y para que
# te avisen de pedidos nuevos. Lo obtienes hablandole a @userinfobot en Telegram.
ADMIN_CHAT_ID = int(os.environ["ADMIN_CHAT_ID"])

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
