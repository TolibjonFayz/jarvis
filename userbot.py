"""Userbot: ustozning SHAXSIY Telegram akkaunti bilan ishlaydi (Telethon).

Telethon async — shuning uchun uni alohida fon oqimidagi (thread) o'z event
loop'ida ushlab turamiz. Tool'lar oddiy (sinxron) funksiyalar orqali chaqiradi.

Login: bir marta `python setup_userbot.py` (sessiya data/ ga saqlanadi).
"""
import os
import re
import asyncio
import threading

import config

SESSION = os.path.join(config.DATA_DIR, "userbot")

NOT_READY = (
    "Userbot hali ulanmagan. Qilish kerak:\n"
    "1) my.telegram.org dan API_ID/API_HASH olib .env ga yozing\n"
    "2) Terminalda: python setup_userbot.py (telefon raqam + kod)\n"
    "3) Botni qayta ishga tushiring"
)

_loop = None
_client = None
_lock = threading.Lock()


def _ensure_started():
    """Fon oqimida Telethon klientni (bir marta) ishga tushiradi."""
    global _loop, _client
    with _lock:
        if _client is not None:
            return True
        if not (config.TG_API_ID and config.TG_API_HASH):
            return False

        from telethon import TelegramClient
        from telethon.sessions import StringSession

        # Server: env'dagi STRING sessiya; lokal: fayl sessiyasi.
        if config.TG_SESSION:
            session = StringSession(config.TG_SESSION)
        elif os.path.exists(SESSION + ".session"):
            session = SESSION
        else:
            return False

        _loop = asyncio.new_event_loop()
        threading.Thread(target=_loop.run_forever, daemon=True).start()

        async def _make():
            c = TelegramClient(session, config.TG_API_ID, config.TG_API_HASH)
            await c.connect()
            if not await c.is_user_authorized():
                await c.disconnect()
                return None
            return c

        fut = asyncio.run_coroutine_threadsafe(_make(), _loop)
        _client = fut.result(30)
        return _client is not None


def _run(coro, timeout=60):
    """Coroutine'ni userbot loop'ida bajarib, natijasini qaytaradi."""
    fut = asyncio.run_coroutine_threadsafe(coro, _loop)
    return fut.result(timeout)


# --- Tool'lar chaqiradigan sinxron funksiyalar ---

def list_chats(limit=10):
    """Oxirgi suhbatlar ro'yxati (o'qilmaganlar soni bilan)."""
    if not _ensure_started():
        return NOT_READY

    async def go():
        lines = []
        async for d in _client.iter_dialogs(limit=limit):
            unread = f"  [{d.unread_count} o'qilmagan]" if d.unread_count else ""
            kind = "guruh" if d.is_group else ("kanal" if d.is_channel else "shaxsiy")
            lines.append(f"- {d.name} ({kind}){unread}")
        return "\n".join(lines) or "Suhbatlar topilmadi."

    return _run(go())


async def _find_dialog(query):
    """Suhbatni nomi bo'yicha qidiradi (katta-kichik farqsiz, qisman mos)."""
    q = query.lower().lstrip("@")
    async for d in _client.iter_dialogs(limit=150):
        name = (d.name or "").lower()
        uname = (getattr(d.entity, "username", None) or "").lower()
        if q in name or q == uname:
            return d
    return None


def resolve_chat(query):
    """Suhbatni topib (id, nom) qaytaradi, topilmasa None."""
    if not _ensure_started():
        return None

    async def go():
        d = await _find_dialog(query)
        return (d.id, d.name) if d else None

    return _run(go())


def read_messages(query, limit=10):
    """Suhbatdan oxirgi xabarlarni o'qiydi (eskidan yangiga)."""
    if not _ensure_started():
        return NOT_READY

    async def go():
        d = await _find_dialog(query)
        if d is None:
            return f"'{query}' nomli suhbat topilmadi. tg_chats bilan ro'yxatni ko'r."
        lines = []
        async for m in _client.iter_messages(d.entity, limit=limit):
            if m.out:
                who = "Men"
            else:
                try:
                    s = await m.get_sender()
                    who = (
                        getattr(s, "first_name", None)
                        or getattr(s, "title", None)
                        or "?"
                    )
                except Exception:
                    who = "?"
            text = (m.text or "(media/fayl)").strip()
            when = m.date.strftime("%d.%m %H:%M") if m.date else ""
            lines.append(f"[{when}] {who}: {text[:300]}")
        lines.reverse()
        return f"'{d.name}' — oxirgi {len(lines)} xabar:\n" + "\n".join(lines)

    return _run(go())


def send_message(chat_id, text):
    """Xabar yuboradi (faqat tasdiqdan keyin chaqiriladi — tools.py boshqaradi)."""
    if not _ensure_started():
        return NOT_READY

    async def go():
        entity = await _client.get_entity(chat_id)
        await _client.send_message(entity, text)
        name = getattr(entity, "first_name", None) or getattr(entity, "title", "")
        return f"Yuborildi -> {name}: \"{text}\""

    return _run(go())


