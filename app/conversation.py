"""
Flujo del bot:

1. /start -> se explica el proceso y se manda el link de pago (dLocal Go:
   tarjeta, OXXO o transferencia). Esto es deterministico, no pasa por Claude.
2. Mientras espera el pago, el cliente puede preguntarle lo que quiera a
   Claude (como pagar, si ya se confirmo, pedir un link nuevo, etc.) - Claude
   tiene herramientas para consultar el estado real y generar un link nuevo.
   Ademas, un chequeo automatico en segundo plano (ver main.py) confirma el
   pago solo apenas dLocal Go lo reporta, sin que el cliente ni vos tengan
   que hacer nada.
3. Una vez pagado, Claude pregunta por los detalles de la cancion, arma un
   borrador, lo ajusta segun lo que pida el cliente.
4. Cuando el cliente aprueba explicitamente, Claude llama a la herramienta
   finalizar_letra - eso dispara la generacion en Suno. El loop de polling
   en main.py entrega la cancion cuando esta lista.

Estados posibles (columna "step" en la tabla orders):
    creando_pago -> esperando_pago -> charlando -> generando -> entregado

Vos (admin) solo te enteras si algo sale realmente mal (pago rechazado,
fallo tecnico) - no hace falta que intervengas en el camino feliz.
"""
import logging
import time

from app import db
from app.config import ADMIN_CHAT_ID, PRECIO_MXN, PRECIO_TEXTO, BASE_URL
from app.dlocal_client import create_payment, get_payment
from app.claude_client import (
    send_chat,
    PAYMENT_SYSTEM_PROMPT,
    PAYMENT_TOOLS,
    CONTENT_SYSTEM_PROMPT,
    CONTENT_TOOLS,
)
from app.suno_client import generate_custom_song
from app.telegram_client import send_message

log = logging.getLogger("cancion-bot")

INTRO_TEXT = (
    "¡Hola! Así vamos a trabajar tu canción personalizada 🎵\n\n"
    "1️⃣ Te paso un link para hacer tu pago (con tarjeta, en OXXO, o por transferencia). "
    "Yo confirmo que llegó y seguimos.\n"
    "2️⃣ Te hago algunas preguntas sobre la canción: para quién es, el estilo, detalles especiales, etc.\n"
    "3️⃣ Te muestro un borrador de la letra. Si quieres algún cambio, lo ajustamos juntos.\n"
    "4️⃣ Esperas un par de minutos mientras la genero, y te la entrego con un link de descarga.\n\n"
    "¡Empecemos! Generando tu link de pago..."
)

MAX_TOOL_ROUNDS = 4  # limite de seguridad para evitar loops infinitos de herramientas


async def handle_message(chat_id: int, text: str):
    # --- Comando de respaldo del admin (vos), solo para casos imprevistos ---
    if chat_id == ADMIN_CHAT_ID and text.strip().lower().startswith("/reintentar"):
        partes = text.strip().split()
        if len(partes) != 2:
            await send_message(chat_id, "Uso: /reintentar <chat_id_del_cliente>")
            return
        await reintentar_generacion(int(partes[1]))
        return

    if chat_id == ADMIN_CHAT_ID and text.strip().lower().startswith("/reiniciar_chat"):
        partes = text.strip().split()
        if len(partes) != 2:
            await send_message(chat_id, "Uso: /reiniciar_chat <chat_id_del_cliente>")
            return
        target_chat_id = int(partes[1])
        db.set_messages(target_chat_id, [])
        await send_message(
            chat_id,
            f"Historial de conversación borrado para chat_id {target_chat_id} "
            "(el pedido y el pago se mantienen). Pídele al cliente que escriba "
            "algo para retomar la charla desde cero.",
        )
        return

    order = db.get_order(chat_id)

    # --- /start: explica el proceso y genera el link de pago ---
    if text.strip().lower() in ("/start", "/inicio") or order is None:
        db.create_order(chat_id)
        db.update_order(chat_id, step="creando_pago")
        await send_message(chat_id, INTRO_TEXT)
        await generar_link_pago(chat_id, avisar_admin=True)
        return

    current_step = order["step"]

    if current_step in ("creando_pago", "esperando_pago", "pago_fallido"):
        await continuar_charla_pago(chat_id, text)
        return

    if current_step == "generando":
        await send_message(
            chat_id,
            "Tu canción se está generando, dame un par de minutos más y te la comparto 🎧",
        )
        return

    if current_step == "entregado":
        await send_message(
            chat_id, "Ya te entregué tu canción. Si quieres pedir otra, escribe /start.",
        )
        return

    if current_step == "charlando":
        await continuar_charla_cancion(chat_id, text)
        return


