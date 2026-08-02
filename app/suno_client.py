"""
Cliente para la API no oficial de Suno via AceDataCloud.

Esta NO es la API oficial de Suno (no existe publica todavia). Es un
proveedor tercero que revende acceso. Uso bajo tu propio riesgo/terminos.

Referencia verificada contra el codigo fuente de su SDK oficial
(github.com/AceDataCloud/SunoMCP, core/client.py):
- POST /suno/audios con "async": true -> devuelve rapido un "task_id" para
  hacer polling (si no se manda async, puede quedarse esperando sincronico
  varios minutos - por eso lo mandamos siempre explicito).
- Para consultar el estado: POST /suno/tasks (NO es un GET a /tasks/{id})
  con body {"id": task_id, "action": "retrieve"}.
- La respuesta de /suno/tasks tiene esta forma:
    {
      "id": "...", "state": "pending" | "processing" | "complete" | "failed",
      "response": {"success": bool, "data": [{"audio_url": ..., "title": ...}], "error": ...}
    }
  Solo "complete" + success=true significa que ya esta lista de verdad -
  puede haber audio_url "de preview" en estados intermedios que NO son el
  resultado final.
"""
import httpx

from app.config import ACEDATACLOUD_API_TOKEN

BASE = "https://api.acedata.cloud/suno"

# La generacion en si puede demorar unos minutos incluso en modo async antes
# de que el endpoint conteste con el task_id, asi que le damos margen.
GENERATE_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=15.0, pool=15.0)


async def generate_custom_song(lyric: str, title: str, style: str, model: str = "chirp-v3-5") -> dict:
    async with httpx.AsyncClient(timeout=GENERATE_TIMEOUT) as client:
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
                "async": True,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_task_status(task_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE}/tasks",
            headers={
                "authorization": f"Bearer {ACEDATACLOUD_API_TOKEN}",
                "accept": "application/json",
                "content-type": "application/json",
            },
            json={"id": task_id, "action": "retrieve"},
        )
        resp.raise_for_status()
        return resp.json()
