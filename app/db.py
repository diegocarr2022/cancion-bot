"""
Persistencia muy simple con SQLite.

Guarda por cada chat_id de Telegram:
- El estado del pedido (step): creando_pago, esperando_pago, charlando,
  generando, entregado.
- El historial completo de la conversacion con Claude (messages, en el mismo
  formato que espera la API de Anthropic) - asi Claude mantiene contexto
  entre mensajes.
- La letra/titulo/estilo FINAL una vez que el cliente los aprueba (para poder
  reintentar la generacion en Suno sin tener que volver a chatear si algo falla).
- Datos del pago y de la entrega.

NOTA: en Render, el disco declarado en render.yaml (/data) es persistente entre
despliegues. Si no agregas ese disco, el archivo se borra en cada deploy.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    chat_id INTEGER PRIMARY KEY,
    step TEXT NOT NULL DEFAULT 'creando_pago',
    messages TEXT NOT NULL DEFAULT '[]',
    final_title TEXT,
    final_style TEXT,
    final_lyric TEXT,
    payment_request_id TEXT,
    payment_url TEXT,
    paid INTEGER NOT NULL DEFAULT 0,
    suno_task_id TEXT,
    delivered INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payment_request_id ON orders(payment_request_id);

-- Cada fila es un clic real al link intermedio /ir/<source> (ver main.py),
-- ANTES de que la persona llegue a Telegram. Esto nos deja medir cuanta
-- gente realmente hizo clic en el anuncio, independiente de si despues
-- abrio Telegram y presiono "Iniciar" o no (Telegram no nos avisa de eso -
-- ver el "source" en orders para ese siguiente paso del embudo).
CREATE TABLE IF NOT EXISTS clicks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    user_agent TEXT,
    ip TEXT,
    fbclid TEXT,
    is_bot INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Pedidos que vienen de la landing web (/cancion), en paralelo al flujo de
-- Telegram (tabla orders). Se identifican por session_id (un uuid generado
-- en el navegador del cliente) en vez de chat_id. El orden de pasos es
-- distinto al de Telegram: aca se charla con Claude ANTES de pagar (para no
-- pedirle dinero al cliente antes de mostrarle nada, que es justo la
-- friccion/desconfianza que se queria evitar con esta landing), y recien
-- cuando aprueba la letra se genera el link de pago. Ya con content
-- aprobado, no hace falta que Claude vuelva a hablar despues del pago - se
-- manda derecho a Suno.
CREATE TABLE IF NOT EXISTS web_orders (
    session_id TEXT PRIMARY KEY,
    email TEXT,
    customer_name TEXT,
    step TEXT NOT NULL DEFAULT 'charlando',
    messages TEXT NOT NULL DEFAULT '[]',
    final_title TEXT,
    final_style TEXT,
    final_lyric TEXT,
    payment_request_id TEXT,
    payment_url TEXT,
    paid INTEGER NOT NULL DEFAULT 0,
    amount_mxn REAL,
    suno_task_id TEXT,
    audio_urls TEXT,
    delivered INTEGER NOT NULL DEFAULT 0,
    delivered_email INTEGER NOT NULL DEFAULT 0,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_web_payment_request_id ON web_orders(payment_request_id);
"""

# Migraciones simples para bases de datos que ya existian con el esquema
# viejo (antes de agregar el chat con Claude). No pasa nada si ya existen -
# las ignoramos.
MIGRATIONS = [
    "ALTER TABLE orders ADD COLUMN messages TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE orders ADD COLUMN final_title TEXT",
    "ALTER TABLE orders ADD COLUMN final_style TEXT",
    "ALTER TABLE orders ADD COLUMN final_lyric TEXT",
    # Guarda el precio real (MXN) que se le cobro a ESTE pedido en particular
    # al momento de generar el link de pago - asi el panel de admin puede
    # calcular ingresos reales incluso si el precio cambio con el tiempo
    # (en vez de asumir el precio actual para pedidos viejos).
    "ALTER TABLE orders ADD COLUMN amount_mxn REAL",
    # De donde vino este pedido (marketplace, instagram, tiktok, google, etc.)
    # - se llena a partir del parametro ?start=<source> del deep link de
    # Telegram (ver conversation.py). NULL si el cliente escribio /start a
    # secas, sin venir de ningun link con tracking.
    "ALTER TABLE orders ADD COLUMN source TEXT",
    # Para poder filtrar clics que en realidad son bots/crawlers (de Meta,
    # Telegram, etc. generando la vista previa del link) en vez de personas
    # reales - ver _es_probable_bot() en este mismo archivo.
    "ALTER TABLE clicks ADD COLUMN user_agent TEXT",
    "ALTER TABLE clicks ADD COLUMN ip TEXT",
    "ALTER TABLE clicks ADD COLUMN is_bot INTEGER NOT NULL DEFAULT 0",
    # fbclid: Facebook SOLO lo agrega cuando una persona real toca el link
    # dentro de la app/sitio de Facebook - los crawlers que generan la vista
    # previa piden la URL "pelona" del anuncio, sin este parametro. Es la
    # senal mas confiable que tenemos de que un clic es humano de verdad.
    "ALTER TABLE clicks ADD COLUMN fbclid TEXT",
    # Nombre del cliente, pedido al inicio de la charla web (despues del
    # saludo) - junto con el correo, para poder armar audiencias similares
    # (lookalike) en Meta Ads mas adelante.
    "ALTER TABLE web_orders ADD COLUMN customer_name TEXT",
]


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for statement in MIGRATIONS:
            try:
                conn.execute(statement)
            except sqlite3.OperationalError:
                pass  # la columna ya existe


