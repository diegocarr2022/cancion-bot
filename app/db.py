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
    last_checked_at TEXT,
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
    country TEXT NOT NULL DEFAULT 'MX',
    currency TEXT NOT NULL DEFAULT 'MXN',
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
    last_checked_at TEXT,
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
    # Pais/moneda de este pedido (ver ?country= en app/landing.py y
    # PAISES_SOPORTADOS en app/config.py) - default Mexico para pedidos viejos.
    "ALTER TABLE web_orders ADD COLUMN country TEXT NOT NULL DEFAULT 'MX'",
    "ALTER TABLE web_orders ADD COLUMN currency TEXT NOT NULL DEFAULT 'MXN'",
    # Cuando fue la ultima vez que efectivamente se le pregunto a dLocal Go
    # por este pago (distinto de updated_at, que marca cuando se genero el
    # link) - se usa para espaciar los chequeos de pagos viejos sin resolver
    # y no perder tiempo/memoria reconsultando muy seguido algo que probablemente
    # ya se abandono. Ver PENDING_PAYMENT_BACKOFF_* en config.py.
    "ALTER TABLE orders ADD COLUMN last_checked_at TEXT",
    "ALTER TABLE web_orders ADD COLUMN last_checked_at TEXT",
    # Datos para mandar el evento "Purchase" a la Conversions API de Meta al
    # confirmarse el pago (ver app/meta_capi.py) - sin esto, Meta no puede
    # medir el costo de adquisicion real ni optimizar la entrega de los
    # anuncios hacia gente que efectivamente compra. fbclid/fbp se capturan
    # en el navegador (landing.py) al crear la sesion; ip/user_agent se leen
    # del propio request en /web/session (main.py).
    "ALTER TABLE web_orders ADD COLUMN fbclid TEXT",
    "ALTER TABLE web_orders ADD COLUMN fbp TEXT",
    "ALTER TABLE web_orders ADD COLUMN client_ip TEXT",
    "ALTER TABLE web_orders ADD COLUMN client_user_agent TEXT",
    # Expansion a EE.UU. (ago 2026): idioma de la sesion (?lang= en la URL del
    # anuncio o Accept-Language del navegador - ver /cancion en main.py) y el
    # tier elegido ("song" o "song_video", este ultimo solo para US mientras
    # ENABLE_VIDEO_TIER este activo). gateway indica que pasarela genero el
    # payment_request_id de este pedido ("dlocal" o "paypal") - necesario
    # porque cada una tiene su propia forma de consultar el estado real de un
    # pago (ver check_web_payment_status en main.py).
    "ALTER TABLE web_orders ADD COLUMN language TEXT NOT NULL DEFAULT 'es'",
    "ALTER TABLE web_orders ADD COLUMN tier TEXT NOT NULL DEFAULT 'song'",
    "ALTER TABLE web_orders ADD COLUMN gateway TEXT",
    # Columnas del upsell de video (Fase 2) - se agregan ya de una para no
    # tener que migrar dos veces, aunque no se usen hasta que ENABLE_VIDEO_TIER
    # este activo. video_status es independiente de "step": un fallo de video
    # NUNCA debe bloquear ni demorar la entrega de la cancion.
    "ALTER TABLE web_orders ADD COLUMN audio_duration REAL",
    "ALTER TABLE web_orders ADD COLUMN photos_json TEXT",
    "ALTER TABLE web_orders ADD COLUMN video_status TEXT NOT NULL DEFAULT 'none'",
    "ALTER TABLE web_orders ADD COLUMN video_path TEXT",
    "ALTER TABLE web_orders ADD COLUMN video_url TEXT",
    "ALTER TABLE web_orders ADD COLUMN video_error TEXT",
    # final_gender ("f"/"m"/NULL): genero de voz que el cliente pidio,
    # capturado aparte de "style" para poder mandarselo a Suno en su campo
    # dedicado (ver app/suno_client.py) en vez de depender de que lo respete
    # dentro del texto libre de estilo - de ahi salio una entrega con la voz
    # equivocada. Por ahora solo lo llena el flujo en ingles (Tunecraft); se
    # agrega tambien en "orders" (Telegram) por consistencia con el resto de
    # las columnas final_*, aunque todavia no se use ahi.
    "ALTER TABLE web_orders ADD COLUMN final_gender TEXT",
    "ALTER TABLE orders ADD COLUMN final_gender TEXT",
    # UTM + gclid del link del anuncio (ver iniciar() en landing.py) - antes
    # solo se guardaba un "source" custom y el fbclid de Meta; faltaba lo
    # necesario para atribuir trafico a campanas/grupos de anuncios reales de
    # Google Ads (gclid) y para saber que campana/anuncio especifico convirtio
    # (utm_campaign/utm_content), que es la base para poder mostrar copy
    # distinto por grupo de anuncios mas adelante.
    "ALTER TABLE web_orders ADD COLUMN utm_source TEXT",
    "ALTER TABLE web_orders ADD COLUMN utm_medium TEXT",
    "ALTER TABLE web_orders ADD COLUMN utm_campaign TEXT",
    "ALTER TABLE web_orders ADD COLUMN utm_content TEXT",
    "ALTER TABLE web_orders ADD COLUMN utm_term TEXT",
    "ALTER TABLE web_orders ADD COLUMN gclid TEXT",
    # Pedido de reseña de Trustpilot (ver Diego: pedirla justo al momento de
    # la entrega, no dias despues por correo - el recordatorio por correo es
    # solo un respaldo si no le dio clic ahi mismo).
    "ALTER TABLE web_orders ADD COLUMN review_link_clicked INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE web_orders ADD COLUMN review_email_sent INTEGER NOT NULL DEFAULT 0",
    # Stripe (reemplaza a PayPal en el flujo EN) es checkout embebido, sin
    # redireccion - no hay "payment_url" que guardar, en su lugar se guarda
    # el client_secret que el frontend usa para montar el Payment Element.
    "ALTER TABLE web_orders ADD COLUMN stripe_client_secret TEXT",
    # ago 2026: precio en MXN por IP para la landing en ingles (ver
    # get_precio_en_mx/resolve_precio_orden en config.py) - NULL para el
    # caso normal (USD), "mx_en" cuando Cloudflare detecto al visitante en
    # Mexico al crear la sesion (ver /web/session en main.py). Se guarda en
    # vez de solo confiar en country="US" para que cualquier recalculo
    # posterior del precio (aprobar letra, recuperar pedido por correo)
    # siga cobrando exactamente lo mismo que se le mostro al inicio, sin
    # importar si el visitante cambio de red/IP a mitad de la charla.
    "ALTER TABLE web_orders ADD COLUMN price_override TEXT",
    # ago 2026: correo de recuperacion de carrito abandonado (cupon de un
    # solo uso para quien aprobo la letra pero nunca pago) - ver
    # poll_recovery_email_loop en main.py. Mismo patron que
    # review_email_sent: evita mandarlo mas de una vez por pedido.
    "ALTER TABLE web_orders ADD COLUMN recovery_email_sent INTEGER NOT NULL DEFAULT 0",
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


