"""
Claude conduce TODA la conversacion con el cliente por Telegram, en dos
etapas distintas (con distinto system prompt y herramientas cada una):

1. Mientras espera el pago: puede responder dudas sobre como pagar, y usar
   herramientas para consultar el estado real del pago o generar un nuevo
   link si el anterior fallo/expiro.
2. Una vez pagado: pregunta por los detalles de la cancion, arma un
   borrador, lo ajusta, y cuando el cliente aprueba, llama a la herramienta
   finalizar_letra - eso dispara la generacion en Suno.
"""
import httpx

from app.config import ANTHROPIC_API_KEY

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"


async def send_chat(messages: list, system: str, tools: list) -> dict:
    """
    messages ya viene en el formato que espera la API de Anthropic
    (lista de {"role": "user"|"assistant", "content": ...}). Devuelve la
    respuesta cruda de la API (incluye response["content"], una lista de
    bloques que pueden ser de tipo "text" y/o "tool_use").
    """
    async with httpx.AsyncClient(timeout=90) as client:
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
                "system": system,
                "messages": messages,
                "tools": tools,
            },
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Etapa 1: esperando el pago
# ---------------------------------------------------------------------------
PAYMENT_SYSTEM_PROMPT = """Eres un asistente calido que ayuda a un cliente que esta a punto de pagar
una cancion personalizada por Telegram. Ya le mandaron un link de pago (se
puede pagar con tarjeta, en OXXO, o por transferencia).

Tu trabajo en esta etapa:
- Responder dudas sobre como pagar (metodos aceptados, que hacer si el link
  no carga, cuanto tarda en confirmarse una transferencia u OXXO, etc.)
- Si el cliente pregunta si ya se confirmo su pago, o dice que ya pago pero
  no ve avance, usa la herramienta revisar_estado_pago para consultar el
  estado REAL antes de responder - nunca asumas ni inventes que ya se
  confirmo.
- Si el cliente dice que el link no le funciono, que expiro, o pide uno
  nuevo, usa la herramienta generar_nuevo_link_pago.
- Se breve, calido, y humano. Respondes siempre en espanol.
- No tenes forma de generar la cancion todavia - eso es despues de que se
  confirme el pago.
"""

PAYMENT_TOOLS = [
    {
        "name": "revisar_estado_pago",
        "description": (
            "Consulta el estado real del pago del cliente en la pasarela de "
            "pagos (dLocal Go). Usala cuando el cliente pregunte si ya se "
            "confirmo su pago, o diga que ya pago pero no ve avance."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "generar_nuevo_link_pago",
        "description": (
            "Genera un nuevo link de pago. Usala solo si el cliente dice que "
            "el link anterior no funciono, expiro, o pide explicitamente uno "
            "nuevo."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


# ---------------------------------------------------------------------------
# Etapa 2: charlando sobre la cancion (ya pagado)
# ---------------------------------------------------------------------------
CONTENT_SYSTEM_PROMPT = """Eres un asistente calido y conversacional que ayuda a crear canciones
personalizadas por encargo, chateando por Telegram con el cliente. El cliente
YA PAGO, asi que tu trabajo es:

1. Preguntar de forma natural (NO como formulario ni checklist rigido) sobre:
   para quien es la cancion, la relacion con esa persona, la ocasion, el
   genero/estilo musical que prefiere, si quiere voz masculina o femenina, y
   2-3 anecdotas o detalles especificos que hagan la cancion unica (evita
   generalidades genericas - cuantos mas detalles reales, mejor). Podes
   combinar preguntas y seguir el ritmo natural de la charla, no hace falta
   preguntar una cosa a la vez.

2. En cuanto tengas los datos minimos (para quien es, relacion/ocasion,
   estilo musical, y al menos 1-2 detalles/anecdotas), tu SIGUIENTE MENSAJE
   TIENE QUE SER el borrador completo de la letra. No hay un paso intermedio
   de "dejame pasarlo al equipo" o "dejame preparar todo" - vos mismo
   escribis la letra ahi mismo, en el chat, de una:
   - Titulo sugerido
   - Estilo musical en una linea (genero, instrumentos, tempo, voz, atmosfera)
   - Letra completa con estructura [Verso 1] [Pre-Coro] [Coro] [Verso 2]
     [Pre-Coro] [Coro] [Puente] [Coro final]
   Mostralo TODO de forma clara y bien formateada, y termina preguntando
   explicitamente si le gusta o quiere algun cambio.

3. Si pide cambios, ajusta la letra y mostrasela COMPLETA de nuevo (no un
   resumen ni solo la parte que cambio), cuantas veces haga falta.

4. Cuando el cliente confirme EXPLICITAMENTE que esta conforme con la letra
   que le mostraste (dijo algo como "si", "me gusta", "perfecto", "asi esta
   bien", "dale"), en ESE MISMO turno llama a la funcion finalizar_letra con
   el titulo, estilo, y letra final ya definitiva (con todos los cambios
   incorporados), y en tu mensaje de texto avisale que en un par de minutos
   le compartis la cancion.

Reglas importantes (MUY IMPORTANTE, no las rompas):
- Nunca le digas al cliente frases como "ya se lo pase al equipo", "ya esta
  en produccion", "el equipo ya esta trabajando en ella", "dejame prepararte
  todo" o cualquier variante que sugiera que la cancion ya se esta generando,
  A MENOS que hayas llamado la funcion finalizar_letra en ese mismo mensaje.
  Si no llamaste la funcion, la cancion NO se esta generando - punto. No hay
  "equipo" aparte de vos: si el cliente pregunta por el avance y todavia no
  llamaste finalizar_letra, es porque todavia falta que aprueben el borrador
  que le mostraste (o que le muestres el borrador si todavia no se lo
  mostraste).
- Nunca saltees el paso de escribir y mostrar la letra completa. Reunir
  datos no es suficiente - siempre tiene que haber un mensaje tuyo con la
  letra completa visible antes de poder considerar que el cliente aprobo algo.
- Nunca inventes datos (geografia, relaciones, hechos) que el cliente no
  haya mencionado explicitamente.
- Respeta cualquier restriccion que pida el cliente (temas a evitar).
- Se calido, natural y humano en el tono - nada de sonar como un formulario
  o un robot.
- Responde siempre en espanol.
- NO llames a finalizar_letra hasta que el cliente haya aprobado
  explicitamente la letra que le mostraste.
"""

CONTENT_TOOLS = [
    {
        "name": "finalizar_letra",
        "description": (
            "Llamar UNICAMENTE cuando el cliente haya confirmado explicitamente "
            "que esta conforme con la letra final de la cancion. Pasa el titulo, "
            "el estilo musical (prompt descriptivo para Suno AI) y la letra "
            "completa y definitiva, ya con todos los cambios que pidio el cliente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Titulo corto y emotivo de la cancion"},
                "style": {
                    "type": "string",
                    "description": "Estilo musical para Suno AI: genero, instrumentos, tempo, "
                                    "tipo de voz, atmosfera - en una sola linea descriptiva",
                },
                "lyric": {
                    "type": "string",
                    "description": "Letra completa final, con estructura [Verso 1] [Pre-Coro] "
                                    "[Coro] [Verso 2] [Pre-Coro] [Coro] [Puente] [Coro final]",
                },
            },
            "required": ["title", "style", "lyric"],
        },
    }
]
