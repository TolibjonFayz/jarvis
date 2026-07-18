"""Userbot: ustozning SHAXSIY Telegram akkaunti bilan ishlaydi (Telethon).

Telethon async — shuning uchun uni alohida fon oqimidagi (thread) o'z event
loop'ida ushlab turamiz. Tool'lar oddiy (sinxron) funksiyalar orqali chaqiradi.

Login: bir marta `python setup_userbot.py` (sessiya data/ ga saqlanadi).
"""
import os
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