def touch_last_checked(chat_id: int, timestamp: str):
    """Actualiza SOLO last_checked_at, sin pasar por update_order() (que
    siempre pisa 'updated_at' en cada llamada). Es a proposito: 'updated_at'
    tiene que seguir reflejando cuando se genero el link de pago (para el
    corte de PENDING_PAYMENT_MAX_HORAS en main.py) - si un simple chequeo de
    backoff lo reiniciara cada vez, un pago abandonado nunca llegaria a
    vencerse."""
    with get_conn() as conn:
        conn.execute("UPDATE orders SET last_checked_at = ? WHERE chat_id = ?", (timestamp, chat_id))


def touch_last_checked_web(session_id: str, timestamp: str):
    """Ver touch_last_checked() - misma logica para web_orders."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE web_orders SET last_checked_at = ? WHERE session_id = ?", (timestamp, session_id)
        )


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
    confirman como pagados - para el chequeo automatico en segundo plano.
    Excluye los que ya se marcaron 'pago_fallido' (incluye los vencidos por
    abandono, ver PENDING_PAYMENT_MAX_HORAS en config.py) para no seguir
    reconsultandolos para siempre."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE paid = 0 AND payment_request_id IS NOT NULL "
            "AND step != 'pago_fallido'"
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_orders(limit: int = 300):
    """Todos los pedidos, mas recientes primero - para el panel de admin."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def reset_all():
    """Borra TODO el historial (Telegram + web + clicks) - usado desde el
    boton de reset del panel de admin, para arrancar en limpio despues de
    pruebas/aprobacion de Facebook. Irreversible - no hay respaldo."""
    with get_conn() as conn:
        conn.execute("DELETE FROM orders")
        conn.execute("DELETE FROM web_orders")
        conn.execute("DELETE FROM clicks")


