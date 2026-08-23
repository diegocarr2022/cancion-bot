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
from app.claude_client import (
    send_chat,
    build_web_content_system_prompt,
    WEB_CONTENT_TOOLS,
    WEB_CONTENT_TOOLS_EN,
)
from app.config import BASE_URL, get_precio_pais
from app.dlocal_client import create_payment
from app.paypal_client import create_order as create_paypal_order

log = logging.getLogger("cancion-bot")

MAX_TOOL_ROUNDS = 4

KICKOFF_TEXT = (
    "(Este es el arranque de una sesion nueva - el cliente todavia no escribio "
    "nada. Saludalo con calidez y en ESE MISMO primer mensaje pregúntale su "
    "nombre - nada mas por ahora, no le sumes las preguntas de la cancion "
    "todavia, esas van en tu siguiente mensaje una vez que te diga como se llama.)"
)

KICKOFF_TEXT_EN = (
    "(This is the start of a new session - the customer hasn't written "
    "anything yet. Greet them warmly and in that SAME first message ask "
    "for their name - nothing else for now, don't add the song questions "
    "yet, those go in your next message once they tell you their name.)"
)


async def crear_link_pago(session_id: str, order: dict, precio: dict) -> dict:
    """Crea (o re-crea) el link de pago de un pedido web con letra ya
    aprobada. Separado de _finalizar_letra para poder reutilizarlo desde
    _buscar_pedido_por_correo: si se recupera un pedido sin pagar, el link
    viejo puede haber expirado o el pago haber sido rechazado, asi que ahi
    se genera uno FRESCO en vez de devolver el que ya podria estar muerto."""
    order_id = f"web-{session_id}-{int(time.time())}"
    # EE.UU. paga via PayPal (dLocal Go no puede cobrarle a alguien
    # fisicamente en EE.UU. - ver app/paypal_client.py); el resto de paises
    # sigue con dLocal Go, sin cambios. Ambas ramas dejan `payment` con el
    # mismo shape {"redirect_url", "id"}.
    es_estados_unidos = (order.get("country") or "MX") == "US"
    descripcion = "Personalized song" if es_estados_unidos else "Canción personalizada"
    if order.get("tier") == "song_video":
        descripcion += " + video"

    if es_estados_unidos:
        payment = await create_paypal_order(
            amount=precio["amount"],
            currency=precio["currency"],
            order_id=order_id,
            description=descripcion,
            return_url=f"{BASE_URL}/pago-exitoso/web/{session_id}",
            cancel_url=f"{BASE_URL}/?session_id={session_id}",
        )
        gateway = "paypal"
    else:
        payment = await create_payment(
            amount=precio["amount"],
            currency=precio["currency"],
            country=(order.get("country") or "MX"),
            order_id=order_id,
            description=descripcion,
            notification_url=f"{BASE_URL}/dlocal/webhook",
            # session_id va en el PATH, no en query string: algunos gateways
            # de pago (dLocal Go incluido) no garantizan que preserven query
            # params custom al armar la redireccion final - un segmento de
            # path es mucho mas dificil de perder o pisar que un
            # "?param=valor".
            success_url=f"{BASE_URL}/pago-exitoso/web/{session_id}",
        )
        gateway = "dlocal"

    db.update_web_order(
        session_id,
        step="esperando_pago",
        payment_url=payment["redirect_url"],
        payment_request_id=payment["id"],
        amount_mxn=precio["amount"],
        gateway=gateway,
    )
    return payment


async def _finalizar_letra(session_id: str, order: dict, precio: dict, tool_input: dict, resultado: dict) -> str:
    title = tool_input.get("title", "")
    style = tool_input.get("style", "")
    lyric = tool_input.get("lyric", "")
    email = (tool_input.get("email") or "").strip()
    customer_name = (tool_input.get("customer_name") or "").strip()
    # solo lo llena el tool schema en ingles (WEB_CONTENT_TOOLS_EN) - el de
    # ES no tiene este campo, asi que aca siempre da None y no cambia nada
    # del flujo en espanol.
    vocal_gender = tool_input.get("vocal_gender")
    if vocal_gender not in ("f", "m"):
        vocal_gender = None
    # misma red de seguridad que en Telegram: separar estilo pegado al
    # inicio de la letra si Claude lo mezclo por error.
    idx = lyric.find("[")
    if idx > 0:
        prefijo = lyric[:idx].strip(" \n:-")
        if prefijo:
            lyric = lyric[idx:].lstrip()
            style = f"{style} {prefijo}".strip() if style else prefijo

    db.save_web_final_letra(session_id, title, style, lyric, gender=vocal_gender)
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

    try:
        payment = await crear_link_pago(session_id, order, precio)
    except Exception:
        log.exception(
            "Error creando el pago web para session_id=%s", session_id,
        )
        return (
            "Hubo un problema tecnico generando el link de pago. Decile al cliente "
            "que ya lo estamos revisando y que intente de nuevo en un momento."
        )

    resultado["listo_para_pagar"] = True
    resultado["payment_url"] = payment["redirect_url"]
    return (
        "Se genero el link de pago correctamente. Ya se le va a mostrar el boton de "
        "pago en la pantalla - en tu mensaje de texto avisale con calidez que la letra "
        "quedo lista y que puede pagar cuando quiera para arrancar la generacion."
    )


