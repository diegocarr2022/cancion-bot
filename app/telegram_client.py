import httpx

from app.config import TELEGRAM_API


async def send_message(chat_id: int, text: str):
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )


async def send_document_by_url(
    chat_id: int, file_url: str, caption: str = "", title: str = "", performer: str = ""
) -> bool:
    """Envia la cancion como audio (no como documento generico) - asi Telegram
    la muestra con reproductor y boton de descarga bien visibles, en vez de un
    icono de archivo generico que a veces obliga a usar click derecho.

    Devuelve True/False segun si Telegram realmente acepto el archivo - quien
    llama a esta funcion NO debe marcar el pedido como entregado si esto
    devuelve False, para que el loop de polling lo reintente solo en la
    siguiente vuelta (por ejemplo si Telegram rechaza la URL por estar
    todavia incompleta)."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{TELEGRAM_API}/sendAudio",
            json={
                "chat_id": chat_id,
                "audio": file_url,
                "caption": caption,
                "title": title or "Tu canción",
                "performer": performer or "Personalizada para ti",
            },
        )
        data = resp.json()
        if data.get("ok"):
            return True

        # Fallback: si Telegram no puede procesarlo como audio, intentamos
        # igual como documento generico antes de darnos por vencidos.
        resp2 = await client.post(
            f"{TELEGRAM_API}/sendDocument",
            json={"chat_id": chat_id, "document": file_url, "caption": caption},
        )
        data2 = resp2.json()
        return bool(data2.get("ok"))


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