def get_recent_deliveries(limit: int = 20):
    """Ultimas canciones entregadas de AMBOS canales juntos (Telegram + web) -
    get_stats()/get_web_stats() cuentan cada canal por separado, asi que no
    hay ningun lugar que muestre "lo ultimo que se entrego" sin importar de
    donde vino."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT 'telegram' AS canal, CAST(chat_id AS TEXT) AS id, final_title AS titulo,
                   amount_mxn AS monto, 'MXN' AS moneda, updated_at
            FROM orders WHERE step = 'entregado'
            UNION ALL
            SELECT 'web' AS canal, session_id AS id, final_title AS titulo,
                   amount_mxn AS monto, currency AS moneda, updated_at
            FROM web_orders WHERE step = 'entregado'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
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


def find_recent_web_order_by_email(email: str, language: str | None = None):
    """El pedido web mas reciente con ese correo - usado por la herramienta
    de recuperacion de sesion perdida (buscar_pedido_por_correo /
    find_previous_order en claude_client.py) para cuando el cliente vuelve
    sin su session_id original (cerro la pestaña, le fallo el pago, etc.).
    Filtrado por idioma para no confundir un pedido ES con uno EN si por
    casualidad coincide el correo entre mercados. Si el mismo correo tiene
    varios pedidos, se queda con el mas reciente - una limitacion conocida
    para el caso raro de alguien con mas de un pedido activo a la vez."""
    with get_conn() as conn:
        query = "SELECT * FROM web_orders WHERE LOWER(email) = LOWER(?)"
        params = [email.strip()]
        if language:
            query += " AND language = ?"
            params.append(language)
        query += " ORDER BY created_at DESC LIMIT 1"
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None


def mark_review_link_clicked(session_id: str):
    update_web_order(session_id, review_link_clicked=1)


def find_web_orders_pending_recovery_email(min_hours: int = 2, max_hours: int = 48):
    """Pedidos que llegaron a aprobar la letra (final_lyric ya existe, se
    genero un link de pago) pero nunca pagaron, en ingles, con correo -
    entre min_hours y max_hours desde la ultima actualizacion (ni tan
    reciente que todavia podria estar a mitad de pagar, ni tan viejo que ya
    se le dio por perdido del todo - ver PENDING_PAYMENT_MAX_HORAS en
    main.py, que marca step="pago_fallido" pasado ese corte), que todavia
    no recibio el correo con el precio especial de recuperacion."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM web_orders
            WHERE paid = 0
              AND delivered = 0
              AND language = 'en'
              AND final_lyric IS NOT NULL
              AND email IS NOT NULL
              AND step != 'pago_fallido'
              AND recovery_email_sent = 0
              AND datetime(updated_at) <= datetime('now', ?)
              AND datetime(updated_at) >= datetime('now', ?)
            """,
            (f"-{min_hours} hours", f"-{max_hours} hours"),
        ).fetchall()
        return [dict(r) for r in rows]


def find_web_orders_pending_review_reminder(min_hours_since_delivery: int = 48):
    """Pedidos entregados hace mas de min_hours_since_delivery, en ingles,
    que no le dieron clic al link de reseña en el momento de la entrega ni
    ya se les mando el correo de recordatorio - ver Diego: el pedido
    principal es en el momento, esto es solo el respaldo."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM web_orders
            WHERE delivered = 1
              AND language = 'en'
              AND review_link_clicked = 0
              AND review_email_sent = 0
              AND email IS NOT NULL
              AND datetime(updated_at) <= datetime('now', ?)
            """,
            (f"-{min_hours_since_delivery} hours",),
        ).fetchall()
        return [dict(r) for r in rows]


def create_web_order(
    session_id: str,
    email: str | None = None,
    source: str | None = None,
    country: str = "MX",
    currency: str = "MXN",
    fbclid: str | None = None,
    fbp: str | None = None,
    client_ip: str | None = None,
    client_user_agent: str | None = None,
    language: str = "es",
    tier: str = "song",
    utm_source: str | None = None,
    utm_medium: str | None = None,
    utm_campaign: str | None = None,
    utm_content: str | None = None,
    utm_term: str | None = None,
    gclid: str | None = None,
    price_override: str | None = None,
):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO web_orders
                (session_id, email, step, messages, source, country, currency,
                 fbclid, fbp, client_ip, client_user_agent, language, tier,
                 utm_source, utm_medium, utm_campaign, utm_content, utm_term, gclid,
                 price_override, created_at, updated_at)
            VALUES (?, ?, 'charlando', '[]', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, email, source, country, currency,
             fbclid, fbp, client_ip, client_user_agent, language, tier,
             utm_source, utm_medium, utm_campaign, utm_content, utm_term, gclid,
             price_override, now, now),
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


def save_web_final_letra(session_id: str, title: str, style: str, lyric: str, gender: str | None = None):
    update_web_order(session_id, final_title=title, final_style=style, final_lyric=lyric, final_gender=gender)


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


def find_stuck_web_video(older_than_seconds: int = 1200):
    """Pedidos de tier 'song_video' que quedaron a mitad de un render (proceso
    reiniciado por un deploy) - mismo patron que find_stuck_generation(). El
    umbral (1200s = 20 min) tiene que ser mayor al tiempo maximo que puede
    tardar un render normal (unos pocos minutos para 3-5 fotos)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM web_orders WHERE video_status = 'renderizando' "
            "AND (julianday('now') - julianday(updated_at)) * 86400 > ?",
            (older_than_seconds,),
        ).fetchall()
        return [dict(r) for r in rows]