async def _buscar_pedido_por_correo(tool_input: dict, order: dict, resultado: dict) -> str:
    email = (tool_input.get("email") or "").strip()
    if not email or "@" not in email:
        return "El cliente no dio un correo valido. Pedile que te lo repita bien."

    encontrado = db.find_recent_web_order_by_email(email, language=order.get("language"))
    if not encontrado:
        return (
            "No se encontro ningun pedido con ese correo. Decile al cliente que revise "
            "que este bien escrito, o si prefiere, seguimos armando una cancion nueva."
        )

    found_session_id = encontrado["session_id"]
    nombre = encontrado.get("customer_name") or "el cliente"
    titulo = encontrado.get("final_title") or "su canción"

    if encontrado.get("delivered"):
        resultado["redirect_session_id"] = found_session_id
        return (
            f"Se encontro el pedido de {nombre} ('{titulo}'), YA ENTREGADO. Decile "
            "calidamente que ya encontraste su pedido y que en un segundo lo vas a "
            "llevar de vuelta a la pantalla con su cancion lista para descargar."
        )

    if encontrado.get("paid"):
        resultado["redirect_session_id"] = found_session_id
        return (
            f"Se encontro el pedido de {nombre} ('{titulo}'), YA PAGADO y en "
            "generacion. Decile que ya encontraste su pedido, que el pago quedo "
            "confirmado, y que en un segundo lo vas a llevar de vuelta a la pantalla "
            "donde va a ver el progreso (tambien le llega por correo cuando este lista)."
        )

    if encontrado.get("final_lyric"):
        # Letra ya aprobada pero sin pago confirmado - el link viejo puede
        # haber expirado o el pago haber sido rechazado. Se genera uno
        # fresco antes de mandarlo de vuelta, para no devolverle un link
        # que ya no sirve.
        precio_encontrado = get_precio_pais(encontrado.get("country"), encontrado.get("tier", "song"))
        try:
            await crear_link_pago(found_session_id, encontrado, precio_encontrado)
        except Exception:
            log.exception(
                "Error regenerando link de pago en recuperacion para session_id=%s",
                found_session_id,
            )
            return (
                "Se encontro el pedido pero hubo un problema tecnico generando un "
                "nuevo link de pago. Decile al cliente que ya lo estamos revisando y "
                "que intente de nuevo en unos minutos."
            )
        resultado["redirect_session_id"] = found_session_id
        return (
            f"Se encontro el pedido de {nombre} con la letra ya aprobada ('{titulo}') "
            "pero sin pago confirmado (puede haber sido rechazado o el link haber "
            "expirado) - se genero un link de pago NUEVO. Decile que ya encontraste "
            "su pedido con la letra que ya habian armado juntos, y que en un segundo "
            "lo vas a llevar de vuelta para que pueda pagar con el nuevo link."
        )

    # Se encontro un pedido, pero nunca se llego a aprobar una letra (se
    # quedo a mitad de la charla) - no hay nada util que retomar de ahi.
    return (
        "Se encontro un pedido anterior con ese correo, pero nunca se llego a "
        "aprobar una letra (se quedo a mitad de la charla). No hay nada que "
        "recuperar de ahi - decile al cliente con calidez que mejor arranquen de "
        "nuevo, y segui la charla normal para armar su cancion desde cero en este "
        "mismo chat."
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

    precio = get_precio_pais(order.get("country"), order.get("tier", "song"))
    language = order.get("language", "es")

    if order["step"] != "charlando":
        # Ya paso de la etapa de charla (esta esperando pago, generando, o
        # entregado) - no hay mas turnos de Claude que procesar aca. El
        # frontend deberia estar usando /web/status para el resto.
        return {"mensajes": [], "listo_para_pagar": False, "payment_url": order.get("payment_url")}

    resultado = {
        "mensajes": [], "listo_para_pagar": False, "payment_url": None,
        # Si buscar_pedido_por_correo/find_previous_order encuentra un
        # pedido real, el frontend redirige a esta sesion en vez de seguir
        # en la nueva - ver retomarSesion() en landing.py.
        "redirect_session_id": None,
    }

    async def ejecutar_herramienta(name: str, tool_input: dict) -> str:
        if name == "finalizar_letra":
            return await _finalizar_letra(session_id, order, precio, tool_input, resultado)
        if name in ("buscar_pedido_por_correo", "find_previous_order"):
            return await _buscar_pedido_por_correo(tool_input, order, resultado)
        return "Herramienta desconocida."

    messages = db.get_web_messages(session_id)
    if not messages:
        # primer turno de esta sesion: arrancamos con el saludo/kickoff en
        # vez de esperar a que el cliente escriba primero.
        messages.append({"role": "user", "content": KICKOFF_TEXT_EN if language == "en" else KICKOFF_TEXT})
    else:
        messages.append({"role": "user", "content": text})

    system_prompt = build_web_content_system_prompt(precio["texto"], language=language)
    tools = WEB_CONTENT_TOOLS_EN if language == "en" else WEB_CONTENT_TOOLS

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = await send_chat(messages, system=system_prompt, tools=tools)
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
