"""
Envio del correo de entrega para los pedidos que vienen de la landing web
(/cancion). Usa Gmail por SMTP con una "contraseña de aplicacion" (no la
contraseña normal de la cuenta - Gmail la rechaza para SMTP de terceros).

Se manda como respaldo/comprobante - el link de descarga YA aparece directo
en el chat de la landing en cuanto la cancion esta lista (ver /web/status en
main.py); el correo es para quien cierra la pestaña o quiere guardarlo.

smtplib es sincronico (bloqueante) - lo corremos en un hilo aparte
(asyncio.to_thread) para no trabar el event loop de FastAPI mientras se
manda.
"""
import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import GMAIL_USER, GMAIL_APP_PASSWORD

log = logging.getLogger("cancion-bot")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def _enviar_sync(destinatario: str, asunto: str, cuerpo_html: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = GMAIL_USER
    msg["To"] = destinatario
    msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, [destinatario], msg.as_string())


async def enviar_cancion_por_correo(destinatario: str, titulo: str, audio_urls: list[str]) -> bool:
    """Devuelve True si se mando (o si no hay credenciales configuradas, para
    no bloquear el flujo), False si hubo un error real intentando mandarlo."""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        log.warning(
            "GMAIL_USER/GMAIL_APP_PASSWORD no configurados - se omite el correo de "
            "entrega para %s (el link ya quedo disponible en el chat web).",
            destinatario,
        )
        return False

    enlaces_html = "".join(
        f'<p><a href="{url}" style="color:#c2410c; font-weight:bold;">'
        f"Descargar {('versión ' + str(i + 1)) if len(audio_urls) > 1 else 'canción'}</a></p>"
        for i, url in enumerate(audio_urls)
    )
    cuerpo_html = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
      <h2>🎵 ¡Tu canción "{titulo}" está lista!</h2>
      <p>Aquí tienes el link (o links, si generamos más de una versión) para descargarla:</p>
      {enlaces_html}
      <p style="color:#6b7280; font-size:13px;">Gracias por confiar en nosotros para este regalo.</p>
    </div>
    """

    try:
        await asyncio.to_thread(
            _enviar_sync, destinatario, f"🎵 Tu canción personalizada: {titulo}", cuerpo_html
        )
        return True
    except Exception:
        log.exception("Error mandando el correo de entrega a %s", destinatario)
        return False
