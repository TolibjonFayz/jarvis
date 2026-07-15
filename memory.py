"""Xotira: suhbat tarixi + uzoq muddatli eslab qolishlar (SQLite)."""
import sqlite3
import time
from config import DB_PATH


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                role TEXT,
                content TEXT,
                ts REAL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT,
                ts REAL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                text TEXT,
                due_ts REAL,
                sent INTEGER DEFAULT 0
            )"""
        )


# --- Suhbat tarixi (joriy suhbatni eslab turish uchun) ---

def add_message(chat_id, role, content):
    with _conn() as c:
        c.execute(
            "INSERT INTO history (chat_id, role, content, ts) VALUES (?,?,?,?)",
            (chat_id, role, content, time.time()),
        )


def get_history(chat_id, limit=20):
    """Oxirgi N ta xabarni to'g'ri tartibda qaytaradi."""
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content FROM history WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_history(chat_id):
    with _conn() as c:
        c.execute("DELETE FROM history WHERE chat_id=?", (chat_id,))


# --- Uzoq muddatli xotira (sen haqingda, loyihalar haqida) ---

def add_memory(text):
    with _conn() as c:
        c.execute("INSERT INTO memories (text, ts) VALUES (?,?)", (text, time.time()))


def search_memories(query, limit=10):
    with _conn() as c:
        rows = c.execute(
            "SELECT text FROM memories WHERE text LIKE ? ORDER BY id DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
    return [r["text"] for r in rows]


def all_memories(limit=40):
    with _conn() as c:
        rows = c.execute(
            "SELECT text FROM memories ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [r["text"] for r in rows]


# --- Eslatmalar (vaqti kelganda Telegram'ga yuboriladi) ---

def add_reminder(chat_id, text, due_ts):
    with _conn() as c:
        c.execute(
            "INSERT INTO reminders (chat_id, text, due_ts, sent) VALUES (?,?,?,0)",
            (chat_id, text, due_ts),
        )


def due_reminders():
    """Vaqti kelgan va hali yuborilmagan eslatmalar."""
    now = time.time()
    with _conn() as c:
        rows = c.execute(
            "SELECT id, chat_id, text FROM reminders WHERE sent=0 AND due_ts<=?", (now,)
        ).fetchall()
    return [(r["id"], r["chat_id"], r["text"]) for r in rows]


def mark_reminder_sent(rid):
    with _conn() as c:
        c.execute("UPDATE reminders SET sent=1 WHERE id=?", (rid,))


def list_pending_reminders(chat_id):
    """Hali kutilayotgan (kelajakdagi) eslatmalar."""
    now = time.time()
    with _conn() as c:
        rows = c.execute(
            "SELECT text, due_ts FROM reminders "
            "WHERE chat_id=? AND sent=0 AND due_ts>? ORDER BY due_ts",
            (chat_id, now),
        ).fetchall()
    return [(r["text"], r["due_ts"]) for r in rows]
