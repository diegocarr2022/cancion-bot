"""
Cliente para la API no oficial de Suno via AceDataCloud.

Esta NO es la API oficial de Suno (no existe publica todavia). Es un
proveedor tercero que revende acceso. Uso bajo tu propio riesgo/terminos.
"""
import httpx

from app.config import ACEDATACLOUD_API_TOKEN

BASE = "https://api.acedata.cloud/suno"


async def generate_custom_song(lyric: str, title: str, style: str, model: str = "chirp-v3-5") -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{BASE}/audios",
            headers={
                "authorization": f"Bearer {ACEDATACLOUD_API_TOKEN}",
                "accept": "application/json",
                "content-type": "application/json",
            },
            json={
                "action": "generate",
                "model": model,
                "custom": True,
                "lyric": lyric,
                "title": title,
                "style": style,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_task_status(task_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{BASE}/tasks/{task_id}",
            headers={
                "authorization": f"Bearer {ACEDATACLOUD_API_TOKEN}",
                "accept": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()