def find_pending_web_payments():
    """Ver find_pending_payments() - misma exclusion de 'pago_fallido' para
    no reconsultar pagos vencidos/abandonados para siempre."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM web_orders WHERE paid = 0 AND payment_request_id IS NOT NULL "
            "AND step != 'pago_fallido'"
        ).fetchall()
        return [dict(r) for r in rows]


def get_web_stats():
    """Resumen chico de la landing web, para mostrar junto al panel de admin
    de Telegram y no perder visibilidad de este canal nuevo.

    IMPORTANTE: como ahora hay pedidos en distintas monedas (MXN, PEN, COP,
    etc. - ver PAISES_SOPORTADOS en config.py), los ingresos se agrupan POR
    MONEDA en vez de sumarse todos juntos en un solo numero - sumar 197 MXN
    + 37 PEN como si fueran la misma unidad daria un total sin sentido."""
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM web_orders").fetchone()["n"]
        pagados = conn.execute("SELECT COUNT(*) AS n FROM web_orders WHERE paid = 1").fetchone()["n"]
        entregados = conn.execute(
            "SELECT COUNT(*) AS n FROM web_orders WHERE step = 'entregado'"
        ).fetchone()["n"]
        ingresos_rows = conn.execute(
            "SELECT currency, COALESCE(SUM(amount_mxn), 0) AS total FROM web_orders "
            "WHERE paid = 1 GROUP BY currency"
        ).fetchall()
        return {
            "total": total,
            "pagados": pagados,
            "entregados": entregados,
            "ingresos_por_moneda": [dict(r) for r in ingresos_rows],
        }


def get_all_web_orders(limit: int = 300):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM web_orders ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
