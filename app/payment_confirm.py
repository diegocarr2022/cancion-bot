"""
Se dispara cuando VOS confirmas manualmente un pago (comando /confirmar en
Telegram). A partir de aca todo sigue solo: Claude redacta la letra, Suno
genera la cancion, y el loop de polling en main.py la entrega cuando este
lista.
"""
import logging

from app import db
from app.claude_client import draft_song
from app.suno_client import generate_custom_song
from app.telegram_client import send_message

log = logging.getLogger("cancion-bot")


async def confirmar_pago(chat_id: int):
    order = db.get_order(chat_id)
    if not order:
        await send_message(chat_id, f"No encontré ningún pedido para chat_id {chat_id}.")
        return

    if order["paid"]:
        await send_message(chat_id, f"El pedido de chat_id {chat_id} ya estaba confirmado.")
        return

    data = db.get_data(chat_id)
    await send_message(chat_id, "¡Pago confirmado!")
    await send_message(
        chat_id,
        "¡Pago confirmado! Estamos componiendo tu canción, te avisamos en cuanto esté lista 🎼",
    )

    try:
        song = await draft_song(data)  # {title, style, lyric} generado por Claude
        result = await generate_custom_song(
            lyric=song["lyric"], title=song["title"], style=song["style"]
        )
        task_id = result.get("task_id") or result.get("id")
        db.update_order(chat_id, paid=1, suno_task_id=task_id)
        await send_message(chat_id, "Tu canción se está generando, esto puede tardar unos minutos.")
    except Exception:
        log.exception("Error generando la cancion para chat_id=%s", chat_id)
        await send_message(
            chat_id,
            "Tuvimos un problema generando tu canción. Ya lo estamos revisando, te contactamos pronto.",
        )
