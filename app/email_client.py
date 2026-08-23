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

from app.config import GMAIL_USER, GMAIL_APP_PASSWORD, BRAND_NAME_EN

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


async def enviar_cancion_por_correo(
    destinatario: str, titulo: str, audio_urls: list[str], language: str = "es",
    lyrics_pdf_url: str | None = None,
) -> bool:
    """Devuelve True si se mando (o si no hay credenciales configuradas, para
    no bloquear el flujo), False si hubo un error real intentando mandarlo.
    language: "es" (MX/PE/CO) o "en" (EE.UU. - ver expansion ago 2026)."""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        log.warning(
            "GMAIL_USER/GMAIL_APP_PASSWORD no configurados - se omite el correo de "
            "entrega para %s (el link ya quedo disponible en el chat web).",
            destinatario,
        )
        return False

    if language == "en":
        enlaces_html = "".join(
            f'<p><a href="{url}" style="color:#c2410c; font-weight:bold;">'
            f"Download {('version ' + str(i + 1)) if len(audio_urls) > 1 else 'my song'}</a></p>"
            for i, url in enumerate(audio_urls)
        )
        if lyrics_pdf_url:
            enlaces_html += (
                f'<p><a href="{lyrics_pdf_url}" style="color:#c2410c; font-weight:bold;">'
                f"Download the lyrics (PDF)</a></p>"
            )
        cuerpo_html = f"""
        <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
          <h2>🎵 Your song "{titulo}" is ready!</h2>
          <p>Here's the link (or links, if we generated more than one version) to download it:</p>
          {enlaces_html}
          <p style="color:#6b7280; font-size:13px;">Thank you for trusting {BRAND_NAME_EN} with this gift.</p>
        </div>
        """
        asunto = f"🎵 {BRAND_NAME_EN}: your song \"{titulo}\" is ready"
    else:
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
        asunto = f"🎵 Tu canción personalizada: {titulo}"

    try:
        await asyncio.to_thread(_enviar_sync, destinatario, asunto, cuerpo_html)
        return True
    except Exception:
        log.exception("Error mandando el correo de entrega a %s", destinatario)
        return False


async def enviar_recordatorio_resena(destinatario: str, titulo: str, review_url: str) -> bool:
    """Respaldo para cuando el cliente no le dio clic al link de reseña de
    Trustpilot justo en la pantalla de descarga (ver Diego: el pedido
    principal es en el momento de la entrega, esto es solo el recordatorio
    si no reacciono ahi). Solo existe en ingles - Trustpilot es
    especificamente relevante para EE.UU."""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        log.warning(
            "GMAIL_USER/GMAIL_APP_PASSWORD no configurados - se omite el "
            "recordatorio de reseña para %s.", destinatario,
        )
        return False

    cuerpo_html = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
      <h2>💛 How did "{titulo}" turn out?</h2>
      <p>We hope it landed exactly the way you hoped. If you have a minute, a quick review
      means a lot to a brand-new shop like ours - it's how the next person finds us.</p>
      <p><a href="{review_url}" style="color:#c2410c; font-weight:bold;">Leave us a review</a></p>
      <p style="color:#6b7280; font-size:13px;">Thank you for trusting {BRAND_NAME_EN} with this gift.</p>
    </div>
    """
    asunto = f"💛 How did \"{titulo}\" turn out?"

    try:
        await asyncio.to_thread(_enviar_sync, destinatario, asunto, cuerpo_html)
        return True
    except Exception:
        log.exception("Error mandando el recordatorio de reseña a %s", destinatario)
        return False


async def enviar_video_por_correo(destinatario: str, titulo: str, video_url: str, language: str = "es") -> bool:
    """Fase 2 (upsell de video, ver app/video_client.py): correo separado del
    de la cancion porque el video puede terminar bastante despues (el render
    arranca recien cuando el cliente sube las fotos, que puede ser minutos u
    horas despues de que ya se mando el correo del audio)."""
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        log.warning(
            "GMAIL_USER/GMAIL_APP_PASSWORD no configurados - se omite el correo de "
            "video para %s.", destinatario,
        )
        return False

    if language == "en":
        cuerpo_html = f"""
        <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
          <h2>🎬 Your video for "{titulo}" is ready!</h2>
          <p><a href="{video_url}" style="color:#c2410c; font-weight:bold;">Download my video</a></p>
        </div>
        """
        asunto = f"🎬 {BRAND_NAME_EN}: your video for \"{titulo}\" is ready"
    else:
        cuerpo_html = f"""
        <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
          <h2>🎬 ¡Tu video de "{titulo}" está listo!</h2>
          <p><a href="{video_url}" style="color:#c2410c; font-weight:bold;">Descargar mi video</a></p>
        </div>
        """
        asunto = f"🎬 Tu video ya está listo: {titulo}"

    try:
        await asyncio.to_thread(_enviar_sync, destinatario, asunto, cuerpo_html)
        return True
    except Exception:
        log.exception("Error mandando el correo de video a %s", destinatario)
        return False
