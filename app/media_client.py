"""
Cliente del servicio de media de Tunecraft (droplet propio de Diego, ver
tunecraft-media-services/), para el preview de audio antes de pagar y el
video de dedicatoria despues de pagar (solo flujo "v2", ver LANDING_FLOW en
config.py).

Todas las llamadas pasan por aca (nunca directo desde el navegador del
cliente) para que MEDIA_SERVICE_TOKEN nunca se exponga del lado del
cliente - eso incluye la subida de fotos: el navegador se la manda a
cancion-bot, y esta funcion la reenvia al servicio de media sin guardarla
en disco en ningun momento (se lee en memoria y se reenvia).
"""
import httpx

from app.config import MEDIA_SERVICE_TOKEN, MEDIA_SERVICE_URL

_HEADERS = {"Authorization": f"Bearer {MEDIA_SERVICE_TOKEN}"}


async def generar_preview(audio_url: str, seconds: float | None = None) -> str:
    """Recorte del audio real para el preview gratis antes de pagar. Tarda
    segundos, no minutos - se puede esperar de forma sincrona."""
    body = {"audio_url": audio_url}
    if seconds is not None:
        body["seconds"] = seconds
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{MEDIA_SERVICE_URL}/trim", headers=_HEADERS, json=body)
        resp.raise_for_status()
        return resp.json()["preview_url"]


async def subir_foto(filename: str, content: bytes, content_type: str | None) -> str:
    """Reenvia una foto al servicio de media - NUNCA se escribe a disco de
    este lado, solo pasa por memoria camino al droplet."""
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{MEDIA_SERVICE_URL}/upload-photo",
            headers=_HEADERS,
            files={"file": (filename, content, content_type or "application/octet-stream")},
        )
        resp.raise_for_status()
        return resp.json()["url"]


async def solicitar_video(audio_url: str, lyric_text: str, dedication_text: str, image_urls: list[str]) -> str:
    """Arranca la generacion del video (tarda minutos) y regresa el job_id
    para hacer polling con estado_video()."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{MEDIA_SERVICE_URL}/video",
            headers=_HEADERS,
            json={
                "audio_url": audio_url,
                "lyric_text": lyric_text,
                "dedication_text": dedication_text,
                "image_urls": image_urls,
            },
        )
        resp.raise_for_status()
        return resp.json()["job_id"]


async def estado_video(job_id: str) -> dict:
    """{"status": "pending"|"processing"|"done"|"failed", "video_url", "error"}"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{MEDIA_SERVICE_URL}/video/{job_id}", headers=_HEADERS)
        resp.raise_for_status()
        return resp.json()
