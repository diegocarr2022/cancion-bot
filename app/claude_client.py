"""
Usa la API de Claude (Anthropic) para redactar automaticamente la letra y
el estilo musical a partir de los datos que dio el cliente por Telegram.

Esta es la parte que reemplaza el trabajo manual que hicimos juntos en el
chat para la cancion de prueba (Diego Andres): ahora lo hace el propio
servidor, sin intervencion humana, para cada pedido nuevo.
"""
import json
import httpx

from app.config import ANTHROPIC_API_KEY

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """Eres un compositor experto en canciones personalizadas por encargo.
Con los datos que te den de un pedido, generas:
1. Un titulo corto y emotivo
2. Un "style" (prompt de estilo musical para Suno AI): genero, instrumentos,
   tempo, tipo de voz, atmosfera - todo en una sola linea descriptiva
3. Una letra completa en español, con estructura [Verso 1] [Pre-Coro] [Coro]
   [Verso 2] [Pre-Coro] [Coro] [Puente] [Coro final], que use los detalles y
   anecdotas reales que te den (evita generalidades geneticas, se especifico).
Reglas importantes:
- Nunca inventes datos geograficos o de relaciones que no esten en el pedido
  (ej: no asumas mar/costa si no se menciono, no asumas que alguien enseño
  algo a menos que se diga explicitamente).
- Respeta las restricciones que pida el cliente (temas a evitar).
- Responde EXCLUSIVAMENTE con un JSON valido con las claves: title, style, lyric.
"""


async def draft_song(order_data: dict) -> dict:
    user_content = (
        "Datos del pedido:\n" + json.dumps(order_data, ensure_ascii=False, indent=2)
    )
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            ANTHROPIC_API,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-5",
                "max_tokens": 2000,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_content}],
            },
        )
        resp.raise_for_status()
        result = resp.json()
        text = result["content"][0]["text"]
        return json.loads(text)
