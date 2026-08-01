"""
Maquina de estados simple para el pedido via chat de Telegram.

Cada paso guarda la respuesta anterior y manda la siguiente pregunta.
Cuando se completan todos los pasos, se crea un pago EN dLocal Go especifico
para ese pedido (no un link fijo) - eso permite que el webhook de dLocal Go
nos diga exactamente que pedido se pago, y todo siga solo, sin que vos
tengas que confirmar nada a mano.

El comando /confirmar sigue existiendo como respaldo manual por si el
webhook fallara o se demorara.
"""
import logging

from app import db
from app.config import ADMIN_CHAT_ID, PRECIO_MXN, PRECIO_TEXTO, BASE_URL
from app.dlocal_client import create_payment
from app.telegram_client import send_message

log = logging.getLogger("cancion-bot")

STEPS = [
    ("nombre", "¿Para quién es la canción? (nombre completo)"),
    ("relacion", "¿Cuál es tu relación con esa persona? (ej. hijo, pareja, papá, amigo)"),
    ("ocasion", "¿Qué ocasión están celebrando? (cumpleaños, aniversario, etc.)"),
    ("detalles", "Cuéntame 2-3 detalles o anécdotas especiales de esta persona (gustos, "
                 "historias, frases que dice, lo que la hace única)"),
    ("genero", "¿Qué género musical prefieres? (ej. balada, bossa nova, pop, corrido, mariachi)"),
    ("voz", "¿Voz masculina o femenina?"),
    ("restricciones", "¿Hay algo que NO quieras que mencione la canción? (si no hay nada, escribe 'ninguna')"),
]
FIELDS_IN_ORDER = [s[0] for s in STEPS]


async def handle_message(chat_id: int, text: str):
    # Comando de respaldo del admin (vos) para confirmar pagos a mano
    if chat_id == ADMIN_CHAT_ID and text.strip().lower().startswith("/confirmar"):
        from app.payment_confirm import confirmar_pago

        partes = text.strip().split()
        if len(partes) != 2:
            await send_message(chat_id, "Uso: /confirmar <chat_id_del_cliente>")
            return
        await confirmar_pago(int(partes[1]))
        return

    order = db.get_order(chat_id)

    if text.strip().lower() in ("/start", "/inicio") or order is None:
        db.create_order(chat_id)
        db.update_order(chat_id, step=FIELDS_IN_ORDER[0])
        await send_message(
            chat_id,
            "¡Hola! Vamos a crear tu canción personalizada 🎵\n\n" + STEPS[0][1],
        )
        return

    current_step = order["step"]

    if current_step == "esperando_pago":
        await send_message(
            chat_id,
            "Todavía estoy esperando la confirmación de tu pago. En cuanto se "
            "acredite, seguimos automáticamente 🎶",
        )
        return

    if current_step == "generando_pago":
        # Ya se disparo la creacion del pago para este pedido - no hacemos
        # nada mas, para evitar crear un pago duplicado si Telegram reenvia
        # el mismo mensaje.
        return

    if current_step == "hecho":
        await send_message(chat_id, "Ya tenés un pedido en curso. Si querés empezar uno nuevo, escribe /start.")
        return

    # Guarda la respuesta del paso actual
    db.set_data_field(chat_id, current_step, text.strip())

    current_index = FIELDS_IN_ORDER.index(current_step)
    next_index = current_index + 1

    if next_index < len(FIELDS_IN_ORDER):
        next_field = FIELDS_IN_ORDER[next_index]
        question = STEPS[next_index][1]
        db.update_order(chat_id, step=next_field)
        await send_message(chat_id, question)
    else:
        # Marcamos el pedido como "en proceso" ANTES de llamar a dLocal Go,
        # asi si este mismo mensaje llega duplicado mientras la llamada esta
        # en curso, el chequeo de arriba ("generando_pago") lo frena.
        db.update_order(chat_id, step="generando_pago")

        data = db.get_data(chat_id)
        resumen = "\n".join(f"- {k}: {v}" for k, v in data.items())

        await send_message(chat_id, "Perfecto, generando tu link de pago...")

        try:
            payment = await create_payment(
                amount=PRECIO_MXN,
                currency="MXN",
                country="MX",
                order_id=str(chat_id),
                description=f"Canción personalizada para {data.get('nombre', 'cliente')}",
                notification_url=f"{BASE_URL}/dlocal/webhook",
                success_url=f"{BASE_URL}/pago-exitoso",
            )
        except Exception:
            log.exception("Error creando el pago en dLocal Go para chat_id=%s", chat_id)
            db.update_order(chat_id, step="restricciones")  # permite reintentar
            await send_message(
                chat_id,
                "Tuvimos un problema generando tu link de pago. Ya lo estamos "
                "revisando, en un momento te contactamos.",
            )
            await send_message(
                ADMIN_CHAT_ID,
                f"⚠️ Falló la creación del pago para chat_id {chat_id}. Revisa los logs de Render.",
            )
            return

        db.update_order(
            chat_id,
            step="esperando_pago",
            payment_url=payment["redirect_url"],
            payment_request_id=payment["id"],
        )

        await send_message(
            chat_id,
            f"Resumen de tu pedido:\n{resumen}\n\n"
            f"Para generar tu canción, completa tu pago de {PRECIO_TEXTO} aquí:\n"
            f"{payment['redirect_url']}\n\n"
            "En cuanto se confirme el pago, empezamos a componer tu canción "
            "automáticamente y te la mandamos por aquí en cuanto esté lista 🎶",
        )
        await send_message(
            ADMIN_CHAT_ID,
            f"📝 Nuevo pedido de chat_id {chat_id}:\n{resumen}\n\nEsperando pago.",
        )
