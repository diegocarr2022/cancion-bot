"""
Envio del correo de entrega para los pedidos que vienen de la landing web
(/cancion). Usa la API de Mailgun (ago 2026, reemplaza a Gmail SMTP - ver
MAILGUN_API_KEY en config.py para el motivo) - httpx crudo, mismo patron
que el resto del repo (dlocal_client.py, stripe_client.py, etc.), sin el
SDK oficial.

Se manda como respaldo/comprobante - el link de descarga YA aparece directo
en el chat de la landing en cuanto la cancion esta lista (ver /web/status en
main.py); el correo es para quien cierra la pestaña o quiere guardarlo.
"""
import logging

import httpx

from app.config import MAILGUN_API_KEY, MAILGUN_DOMAIN, MAILGUN_FROM_EMAIL, BRAND_NAME_EN

log = logging.getLogger("cancion-bot")

MAILGUN_BASE_URL = "https://api.mailgun.net/v3"


def _from_email() -> str:
    """MAILGUN_FROM_EMAIL si Diego lo configuro explicito, si no un default
    razonable armado con el dominio verificado - Mailgun rechaza mandar
    desde una direccion que no sea de un dominio que verificaste ahi."""
    return MAILGUN_FROM_EMAIL or f"{BRAND_NAME_EN} <noreply@{MAILGUN_DOMAIN}>"


async def _enviar_async(destinatario: str, asunto: str, cuerpo_html: str):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{MAILGUN_BASE_URL}/{MAILGUN_DOMAIN}/messages",
            auth=("api", MAILGUN_API_KEY),  # "api" es literal, no un placeholder - asi lo pide Mailgun
            data={
                "from": _from_email(),
                "to": destinatario,
                "subject": asunto,
                "html": cuerpo_html,
            },
        )
        resp.raise_for_status()


async def enviar_cancion_por_correo(
    destinatario: str, titulo: str, audio_urls: list[str], language: str = "es",
    lyrics_pdf_url: str | None = None,
) -> bool:
    """Devuelve True si se mando (o si no hay credenciales configuradas, para
    no bloquear el flujo), False si hubo un error real intentando mandarlo.
    language: "es" (MX/PE/CO) o "en" (EE.UU. - ver expansion ago 2026)."""
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        log.warning(
            "MAILGUN_API_KEY/MAILGUN_DOMAIN no configurados - se omite el correo de "
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
        await _enviar_async(destinatario, asunto, cuerpo_html)
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
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        log.warning(
            "MAILGUN_API_KEY/MAILGUN_DOMAIN no configurados - se omite el "
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
        await _enviar_async(destinatario, asunto, cuerpo_html)
        return True
    except Exception:
        log.exception("Error mandando el recordatorio de reseña a %s", destinatario)
        return False


async def enviar_video_por_correo(destinatario: str, titulo: str, video_url: str, language: str = "es") -> bool:
    """Fase 2 (upsell de video, ver app/video_client.py): correo separado del
    de la cancion porque el video puede terminar bastante despues (el render
    arranca recien cuando el cliente sube las fotos, que puede ser minutos u
    horas despues de que ya se mando el correo del audio)."""
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        log.warning(
            "MAILGUN_API_KEY/MAILGUN_DOMAIN no configurados - se omite el correo de "
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
        await _enviar_async(destinatario, asunto, cuerpo_html)
        return True
    except Exception:
        log.exception("Error mandando el correo de video a %s", destinatario)
        return False


async def enviar_correo_recuperacion(
    destinatario: str, titulo: str, precio_texto: str, recovery_url: str,
) -> bool:
    """Correo de recuperacion de carrito abandonado (ago 2026, ver
    poll_recovery_email_loop en main.py) - para quien aprobo la letra pero
    nunca completo el pago. Ofrece un precio especial de una sola vez
    (PRECIO_RECOVERY_USD en config.py) para intentar rescatar la venta. Solo
    existe en ingles, mismo criterio que el resto del flujo EN/Stripe."""
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        log.warning(
            "MAILGUN_API_KEY/MAILGUN_DOMAIN no configurados - se omite el "
            "correo de recuperacion para %s.", destinatario,
        )
        return False

    cuerpo_html = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
      <h2>🎵 Still want "{titulo}"?</h2>
      <p>We noticed you wrote the lyrics for your song but didn't finish checkout.
      We really value our customers, and we want you to have your song - so if you
      follow the link below, you can complete it at a special one-time price of
      just {precio_texto}.</p>
      <p><a href="{recovery_url}" style="color:#c2410c; font-weight:bold;">Finish my song for {precio_texto}</a></p>
      <p style="color:#6b7280; font-size:13px;">Your lyrics are already approved and waiting - this just picks up right where you left off.</p>
    </div>
    """
    asunto = f"🎵 {BRAND_NAME_EN}: your song is waiting - special price inside"

    try:
        await _enviar_async(destinatario, asunto, cuerpo_html)
        return True
    except Exception:
        log.exception("Error mandando el correo de recuperacion a %s", destinatario)
        return False


async def enviar_correo_de_prueba(destinatario: str) -> tuple[bool, str]:
    """Solo para confirmar que Mailgun quedo bien configurado (DNS/API key)
    antes de depender de el en un pedido real - ver POST /admin/test-email
    en main.py. Devuelve (ok, detalle) en vez de solo bool: a diferencia de
    las funciones de arriba (que no deben bloquear la entrega de una
    cancion por un error de correo), aca SI queremos saber la razon exacta
    si falla, para poder decirle a Diego que revisar."""
    if not MAILGUN_API_KEY or not MAILGUN_DOMAIN:
        return False, "MAILGUN_API_KEY/MAILGUN_DOMAIN no estan configurados en Render todavia."
    cuerpo_html = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
      <h2>✅ Mailgun esta funcionando</h2>
      <p>Este es un correo de prueba de {BRAND_NAME_EN} - si lo recibiste, el DNS y el API key
      de Mailgun quedaron bien configurados y el correo de entrega real va a funcionar.</p>
    </div>
    """
    try:
        await _enviar_async(destinatario, f"✅ {BRAND_NAME_EN}: prueba de Mailgun", cuerpo_html)
        return True, "Enviado."
    except httpx.HTTPStatusError as e:
        return False, f"Mailgun rechazo el envio: {e.response.status_code} {e.response.text}"
    except Exception as e:
        return False, f"Error inesperado: {e}"
