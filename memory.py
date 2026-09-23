"""Xotira: suhbat tarixi + uzoq muddatli eslab qolishlar (SQLite)."""
import sqlite3
import time
import datetime
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
        c.execute(
            """CREATE TABLE IF NOT EXISTS warns (
                chat_id INTEGER,
                user_id INTEGER,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, user_id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS settings (
                chat_id INTEGER,
                key TEXT,
                value TEXT,
                PRIMARY KEY (chat_id, key)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                text TEXT,
                done INTEGER DEFAULT 0,
                ts REAL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS recurring (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                text TEXT,
                hour INTEGER,
                minute INTEGER,
                dow INTEGER,
                last_fired TEXT DEFAULT ''
            )"""
        )
        # Aqlli xotira ustunlari (eski bazalarga ham qo'shiladi).
        cols = {r["name"] for r in c.execute("PRAGMA table_info(memories)")}
        for col, ddl in (
            ("category", "TEXT DEFAULT 'boshqa'"),
            ("importance", "INTEGER DEFAULT 2"),
            ("updated", "REAL"),
        ):
            if col not in cols:
                c.execute(f"ALTER TABLE memories ADD COLUMN {col} {ddl}")
        c.execute(
            """CREATE TABLE IF NOT EXISTS digest_channels (
                chat_id INTEGER,
                channel_id INTEGER,
                title TEXT,
                username TEXT,
                last_id INTEGER DEFAULT 0,
                PRIMARY KEY (chat_id, channel_id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS budgets (
                chat_id INTEGER,
                category TEXT,
                amount INTEGER,
                PRIMARY KEY (chat_id, category)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                amount INTEGER,
                category TEXT,
                note TEXT,
                day TEXT,
                ts REAL
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

def add_memory(text, category="boshqa", importance=2):
    now = time.time()
    with _conn() as c:
        c.execute(
            "INSERT INTO memories (text, category, importance, ts, updated) VALUES (?,?,?,?,?)",
            (text, category, importance, now, now),
        )


def list_memories():
    """Hamma faktlar: muhimlari va yangilari birinchi."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, text, category, importance FROM memories "
            "ORDER BY importance DESC, COALESCE(updated, ts) DESC"
        ).fetchall()
    return [
        {"id": r["id"], "text": r["text"], "category": r["category"] or "boshqa",
         "importance": r["importance"] or 2}
        for r in rows
    ]


def memory_exists(text):
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM memories WHERE lower(trim(text)) = lower(trim(?))", (text,)
        ).fetchone()
    return row is not None


def update_memory(mid, text, category=None, importance=None):
    with _conn() as c:
        c.execute(
            "UPDATE memories SET text=?, category=COALESCE(?, category), "
            "importance=COALESCE(?, importance), updated=? WHERE id=?",
            (text, category, importance, time.time(), mid),
        )


def delete_memory(mid):
    with _conn() as c:
        c.execute("DELETE FROM memories WHERE id=?", (mid,))