async def generar_link_pago(chat_id: int, avisar_admin: bool = False) -> str | None:
    """Crea un pago nuevo en dLocal Go y le manda el link al cliente.
    Devuelve el redirect_url, o None si fallo (y ahi si le avisamos al admin,
    porque eso es lo imprevisto)."""
    # order_id tiene que ser unico por cada intento de pago - dLocal Go
    # rechaza (400) si se reutiliza uno ya usado antes, por eso le agregamos
    # un timestamp (por si el cliente pide un link nuevo tras uno fallido).
    order_id = f"{chat_id}-{int(time.time())}"
    try:
        payment = await create_payment(
            amount=PRECIO_MXN,
            currency="MXN",
            country="MX",
            order_id=order_id,
            description="Canción personalizada",
            notification_url=f"{BASE_URL}/dlocal/webhook",
            success_url=f"{BASE_URL}/pago-exitoso",
        )
    except Exception:
        log.exception("Error creando el pago en dLocal Go para chat_id=%s", chat_id)
        await send_message(
            chat_id,
            "Tuvimos un problema generando tu link de pago. Ya lo estamos revisando.",
        )
        await send_message(ADMIN_CHAT_ID, f"⚠️ Falló la creación del pago para chat_id {chat_id}.")
        return None

    db.update_order(
        chat_id,
        step="esperando_pago",
        payment_url=payment["redirect_url"],
        payment_request_id=payment["id"],
    )
    await send_message(
        chat_id,
        f"Tu link de pago ({PRECIO_TEXTO}):\n{payment['redirect_url']}\n\n"
        "En cuanto se confirme el pago, seguimos con el paso 2 🎶",
    )
    if avisar_admin:
        await send_message(ADMIN_CHAT_ID, f"📝 Nuevo pedido de chat_id {chat_id}. Esperando pago.")
    return payment["redirect_url"]


async def continuar_charla_pago(chat_id: int, text: str):
    """Etapa 1: el cliente pregunta cosas mientras espera que se confirme el
    pago. Claude puede consultar el estado real o generar un link nuevo."""

    async def ejecutar_herramienta(name: str, tool_input: dict) -> str:
        if name == "revisar_estado_pago":
            order = db.get_order(chat_id)
            if not order.get("payment_request_id"):
                return "Todavía no se generó ningún link de pago para este pedido."
            try:
                payment = await get_payment(order["payment_request_id"])
            except Exception:
                log.exception("Error consultando estado de pago para chat_id=%s", chat_id)
                return "No se pudo consultar el estado del pago en este momento."

            status = payment.get("status")
            if status == "PAID":
                # Puede que el webhook todavia no haya llegado - lo confirmamos
                # ya mismo nosotros mismos.
                order_fresh = db.get_order(chat_id)
                if not order_fresh["paid"]:
                    from app.payment_confirm import confirmar_pago
                    await confirmar_pago(chat_id)
                return "El pago ya fue confirmado. Avisale al cliente con entusiasmo y continua."
            if status in ("REJECTED", "CANCELLED", "EXPIRED"):
                await send_message(
                    ADMIN_CHAT_ID,
                    f"⚠️ El pago de chat_id {chat_id} quedó en estado {status}.",
                )
            return f"Estado actual del pago: {status}"

        if name == "generar_nuevo_link_pago":
            url = await generar_link_pago(chat_id, avisar_admin=False)
            if url:
                return f"Nuevo link de pago generado: {url}"
            return "Hubo un problema generando un nuevo link. Decile al cliente que ya lo estamos revisando."

        return "Herramienta desconocida."

    await ejecutar_turno_claude(
        chat_id,
        text,
        system=PAYMENT_SYSTEM_PROMPT,
        tools=PAYMENT_TOOLS,
        ejecutar_herramienta=ejecutar_herramienta,
    )


