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
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO orders (chat_id, step, messages, created_at, updated_at) "
            "VALUES (?, 'creando_pago', '[]', ?, ?)",
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