def history_after(chat_id, after_id):
    """after_id dan keyingi xabarlar (id bilan, eskisi birinchi)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, role, content FROM history WHERE chat_id=? AND id>? ORDER BY id",
            (chat_id, after_id),
        ).fetchall()
    return [{"id": r["id"], "role": r["role"], "content": r["content"] or ""} for r in rows]


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


# --- Guruh moderatsiyasi: ogohlantirishlar hisobi ---

def add_warn(chat_id, user_id):
    """Ogohlantirishni oshirib, yangi sonni qaytaradi."""
    with _conn() as c:
        c.execute(
            "INSERT INTO warns (chat_id, user_id, count) VALUES (?,?,1) "
            "ON CONFLICT(chat_id, user_id) DO UPDATE SET count = count + 1",
            (chat_id, user_id),
        )
        row = c.execute(
            "SELECT count FROM warns WHERE chat_id=? AND user_id=?",
            (chat_id, user_id),
        ).fetchone()
    return row["count"] if row else 1


def reset_warns(chat_id, user_id):
    with _conn() as c:
        c.execute(
            "DELETE FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id)
        )


# --- Sozlamalar (chat bo'yicha: avto-namoz, tonggi brifing va h.k.) ---

def set_setting(chat_id, key, value):
    with _conn() as c:
        c.execute(
            "INSERT INTO settings (chat_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT(chat_id, key) DO UPDATE SET value=excluded.value",
            (chat_id, key, str(value)),
        )


def get_setting(chat_id, key, default=None):
    with _conn() as c:
        row = c.execute(
            "SELECT value FROM settings WHERE chat_id=? AND key=?", (chat_id, key)
        ).fetchone()
    return row["value"] if row else default


def settings_where(key, value):
    """Berilgan key=value bo'lgan barcha chat_id'lar."""
    with _conn() as c:
        rows = c.execute(
            "SELECT chat_id FROM settings WHERE key=? AND value=?", (key, str(value))
        ).fetchall()
    return [r["chat_id"] for r in rows]


# --- Todo (vazifalar ro'yxati) ---

def add_todo(chat_id, text):
    with _conn() as c:
        c.execute(
            "INSERT INTO todos (chat_id, text, done, ts) VALUES (?,?,0,?)",
            (chat_id, text, time.time()),
        )


def list_todos(chat_id):
    with _conn() as c:
        rows = c.execute(
            "SELECT id, text FROM todos WHERE chat_id=? AND done=0 ORDER BY id",
            (chat_id,),
        ).fetchall()
    return [(r["id"], r["text"]) for r in rows]


def complete_todo(chat_id, number=None, text=None):
    """Vazifani bajarilgan deb belgilaydi (raqam yoki matn bo'yicha). Matnini qaytaradi."""
    todos = list_todos(chat_id)
    target = None
    if number is not None and 1 <= number <= len(todos):
        target = todos[number - 1]
    elif text:
        q = text.lower()
        target = next((t for t in todos if q in t[1].lower()), None)
    if not target:
        return None
    with _conn() as c:
        c.execute("UPDATE todos SET done=1 WHERE id=?", (target[0],))
    return target[1]


# --- Takroriy eslatmalar (har kuni/hafta) ---

def add_recurring(chat_id, text, hour, minute, dow=None):
    now = datetime.datetime.now()
    sched = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Bugungi vaqti o'tib ketgan bo'lsa — bugun qayta chiqmasin (ertaga boshlanadi).
    last = ""
    if now >= sched and (dow is None or dow == now.weekday()):
        last = now.strftime("%Y-%m-%d")
    with _conn() as c:
        c.execute(
            "INSERT INTO recurring (chat_id, text, hour, minute, dow, last_fired) "
            "VALUES (?,?,?,?,?,?)",
            (chat_id, text, hour, minute, dow, last),
        )


def list_recurring(chat_id):
    with _conn() as c:
        rows = c.execute(
            "SELECT id, text, hour, minute, dow FROM recurring WHERE chat_id=? ORDER BY id",
            (chat_id,),
        ).fetchall()
    return [(r["id"], r["text"], r["hour"], r["minute"], r["dow"]) for r in rows]


def cancel_recurring(chat_id, number):
    rows = list_recurring(chat_id)
    if not (1 <= number <= len(rows)):
        return None
    rid, text = rows[number - 1][0], rows[number - 1][1]
    with _conn() as c:
        c.execute("DELETE FROM recurring WHERE id=?", (rid,))
    return text


def due_recurring(now_dt=None):
    """Vaqti kelgan takroriy eslatmalarni qaytaradi va 'bugun yuborildi' deb belgilaydi."""
    now = now_dt or datetime.datetime.now()
    today = now.strftime("%Y-%m-%d")
    fired = []
    with _conn() as c:
        rows = c.execute(
            "SELECT id, chat_id, text, hour, minute, dow, last_fired FROM recurring"
        ).fetchall()
        for r in rows:
            if r["last_fired"] == today:
                continue
            if r["dow"] is not None and r["dow"] != now.weekday():
                continue
            sched = now.replace(
                hour=r["hour"], minute=r["minute"], second=0, microsecond=0
            )
            if now >= sched:
                fired.append((r["chat_id"], r["text"]))
                c.execute(
                    "UPDATE recurring SET last_fired=? WHERE id=?", (today, r["id"])
                )
    return fired


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


# --- Xarajatlar (so'mda) ---

def add_expense(chat_id, amount, category, note, day):
    """day = 'YYYY-MM-DD' (xarajat qilingan kun)."""
    with _conn() as c:
        c.execute(
            "INSERT INTO expenses (chat_id, amount, category, note, day, ts) "
            "VALUES (?,?,?,?,?,?)",
            (chat_id, amount, category, note, day, time.time()),
        )


def recent_expenses(chat_id, limit=10):
    """Oxirgi kiritilganlar (eng yangisi birinchi)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id, amount, category, note, day FROM expenses "
            "WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    return [(r["id"], r["amount"], r["category"], r["note"], r["day"]) for r in rows]


def delete_expense(chat_id, number):
    """recent_expenses ro'yxatidagi raqam bo'yicha o'chiradi (1 = eng oxirgisi)."""
    rows = recent_expenses(chat_id, limit=max(number, 1))
    if not (1 <= number <= len(rows)):
        return None
    row = rows[number - 1]
    with _conn() as c:
        c.execute("DELETE FROM expenses WHERE id=?", (row[0],))
    return row


def expenses_between(chat_id, start, end):
    """start..end (ikkalasi ham kiradi, 'YYYY-MM-DD') oralig'idagi xarajatlar."""
    with _conn() as c:
        rows = c.execute(
            "SELECT amount, category, note, day FROM expenses "
            "WHERE chat_id=? AND day BETWEEN ? AND ? ORDER BY day, id",
            (chat_id, start, end),
        ).fetchall()
    return [(r["amount"], r["category"], r["note"], r["day"]) for r in rows]


def status_counts(chat_id):
    """/status uchun bazadagi asosiy sonlar."""
    now = time.time()
    today = datetime.date.today().isoformat()
    with _conn() as c:
        one = lambda q, *a: c.execute(q, a).fetchone()[0]
        return {
            "memories": one("SELECT COUNT(*) FROM memories"),
            "reminders": one(
                "SELECT COUNT(*) FROM reminders WHERE chat_id=? AND sent=0 AND due_ts>?",
                chat_id, now,
            ),
            "recurring": one("SELECT COUNT(*) FROM recurring WHERE chat_id=?", chat_id),
            "todos": one("SELECT COUNT(*) FROM todos WHERE chat_id=? AND done=0", chat_id),
            "spent_today": one(
                "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE chat_id=? AND day=?",
                chat_id, today,
            ),
        }


# --- Dayjest kanallari ---

def add_digest_channel(chat_id, channel_id, title, username):
    """Qo'shadi; allaqachon bo'lsa False."""
    with _conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO digest_channels (chat_id, channel_id, title, username, last_id) "
            "VALUES (?,?,?,?,0)",
            (chat_id, channel_id, title, username),
        )
    return cur.rowcount > 0


