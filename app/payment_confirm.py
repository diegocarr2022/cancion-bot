"""
Se dispara cuando el pago de un pedido queda confirmado - esto puede pasar
por tres caminos distintos, todos automaticos:
1. El webhook de dLocal Go avisa que el pago se completo.
2. El chequeo periodico en segundo plano (main.py) detecta que ya esta pagado.
3. El propio cliente le pregunta a Claude si ya se confirmo, y Claude
   consulta el estado real (herramienta revisar_estado_pago) y lo detecta.

A partir de aca arranca la charla con Claude (paso 2 y 3 del proceso): el
mismo Claude pregunta por los detalles, arma un borrador, ajusta, y cuando
el cliente aprueba, dispara la generacion en Suno (eso ultimo lo maneja
app/conversation.py cuando Claude llama a la herramienta finalizar_letra).
"""
import logging

from app import db
from app.claude_client import send_chat, CONTENT_SYSTEM_PROMPT, CONTENT_TOOLS
from app.config import ADMIN_CHAT_ID
from app.suno_client import generate_custom_song
from app.telegram_client import send_message

log = logging.getLogger("cancion-bot")

KICKOFF_INSTRUCTION = (
    "(El cliente ya realizo el pago. Saludalo calidamente confirmando que "
    "recibiste el pago, y empeza a preguntarle sobre la cancion: para quien "
    "es, la relacion, la ocasion, el estilo musical que prefiere, y algun "
    "detalle o anecdota especial.)"
)


async def confirmar_pago(chat_id: int):
    order = db.get_order(chat_id)
    if not order:
        await send_message(chat_id, f"No encontré ningún pedido para chat_id {chat_id}.")
        return

    if order["paid"]:
        await send_message(chat_id, f"El pedido de chat_id {chat_id} ya estaba confirmado.")
        return

    db.update_order(chat_id, paid=1, step="charlando")

    messages = [{"role": "user", "content": KICKOFF_INSTRUCTION}]
    try:
        response = await send_chat(messages, system=CONTENT_SYSTEM_PROMPT, tools=CONTENT_TOOLS)
        assistant_content = response["content"]
        messages.append({"role": "assistant", "content": assistant_content})

        for block in assistant_content:
            if block.get("type") == "text" and block.get("text"):
                await send_message(chat_id, block["text"])

        db.set_messages(chat_id, messages)
    except Exception:
        log.exception("Error iniciando la charla con Claude para chat_id=%s", chat_id)
        await send_message(
            chat_id,
            "¡Pago confirmado! Cuéntame, ¿para quién es la canción y qué la hace especial?",
        )
        db.set_messages(chat_id, messages)


async def confirmar_pago_web(session_id: str):
    """Version web de confirmar_pago: a diferencia de Telegram, la letra ya
    quedo definida y aprobada ANTES del pago (ver web_conversation.py), asi
    que aca no hace falta volver a hablar con Claude - se manda derecho a
    generar la cancion en Suno con lo que ya se guardo."""
    order = db.get_web_order(session_id)
    if not order or order["paid"]:
        return

    db.update_web_order(session_id, paid=1, step="generando")

    try:
        result = await generate_custom_song(
            lyric=order["final_lyric"], title=order["final_title"], style=order["final_style"]
        )
        task_id = result.get("task_id") or result.get("id")
        db.update_web_order(session_id, suno_task_id=task_id)
    except Exception:
        log.exception("Error generando la cancion en Suno para session_id=%s (web)", session_id)
        db.update_web_order(session_id, step="charlando")
        await send_message(
            ADMIN_CHAT_ID,
            f"⚠️ Falló Suno para el pedido web session_id={session_id} justo tras el pago.",
        )