async def continuar_charla_cancion(chat_id: int, text: str):
    """Etapa 2: ya pagado - Claude arma la letra con el cliente."""

    async def ejecutar_herramienta(name: str, tool_input: dict) -> str:
        if name != "finalizar_letra":
            return "Herramienta desconocida."

        db.save_final_letra(
            chat_id,
            tool_input.get("title", ""),
            tool_input.get("style", ""),
            tool_input.get("lyric", ""),
        )
        db.update_order(chat_id, step="generando")

        try:
            result = await generate_custom_song(
                lyric=tool_input["lyric"], title=tool_input["title"], style=tool_input["style"]
            )
            task_id = result.get("task_id") or result.get("id")
            db.update_order(chat_id, suno_task_id=task_id)
            return "La canción se está generando correctamente."
        except Exception:
            log.exception("Error generando la cancion en Suno para chat_id=%s", chat_id)
            db.update_order(chat_id, step="charlando")
            await send_message(
                ADMIN_CHAT_ID,
                f"⚠️ Falló Suno para chat_id {chat_id}. Usa /reintentar {chat_id} cuando lo revises.",
            )
            return (
                "Hubo un problema tecnico generando la cancion. Decile al cliente que ya lo "
                "estamos revisando y que le avisamos apenas se resuelva."
            )

    await ejecutar_turno_claude(
        chat_id,
        text,
        system=CONTENT_SYSTEM_PROMPT,
        tools=CONTENT_TOOLS,
        ejecutar_herramienta=ejecutar_herramienta,
    )


async def ejecutar_turno_claude(chat_id: int, text: str, system: str, tools: list, ejecutar_herramienta):
    """Loop generico: manda el mensaje a Claude, muestra el texto que
    responda, y si pide usar alguna herramienta, la ejecuta y le devuelve el
    resultado para que pueda seguir (hasta MAX_TOOL_ROUNDS rondas, por
    seguridad)."""
    log.info("[chat_id=%s] USUARIO: %s", chat_id, text)

    messages = db.get_messages(chat_id)
    messages.append({"role": "user", "content": text})

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = await send_chat(messages, system=system, tools=tools)
        except Exception:
            log.exception("Error hablando con Claude para chat_id=%s", chat_id)
            await send_message(
                chat_id, "Tuve un problema procesando tu mensaje, ¿me lo puedes repetir?"
            )
            return

        assistant_content = response["content"]
        messages.append({"role": "assistant", "content": assistant_content})

        for block in assistant_content:
            if block.get("type") == "text" and block.get("text"):
                log.info("[chat_id=%s] CLAUDE (texto): %s", chat_id, block["text"])
                await send_message(chat_id, block["text"])
            elif block.get("type") == "tool_use":
                log.info(
                    "[chat_id=%s] CLAUDE llamo la herramienta '%s' con input=%s",
                    chat_id, block.get("name"), block.get("input"),
                )

        tool_use_blocks = [b for b in assistant_content if b.get("type") == "tool_use"]

        if not tool_use_blocks:
            db.set_messages(chat_id, messages)
            return

        tool_results = []
        for block in tool_use_blocks:
            result_text = await ejecutar_herramienta(block["name"], block.get("input", {}))
            log.info(
                "[chat_id=%s] Resultado de la herramienta '%s': %s",
                chat_id, block["name"], result_text,
            )
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block["id"], "content": result_text}
            )
        messages.append({"role": "user", "content": tool_results})
        db.set_messages(chat_id, messages)
        # sigue el loop para que Claude vea el resultado y responda

    log.warning("Se alcanzo el limite de rondas de herramientas para chat_id=%s", chat_id)


async def reintentar_generacion(chat_id: int):
    """Respaldo manual: reintenta la generacion en Suno usando la ultima
    letra/titulo/estilo ya aprobados, sin volver a chatear con el cliente."""
    order = db.get_order(chat_id)
    if not order or not order.get("final_lyric"):
        await send_message(
            ADMIN_CHAT_ID, f"No hay una letra final guardada todavía para chat_id {chat_id}."
        )
        return

    db.update_order(chat_id, step="generando")
    await send_message(chat_id, "Reintentando la generación de tu canción 🎧")

    try:
        result = await generate_custom_song(
            lyric=order["final_lyric"], title=order["final_title"], style=order["final_style"]
        )
        task_id = result.get("task_id") or result.get("id")
        db.update_order(chat_id, suno_task_id=task_id)
    except Exception:
        log.exception("Error reintentando Suno para chat_id=%s", chat_id)
        db.update_order(chat_id, step="charlando")
        await send_message(ADMIN_CHAT_ID, f"⚠️ Volvió a fallar Suno para chat_id {chat_id}.")
