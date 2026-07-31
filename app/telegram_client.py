import httpx

from app.config import TELEGRAM_API


async def send_message(chat_id: int, text: str):
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )


async def send_document_by_url(chat_id: int, file_url: str, caption: str = ""):
    """Envia un archivo (la cancion) mandando su URL publica - Telegram lo descarga solo."""
    async with httpx.AsyncClient(timeout=60) as client:
        await client.post(
            f"{TELEGRAM_API}/sendDocument",
            json={"chat_id": chat_id, "document": file_url, "caption": caption},
        )


async def set_webhook(base_url: str, secret_token: str):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{TELEGRAM_API}/setWebhook",
            json={
                "url": f"{base_url}/telegram/webhook",
                "secret_token": secret_token,
            },
        )
        return resp.json()
