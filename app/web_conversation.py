"""
Flujo de la landing web (/cancion), en paralelo al de Telegram
(app/conversation.py). La diferencia clave de orden: aca se charla con
Claude ANTES de pagar (el cliente ya dejo su correo al entrar), y recien
cuando aprueba la letra se le muestra el boton de pago - la generacion en
Suno arranca cuando se confirma el pago (ver payment_confirm.confirmar_pago_web),
sin que Claude tenga que volver a hablar despues (el contenido ya quedo
definido antes de pagar).

Estados (columna "step" en web_orders):
    charlando -> esperando_pago -> generando -> entregado
"""
import logging
import time

from app import db
from app.claude_client import send_chat, build_web_content_system_prompt, WEB_CONTENT_TOOLS
from app.config import BASE_URL, get_precio_pais
from app.dlocal_client import create_payment

log = logging.getLogger("cancion-bot")

MAX_TOOL_ROUNDS = 4

KICKOFF_TEXT = (
    "(Este es el arranque de una sesion nueva - el cliente todavia no escribio "
    "nada. Saludalo con calidez y en ESE MISMO primer mensaje pregúntale su "
    "nombre - nada mas por ahora, no le sumes las preguntas de la cancion "
    "todavia, esas van en tu siguiente mensaje una vez que te diga como se llama.)"
)


async def handle_web_chat(session_id: str, text: str) -> dict:
    """Procesa un turno del chat web. Devuelve un dict con:
    - mensajes: lista de textos que Claude respondio en este turno (para
      mostrar en el widget, en orden)
    - listo_para_pagar: True si se acaba de generar el link de pago (el
      frontend debe mostrar el boton)
    - payment_url: el link de pago, si listo_para_pagar es True
    """
    order = db.get_web_order(session_id)
    if not order:
        raise ValueError(f"No existe una sesion web con id {session_id}")

    precio = get_precio_pais(order.get("country"))

    if order["step"] != "charlando":
        # Ya paso de la etapa de charla (esta esperando pago, generando, o
        # entregado) - no hay mas turnos de Claude que procesar aca. El
        # frontend deberia estar usando /web/status para el resto.
        return {"mensajes": [], "listo_para_pagar": False, "payment_url": order.get("payment_url")}

    resultado = {"mensajes": [], "listo_para_pagar": False, "payment_url": None}

    async def ejecutar_herramienta(name: str, tool_input: dict) -> str:
        if name != "finalizar_letra":
            return "Herramienta desconocida."

        title = tool_input.get("title", "")
        style = tool_input.get("style", "")
        lyric = tool_input.get("lyric", "")
        email = (tool_input.get("email") or "").strip()
        customer_name = (tool_input.get("customer_name") or "").strip()
        # misma red de seguridad que en Telegram: separar estilo pegado al
        # inicio de la letra si Claude lo mezclo por error.
        idx = lyric.find("[")
        if idx > 0:
            prefijo = lyric[:idx].strip(" \n:-")
            if prefijo:
                lyric = lyric[idx:].lstrip()
                style = f"{style} {prefijo}".strip() if style else prefijo

        db.save_web_final_letra(session_id, title, style, lyric)
        if email and "@" in email:
            db.update_web_order(session_id, email=email)
        else:
            log.warning(
                "finalizar_letra (web) llamado sin un correo valido para session_id=%s: %r",
                session_id, email,
            )
        if customer_name:
            db.update_web_order(session_id, customer_name=customer_name)
        else:
            log.warning(
                "finalizar_letra (web) llamado sin nombre para session_id=%s", session_id
            )

        order_id = f"web-{session_id}-{int(time.time())}"
        try:
            payment = await create_payment(
                amount=precio["amount"],
                currency=precio["currency"],
                country=(order.get("country") or "MX"),
                order_id=order_id,
                description="Canción personalizada",
                notification_url=f"{BASE_URL}/dlocal/webhook",
                # session_id va en el PATH, no en query string: algunos
                # gateways de pago (dLocal Go incluido) no garantizan que
                # preserven query params custom al armar la redireccion final
                # - un segmento de path es mucho mas dificil de perder o
                # pisar que un "?param=valor".
                success_url=f"{BASE_URL}/pago-exitoso/web/{session_id}",
            )
        except Exception:
            log.exception("Error creando el pago web en dLocal Go para session_id=%s", session_id)
            return (
                "Hubo un problema tecnico generando el link de pago. Decile al cliente "
                "que ya lo estamos revisando y que intente de nuevo en un momento."
            )

        db.update_web_order(
            session_id,
            step="esperando_pago",
            payment_url=payment["redirect_url"],
            payment_request_id=payment["id"],
            amount_mxn=precio["amount"],
        )
        resultado["listo_para_pagar"] = True
        resultado["payment_url"] = payment["redirect_url"]
        return (
            "Se genero el link de pago correctamente. Ya se le va a mostrar el boton de "
            "pago en la pantalla - en tu mensaje de texto avisale con calidez que la letra "
            "quedo lista y que puede pagar cuando quiera para arrancar la generacion."
        )

    messages = db.get_web_messages(session_id)
    if not messages:
        # primer turno de esta sesion: arrancamos con el saludo/kickoff en
        # vez de esperar a que el cliente escriba primero.
        messages.append({"role": "user", "content": KICKOFF_TEXT})
    else:
        messages.append({"role": "user", "content": text})

    system_prompt = build_web_content_system_prompt(precio["texto"])

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = await send_chat(messages, system=system_prompt, tools=WEB_CONTENT_TOOLS)
        except Exception:
            log.exception("Error hablando con Claude para session_id=%s", session_id)
            resultado["mensajes"].append("Tuve un problema procesando tu mensaje, ¿me lo puedes repetir?")
            return resultado

        assistant_content = response["content"]
        messages.append({"role": "assistant", "content": assistant_content})

        for block in assistant_content:
            if block.get("type") == "text" and block.get("text"):
                resultado["mensajes"].append(block["text"])

        tool_use_blocks = [b for b in assistant_content if b.get("type") == "tool_use"]

        if not tool_use_blocks:
            db.set_web_messages(session_id, messages)
            return resultado

        tool_results = []
        for block in tool_use_blocks:
            result_text = await ejecutar_herramienta(block["name"], block.get("input", {}))
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block["id"], "content": result_text}
            )
        messages.append({"role": "user", "content": tool_results})
        db.set_web_messages(session_id, messages)

    log.warning("Se alcanzo el limite de rondas de herramientas para session_id=%s", session_id)
    return resultado