def get_order(chat_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM orders WHERE chat_id = ?", (chat_id,)).fetchone()
        return dict(row) if row else None


def create_order(chat_id: int, source: str | None = None):
    """Crea un pedido nuevo para este chat_id. IMPORTANTE: un cliente tiene
    que poder comprar mas de una vez. Como chat_id sigue siendo la clave
    unica de la fila (un pedido "activo" a la vez por chat), si ya existia
    un pedido anterior para este chat_id (tipicamente uno ya completado,
    step="entregado") lo REINICIA por completo - borra letra final, datos de
    pago, historial de mensajes, etc. - para que arranque una compra nueva
    de cero. Esto solo debe llamarse cuando no hay un pedido en curso
    (ver el chequeo en conversation.py antes de llamar a esta funcion).

    source: de donde vino este pedido (marketplace, instagram, etc.), sacado
    del parametro ?start=<source> del deep link de Telegram. None si el
    cliente escribio /start a secas."""
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO orders (chat_id, step, messages, source, created_at, updated_at)
            VALUES (?, 'creando_pago', '[]', ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                step = 'creando_pago',
                messages = '[]',
                final_title = NULL,
                final_style = NULL,
                final_lyric = NULL,
                payment_request_id = NULL,
                payment_url = NULL,
                paid = 0,
                suno_task_id = NULL,
                delivered = 0,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (chat_id, source, now, now),
        )


# Fragmentos de user-agent tipicos de bots/crawlers (de Meta generando la
# vista previa del link al guardar el anuncio, de Telegram haciendo lo
# mismo, de escaneres de seguridad, etc.) - si el user-agent contiene
# cualquiera de estos, NO es una persona real haciendo clic.
_BOT_UA_HINTS = (
    "facebookexternalhit", "facebookcatalog", "meta-externalagent",
    "telegrambot", "bot", "crawl", "spider", "preview", "curl",
    "python-requests", "wget", "headless", "monitor", "uptime", "pingdom",
    "slurp", "bingpreview", "whatsapp",
)


def _es_probable_bot(user_agent: str | None) -> bool:
    if not user_agent:
        return True  # nadie con un navegador real manda un User-Agent vacio
    ua = user_agent.lower()
    return any(hint in ua for hint in _BOT_UA_HINTS)


def log_click(
    source: str,
    user_agent: str | None = None,
    ip: str | None = None,
    fbclid: str | None = None,
):
    """Registra un clic real al link intermedio /ir/<source>, ANTES de que
    la persona llegue a Telegram (ver main.py). Esta es la unica forma de
    saber cuanta gente hizo clic de verdad, ya que Telegram no avisa cuando
    alguien abre el chat sin presionar 'Iniciar'.

    IMPORTANTE: guardamos TODOS los clics (incluidos los de bots) para no
    perder informacion, pero marcamos is_bot para poder filtrarlos despues -
    Meta/Telegram/WhatsApp mandan sus propios crawlers a "visitar" el link
    apenas se guarda o se comparte un anuncio, generando clics falsos que no
    son personas reales.

    fbclid: Facebook lo agrega al link desde que lo sirve/envuelve, no solo
    cuando una persona hace clic - por eso los propios bots de revision de
    anuncios de Facebook TAMBIEN pueden traerlo. No es prueba de humano, asi
    que lo guardamos solo como dato de referencia y NO lo usamos para decidir
    is_bot. La clasificacion real sigue siendo por User-Agent."""
    now = datetime.utcnow().isoformat()
    is_bot = _es_probable_bot(user_agent)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO clicks (source, user_agent, ip, fbclid, is_bot, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (source, user_agent, ip, fbclid, int(is_bot), now),
        )


def get_click_stats():
    """Clics por canal (solo los que parecen personas reales, no bots), y
    cuantos de esos canales efectivamente llegaron a iniciar un pedido en
    Telegram (con ese mismo source) - para comparar 'clics reales' vs 'gente
    que de verdad abrio el bot'."""
    with get_conn() as conn:
        clicks_rows = conn.execute(
            "SELECT source, COUNT(*) AS n FROM clicks WHERE is_bot = 0 "
            "GROUP BY source ORDER BY n DESC"
        ).fetchall()
        starts_rows = conn.execute(
            "SELECT source, COUNT(*) AS n, SUM(paid) AS pagados, "
            "COALESCE(SUM(CASE WHEN paid = 1 THEN amount_mxn ELSE 0 END), 0) AS ingresos "
            "FROM orders WHERE source IS NOT NULL GROUP BY source"
        ).fetchall()
        starts_by_source = {r["source"]: dict(r) for r in starts_rows}

        resultado = []
        vistos = set()
        for r in clicks_rows:
            source = r["source"]
            vistos.add(source)
            starts = starts_by_source.get(source, {"n": 0, "pagados": 0, "ingresos": 0})
            resultado.append({
                "source": source,
                "clics": r["n"],
                "inicios_telegram": starts["n"],
                "pagados": starts["pagados"] or 0,
                "ingresos_mxn": starts["ingresos"] or 0,
            })
        # por si hay ordenes con un source que nunca paso por /ir/<source>
        # (por ejemplo si alguien comparte el link de Telegram directo)
        for source, starts in starts_by_source.items():
            if source not in vistos:
                resultado.append({
                    "source": source,
                    "clics": 0,
                    "inicios_telegram": starts["n"],
                    "pagados": starts["pagados"] or 0,
                    "ingresos_mxn": starts["ingresos"] or 0,
                })
        return resultado


def get_bot_clicks_total() -> int:
    """Cuantos clics se filtraron por parecer bots/crawlers - solo para
    mostrar en el panel de admin como referencia, asi no parece que los
    datos "desaparecen" sin explicacion."""
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM clicks WHERE is_bot = 1").fetchone()
        return row["n"]


def update_order(chat_id: int, **fields):
    if not fields:
        return
    fields["updated_at"] = datetime.utcnow().isoformat()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [chat_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE orders SET {cols} WHERE chat_id = ?", values)


def get_messages(chat_id: int) -> list:
    order = get_order(chat_id)
    if not order or not order.get("messages"):
        return []
    return json.loads(order["messages"])


def set_messages(chat_id: int, messages: list):
    update_order(chat_id, messages=json.dumps(messages, ensure_ascii=False))


def save_final_letra(chat_id: int, title: str, style: str, lyric: str):
    update_order(chat_id, final_title=title, final_style=style, final_lyric=lyric)


def find_by_payment_request_id(payment_request_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE payment_request_id = ?", (payment_request_id,)
        ).fetchone()
        return dict(row) if row else None


def find_unfinished_suno_tasks():
    """Pedidos pagados, con task de Suno en curso, y aun no entregados."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE paid = 1 AND suno_task_id IS NOT NULL AND delivered = 0"
        ).fetchall()
        return [dict(r) for r in rows]


def find_pending_payments():
    """Pedidos que ya tienen un link de pago generado pero todavia no se
    confirman como pagados - para el chequeo automatico en segundo plano."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE paid = 0 AND payment_request_id IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_orders(limit: int = 300):
    """Todos los pedidos, mas recientes primero - para el panel de admin."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_stats():
    """Resumen agregado para el panel de admin: ventas, ingresos, embudo."""
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM orders").fetchone()["n"]
        pagados = conn.execute("SELECT COUNT(*) AS n FROM orders WHERE paid = 1").fetchone()["n"]
        entregados = conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE step = 'entregado'"
        ).fetchone()["n"]
        en_curso = conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE paid = 1 AND step != 'entregado'"
        ).fetchone()["n"]
        esperando_pago = conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE paid = 0 AND payment_request_id IS NOT NULL"
        ).fetchone()["n"]
        fallidos = conn.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE step = 'pago_fallido'"
        ).fetchone()["n"]
        ingresos = conn.execute(
            "SELECT COALESCE(SUM(amount_mxn), 0) AS total FROM orders WHERE paid = 1"
        ).fetchone()["total"]
        ingresos_hoy = conn.execute(
            "SELECT COALESCE(SUM(amount_mxn), 0) AS total FROM orders "
            "WHERE paid = 1 AND date(updated_at) = date('now')"
        ).fetchone()["total"]
        return {
            "total": total,
            "pagados": pagados,
            "entregados": entregados,
            "en_curso": en_curso,
            "esperando_pago": esperando_pago,
            "fallidos": fallidos,
            "ingresos_mxn": ingresos or 0,
            "ingresos_hoy_mxn": ingresos_hoy or 0,
        }


def find_stuck_generation(older_than_seconds: int = 900):
    """Pedidos que ya tienen la letra final aprobada, deberian estar
    generandose en Suno, pero no tienen task_id - suele pasar si el proceso
    se reinicio (deploy) justo mientras se estaba mandando a generar. Se
    reintentan solos, sin que nadie tenga que escribir un comando.

    IMPORTANTE: el umbral (900s = 15 min) tiene que ser MAYOR al tiempo
    maximo que puede tardar una generacion normal (hasta 600s/10 min, ver
    GENERATE_TIMEOUT en suno_client.py) - si no, este chequeo podria
    reintentar una generacion que en realidad sigue en curso normalmente en
    el mismo proceso, generando una cancion duplicada."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE step = 'generando' AND suno_task_id IS NULL "
            "AND final_lyric IS NOT NULL "
            "AND (julianday('now') - julianday(updated_at)) * 86400 > ?",
            (older_than_seconds,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# web_orders: mismo patron que orders, pero identificados por session_id
# (uuid) en vez de chat_id - para los pedidos que vienen de la landing web
# (/cancion) en vez de Telegram. Ver comentario en SCHEMA para el porque del
# orden de pasos distinto (charlando -> esperando_pago -> generando -> entregado).
# ---------------------------------------------------------------------------
def get_web_order(session_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM web_orders WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None


def create_web_order(session_id: str, email: str | None = None, source: str | None = None):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO web_orders (session_id, email, step, messages, source, created_at, updated_at)
            VALUES (?, ?, 'charlando', '[]', ?, ?, ?)
            """,
            (session_id, email, source, now, now),
        )


def update_web_order(session_id: str, **fields):
    if not fields:
        return
    fields["updated_at"] = datetime.utcnow().isoformat()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [session_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE web_orders SET {cols} WHERE session_id = ?", values)


def get_web_messages(session_id: str) -> list:
    order = get_web_order(session_id)
    if not order or not order.get("messages"):
        return []
    return json.loads(order["messages"])


def set_web_messages(session_id: str, messages: list):
    update_web_order(session_id, messages=json.dumps(messages, ensure_ascii=False))


def save_web_final_letra(session_id: str, title: str, style: str, lyric: str):
    update_web_order(session_id, final_title=title, final_style=style, final_lyric=lyric)


def find_web_by_payment_request_id(payment_request_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM web_orders WHERE payment_request_id = ?", (payment_request_id,)
        ).fetchone()
        return dict(row) if row else None


def find_unfinished_web_suno_tasks():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM web_orders WHERE paid = 1 AND suno_task_id IS NOT NULL AND delivered = 0"
        ).fetchall()
        return [dict(r) for r in rows]


def find_pending_web_payments():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM web_orders WHERE paid = 0 AND payment_request_id IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]


def get_web_stats():
    """Resumen chico de la landing web, para mostrar junto al panel de admin
    de Telegram y no perder visibilidad de este canal nuevo."""
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM web_orders").fetchone()["n"]
        pagados = conn.execute("SELECT COUNT(*) AS n FROM web_orders WHERE paid = 1").fetchone()["n"]
        entregados = conn.execute(
            "SELECT COUNT(*) AS n FROM web_orders WHERE step = 'entregado'"
        ).fetchone()["n"]
        ingresos = conn.execute(
            "SELECT COALESCE(SUM(amount_mxn), 0) AS total FROM web_orders WHERE paid = 1"
        ).fetchone()["total"]
        return {
            "total": total,
            "pagados": pagados,
            "entregados": entregados,
            "ingresos_mxn": ingresos or 0,
        }


def get_all_web_orders(limit: int = 300):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM web_orders ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