def remove_digest_channel(chat_id, query):
    """Nomi/username qismi bo'yicha o'chiradi; o'chirilgan nomni qaytaradi."""
    q = query.lower().lstrip("@").strip()
    for ch in list_digest_channels(chat_id):
        if q == ch["username"].lower() or q in ch["title"].lower():
            with _conn() as c:
                c.execute(
                    "DELETE FROM digest_channels WHERE chat_id=? AND channel_id=?",
                    (chat_id, ch["channel_id"]),
                )
            return ch["title"]
    return None


def list_digest_channels(chat_id):
    with _conn() as c:
        rows = c.execute(
            "SELECT channel_id, title, username, last_id FROM digest_channels "
            "WHERE chat_id=? ORDER BY title",
            (chat_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def set_digest_last(chat_id, channel_id, last_id):
    with _conn() as c:
        c.execute(
            "UPDATE digest_channels SET last_id=? WHERE chat_id=? AND channel_id=?",
            (last_id, chat_id, channel_id),
        )


# --- Oylik budjet (category="jami" — umumiy) ---

def set_budget(chat_id, category, amount):
    with _conn() as c:
        if amount > 0:
            c.execute(
                "INSERT INTO budgets (chat_id, category, amount) VALUES (?,?,?) "
                "ON CONFLICT(chat_id, category) DO UPDATE SET amount=excluded.amount",
                (chat_id, category, amount),
            )
        else:
            c.execute(
                "DELETE FROM budgets WHERE chat_id=? AND category=?", (chat_id, category)
            )


def list_budgets(chat_id):
    """{category: amount}, 'jami' birinchi."""
    with _conn() as c:
        rows = c.execute(
            "SELECT category, amount FROM budgets WHERE chat_id=? "
            "ORDER BY category != 'jami', amount DESC",
            (chat_id,),
        ).fetchall()
    return {r["category"]: r["amount"] for r in rows}
