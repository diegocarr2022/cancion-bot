"""
Persistencia muy simple con SQLite.

Guarda:
- El estado de la conversacion con cada chat de Telegram (que pregunta va)
- Los datos del pedido que se van recabando
- El pedido final: link de pago, estado de pago, task_id de Suno, y si ya se entrego

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
    step TEXT NOT NULL DEFAULT 'nombre',
    data TEXT NOT NULL DEFAULT '{}',
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


def get_order(chat_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM orders WHERE chat_id = ?", (chat_id,)).fetchone()
        return dict(row) if row else None


def create_order(chat_id: int):
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO orders (chat_id, step, data, created_at, updated_at) "
            "VALUES (?, 'nombre', '{}', ?, ?)",
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


def get_data(chat_id: int) -> dict:
    order = get_order(chat_id)
    return json.loads(order["data"]) if order else {}


def set_data_field(chat_id: int, field: str, value: str):
    data = get_data(chat_id)
    data[field] = value
    update_order(chat_id, data=json.dumps(data, ensure_ascii=False))


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
