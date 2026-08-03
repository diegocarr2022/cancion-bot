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


def create_order(chat_id: int):
    """Crea un pedido nuevo para este chat_id. IMPORTANTE: un cliente tiene
    que poder comprar mas de una vez. Como chat_id sigue siendo la clave
    unica de la fila (un pedido "activo" a la vez por chat), si ya existia
    un pedido anterior para este chat_id (tipicamente uno ya completado,
    step="entregado") lo REINICIA por completo - borra letra final, datos de
    pago, historial de mensajes, etc. - para que arranque una compra nueva
    de cero. Esto solo debe llamarse cuando no hay un pedido en curso
    (ver el chequeo en conversation.py antes de llamar a esta funcion)."""
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO orders (chat_id, step, messages, created_at, updated_at)
            VALUES (?, 'creando_pago', '[]', ?, ?)
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
                updated_at = excluded.updated_at
            """,
            (chat_id, now, now),
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