def download_media(chat_id, message_id, dest):
    """Guruhdagi xabar mediasini faylga yuklaydi (botdan farqli — 2GBgача).
    Muvaffaqiyatda fayl yo'lini, aks holda None qaytaradi."""
    if not _ensure_started():
        return None

    async def go():
        try:
            msg = await _client.get_messages(int(chat_id), ids=int(message_id))
        except Exception:
            msg = None
        if not msg or not getattr(msg, "media", None):
            return None
        # Tez yo'l: katta bo'laklar (512KB) -> kamroq so'rov -> tezroq yuklash.
        try:
            with open(dest, "wb") as f:
                async for chunk in _client.iter_download(msg, request_size=512 * 1024):
                    f.write(chunk)
            return dest
        except Exception:
            # Zaxira: oddiy usul (tez yo'l ishlamasa).
            return await _client.download_media(msg, file=dest)

    try:
        return _run(go(), timeout=300)
    except Exception:
        return None


# --- Dayjest (kanallar) va javobsiz xabarlar ---

def _is_broadcast(d):
    return bool(d.is_channel and not d.is_group)


def list_channels(limit=300):
    """Obuna bo'lingan kanallar: [{id, title, username}]."""
    if not _ensure_started():
        return None

    async def go():
        out = []
        async for d in _client.iter_dialogs(limit=limit):
            if _is_broadcast(d):
                out.append({
                    "id": d.id,
                    "title": d.name or "",
                    "username": getattr(d.entity, "username", None) or "",
                })
        return out

    return _run(go())


def find_channel(query):
    """Kanalni nomi yoki @username bo'yicha topadi (faqat kanallar)."""
    chans = list_channels()
    if chans is None:
        return None
    q = query.lower().lstrip("@").strip()
    for c in chans:
        if q == c["username"].lower():
            return c
    for c in chans:
        if q in c["title"].lower():
            return c
    return {}


def fetch_posts(channel_id, after_id=0, limit=40, since_hours=24):
    """after_id dan keyingi postlar (eskidan yangiga). after_id=0 bo'lsa —
    faqat oxirgi since_hours soatdagilari (birinchi dayjest butun tarixni olmasin)."""
    if not _ensure_started():
        return None
    import datetime as _dt

    async def go():
        entity = await _client.get_entity(channel_id)
        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=since_hours)
        posts = []
        async for m in _client.iter_messages(entity, min_id=after_id, limit=limit):
            if not after_id and m.date and m.date < cutoff:
                break
            text = (m.text or "").strip()
            if text:
                posts.append({"id": m.id, "text": text, "views": m.views or 0})
        posts.reverse()
        return posts

    return _run(go(), timeout=120)


_ACK_WORDS = {
    "ok", "okey", "ок", "rahmat", "raxmat", "rahmat!", "spasibo", "спасибо", "xop", "xo'p",
    "хоп", "ha", "да", "mayli", "tushundim", "yaxshi", "zo'r", "super", "+", "👍", "🙏", "❤️",
}


_ACK_RE = re.compile(
    r"^(rahmat|raxmat|spasibo|спасибо|ok+|okey|xa+|ha+|xo'?p|mayli|tushundim|zo'r)\b|^(👍|🙏)"
)


def _needs_no_reply(m):
    """'rahmat', 'ok', 👍, stiker — javob kutmaydi."""
    if getattr(m, "sticker", None):
        return True
    text = (m.text or "").strip().lower().rstrip("!.) ")
    if not text:
        return False  # rasm/fayl/ovoz — javob kerak bo'lishi mumkin
    if text in _ACK_WORDS or (len(text) <= 2 and not text.isalnum()):
        return True
    # "Rahmat aytganiz kelsin", "xaa", "okk" — qisqa minnatdorchilik/rozilik
    return len(text) <= 40 and "?" not in text and bool(_ACK_RE.search(text))


def unanswered(min_hours=3, max_days=3, limit=200):
    """Shaxsiy chatlarda oxirgi xabar SENDAN EMAS va min_hours dan ko'p kutgan.
    Botlar, Telegram xizmati, "Saqlanganlar" va ovozi o'chirilgan chatlar hisobga olinmaydi.
    Xabar matni hech qayerga yuborilmaydi — faqat egasiga ro'yxat."""
    if not _ensure_started():
        return None
    import datetime as _dt

    async def go():
        now = _dt.datetime.now(_dt.timezone.utc)
        out = []
        async for d in _client.iter_dialogs(limit=limit):
            if not d.is_user:
                continue
            e = d.entity
            if getattr(e, "bot", False) or getattr(e, "is_self", False) or d.id == 777000:
                continue
            mute = getattr(getattr(d.dialog, "notify_settings", None), "mute_until", None)
            if mute and mute > now:
                continue
            m = d.message
            if m is None or m.out or not m.date:
                continue
            if _needs_no_reply(m):
                continue
            age = now - m.date
            if age < _dt.timedelta(hours=min_hours) or age > _dt.timedelta(days=max_days):
                continue
            out.append({
                "id": d.id,
                "name": d.name or "?",
                "hours": int(age.total_seconds() // 3600),
                "unread": d.unread_count,
                "preview": (m.text or "(media/fayl)").strip().replace("\n", " ")[:60],
            })
        out.sort(key=lambda x: -x["hours"])
        return out

    return _run(go(), timeout=120)
