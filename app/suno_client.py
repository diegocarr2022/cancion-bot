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


async def generate_custom_song(
    lyric: str, title: str, style: str, model: str = "chirp-v5-5", gender: str | None = None
) -> dict:
    """gender: "f" (voz femenina) o "m" (voz masculina) - solo soportado en
    modelos v4.5+ (por eso el default ya no es chirp-v3-5, que ademas topaba
    la duracion en 120 segundos). chirp-v5-5 en vez de v4-5: mismo rango de
    precio en AceDataCloud (0.56 vs 0.47 creditos, diferencia marginal contra
    el precio de venta) y notablemente mejor calidad de voz - confirmado
    escuchando las muestras reales usadas en la landing en ingles. Antes de
    este cambio, el pedido de genero de voz del cliente solo se le mandaba a
    Suno mezclado dentro del texto libre de "style" (ej. "...female
    vocals..."), donde Suno no lo respeta de forma confiable - de ahi salio
    una entrega con la voz equivocada. Se deja afuera del payload si no se
    especifica, para no forzar un valor cuando al cliente no le importa."""
    payload = {
        "action": "generate",
        "model": model,
        "custom": True,
        "lyric": lyric,
        "title": title,
        "style": style,
        "async": True,
    }
    if gender in ("f", "m"):
        payload["gender"] = gender

    async with httpx.AsyncClient(timeout=GENERATE_TIMEOUT) as client:
        resp = await client.post(
            f"{BASE}/audios",
            headers={
                "authorization": f"Bearer {ACEDATACLOUD_API_TOKEN}",
                "accept": "application/json",
                "content-type": "application/json",
            },
            json=payload,
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


def extract_ready_items(task: dict) -> dict:
    """Logica compartida (Telegram y web) para decidir que variantes de Suno
    ya estan completamente listas para entregar. Ver la nota larga en
    main.py/check_and_deliver: "state"/"success" a nivel de tarea no son
    confiables, la señal real es que cada variante tenga audio_url Y duration."""
    response = task.get("response") or {}
    success = response.get("success")
    items = response.get("data") or []
    total_items = len(items)

    ready_items = []
    failed_count = 0
    for item in items:
        item_state = (item.get("state") or "").lower()
        if item_state in ("error", "failed"):
            failed_count += 1
            continue
        if item.get("audio_url") and item.get("duration"):
            ready_items.append(item)

    pendientes = total_items - failed_count - len(ready_items)
    fallo_total = success is False or (total_items > 0 and failed_count == total_items)

    return {
        "ready_items": ready_items,
        "failed_count": failed_count,
        "total_items": total_items,
        "pendientes": pendientes,
        "fallo_total": fallo_total,
        "success": success,
    }
