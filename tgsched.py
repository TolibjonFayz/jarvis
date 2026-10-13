"""Telegram rejalashtirilgan xabarlar — kompyuter o'chiq bo'lsa ham eslatmalar yetib boradi.

Bot faqat kompyuter yoniq paytda ishlaydi (ish kunlari ~09-18). Kechki/tungi va dam olish
kunidagi eslatmalar yo'qolardi (Liverpool o'yini, Chempionlar ligasi 00:00, shom/xufton).
Yechim: kelgusi xabarlarni egasining akkaunti (userbot) orqali «Saqlangan xabarlar»ga
REJALASHTIRIB qo'yamiz — vaqti kelganda Telegram serveri o'zi yuboradi.

- sync(): har 2 daqiqada «kerakli» ro'yxat (eslatmalar, takroriylar, namoz, yillik sanalar,
  Man City) bilan rejalashtirilganlarni tenglashtiradi: yangisini qo'shadi, bekor qilingan
  yoki o'zgarganini o'chiradi. FAQAT o'zi yaratgan xabarlarga tegadi.
- handoff(): bot yoniq bo'lsa, vaqtiga HANDOFF_SEC qolganda rejalashtirilganini o'chiradi —
  xabarni bot o'zi FRIDAY chatiga yuboradi (takror bo'lmaydi).
- claim(key): bot xabar yuborishdan oldin so'raydi. True = Telegram allaqachon yetkazgan
  (PC o'chiq edi) — bot qayta yubormaydi. Kelajakdagisi bo'lsa o'chirishga navbatga qo'yadi.

Holat settings'da (tg_sched): {kalit: {"id": xabar_id, "due": ts, "h": matn_hash}}.
"""
import datetime
import hashlib
import json
import logging
import threading
import time

import config
import memory

log = logging.getLogger("jarvis")

LEAD_SEC = 5 * 60          # bundan yaqinroq vaqtdagini rejalashtirmaymiz (bot o'zi yuboradi)
HANDOFF_SEC = 3 * 60       # bot yoniq: shuncha qolganda rejalashtirilgani o'chiriladi
MAX_ITEMS = 90             # Telegram: bir chatda 100 tagacha rejalashtirilgan xabar
PRAYER_DAYS = 3
RECURRING_DAYS = 3
DATE_DAYS = 60
FOOTBALL_DAYS = 7
STATE_KEY = "tg_sched"
DATE_HOUR = memory.DATE_HOUR

_lock = threading.Lock()
_pending_delete = []        # claim() navbati — handoff/sync o'chiradi
_prayer_cache = {}          # (shahar, sana) -> timings


def enabled(chat_id):
    return (memory.get_setting(chat_id, "tg_sched_on", "1") == "1"
            and bool(config.TG_API_ID and config.TG_API_HASH))


def _hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _load(chat_id):
    try:
        return json.loads(memory.get_setting(chat_id, STATE_KEY, "{}") or "{}")
    except ValueError:
        return {}


def _save(chat_id, state):
    memory.set_setting(chat_id, STATE_KEY, json.dumps(state))


def _ts(d, hour, minute=0):
    return datetime.datetime.combine(d, datetime.time(hour, minute)).timestamp()


# --- Kerakli xabarlar ---

def _prayers(chat_id, today, now):
    import tools
    if memory.get_setting(chat_id, "auto_prayer", "0") != "1":
        return []
    city = memory.get_setting(chat_id, "prayer_city", "Tashkent")
    out = []
    for i in range(PRAYER_DAYS):
        d = today + datetime.timedelta(days=i)
        key = (city, d.isoformat())
        if key not in _prayer_cache:
            try:
                _prayer_cache[key] = tools._prayer_times(city, d)
            except Exception as e:
                log.warning("Rejalashtirish: namoz vaqtlari olinmadi (%s): %s", d, str(e)[:80])
                continue
        timings = _prayer_cache[key]
        for eng, uz in tools.PRAYERS:
            h, m = map(int, timings[eng].split()[0].split(":"))
            out.append((f"pray:{d.isoformat()}:{uz}", _ts(d, h, m), f"⏰ Eslatma: {uz} namozi vaqti kirdi 🕌"))
    return out


def _football(chat_id, now_dt):
    if memory.get_setting(chat_id, "football", "0") != "1":
        return []
    import football
    try:
        ms = football.fixtures()
    except Exception as e:
        log.warning("Rejalashtirish: o'yinlar olinmadi: %s", str(e)[:80])
        return []
    out = []
    for m in ms:
        ko = m["kickoff"]
        if (ko - now_dt).total_seconds() > FOOTBALL_DAYS * 86400:
            continue
        day_at = football.day_alert_time(m)
        out.append((f"fb:{m['id']}:day", day_at.timestamp(), football.day_text(m, day_at.date())))
        out.append((f"fb:{m['id']}:pre", ko.timestamp() - football.PRE_MIN * 60,
                    football.pre_text(m, football.PRE_MIN)))
    return out


def desired(chat_id, now=None):
    """[(kalit, vaqt_ts, matn)] — vaqti bo'yicha, eng yaqin MAX_ITEMS tasi."""
    import tools
    now = now or time.time()
    now_dt = datetime.datetime.fromtimestamp(now)
    today = now_dt.date()
    items = []
    for rid, text, due in memory.pending_reminders_with_id(chat_id):
        if "namozi vaqti" in text:
            continue  # namozlar quyida — har kunlik jadvaldan
        items.append((f"rem:{rid}", due, f"⏰ Eslatma: {text}"))
    for rid, text, h, m, dow in memory.list_recurring(chat_id):
        for i in range(RECURRING_DAYS):
            d = today + datetime.timedelta(days=i)
            if dow is None or dow == d.weekday():
                items.append((f"rec:{rid}:{d.isoformat()}", _ts(d, h, m), f"🔔 Eslatma: {text}"))
    items += _prayers(chat_id, today, now)
    for did, text, _m, _d, year, occ in memory.list_dates(chat_id, today):
        if (occ - today).days > DATE_DAYS:
            continue
        eve = occ - datetime.timedelta(days=1)
        items.append((f"date:{did}:{occ.isoformat()}:eve", _ts(eve, DATE_HOUR),
                      tools.date_alert_text(text, year, occ, False)))
        items.append((f"date:{did}:{occ.isoformat()}:day", _ts(occ, DATE_HOUR),
                      tools.date_alert_text(text, year, occ, True)))
    items += _football(chat_id, now_dt.astimezone())
    items = sorted((it for it in items if it[1] > now + LEAD_SEC), key=lambda it: it[1])
    return items[:MAX_ITEMS]


# --- Tenglashtirish ---

def _flush_deletes():
    import userbot
    if not _pending_delete:
        return
    ids = list(_pending_delete)
    try:
        userbot.delete_scheduled(ids)
        del _pending_delete[:len(ids)]
    except Exception as e:
        log.warning("Rejalashtirilgan xabarlar o'chirilmadi: %s", str(e)[:100])


def sync(chat_id, now=None):
    """(qo'shildi, o'chirildi) soni."""
    import userbot
    if not enabled(chat_id):
        return 0, 0
    now = now or time.time()
    want = {k: (due, text) for k, due, text in desired(chat_id, now)}
    with _lock:
        state = _load(chat_id)
        removed = 0
        for key, ent in list(state.items()):
            if ent["due"] < now - 2 * 86400:
                del state[key]  # yetkazilgan, endi kerak emas
                continue
            if ent["due"] <= now:
                continue  # Telegram yetkazdi — bot claim() qilguncha saqlanadi
            w = want.get(key)
            if w is None or abs(w[0] - ent["due"]) > 30 or _hash(w[1]) != ent["h"]:
                _pending_delete.append(ent["id"])  # bekor qilindi yoki o'zgardi
                del state[key]
                removed += 1
        _flush_deletes()
        added = 0
        future = sum(1 for e in state.values() if e["due"] > now)
        for key, (due, text) in want.items():
            if key in state or future >= MAX_ITEMS:
                continue
            try:
                mid = userbot.schedule_saved(text, due)
            except Exception as e:
                log.warning("Rejalashtirib bo'lmadi (%s): %s", key, str(e)[:100])
                break  # tarmoq yo'q — keyingi sync'da
            if mid:
                state[key] = {"id": mid, "due": due, "h": _hash(text)}
                added += 1
                future += 1
        _save(chat_id, state)
    if added or removed:
        log.info("Telegram rejalashtirish: +%d, -%d (jami %d)", added, removed, future)
    return added, removed


def handoff(chat_id, now=None):
    """Bot yoniq: vaqtiga oz qolganlarni Telegram'dan olib, botga qoldiradi."""
    if not enabled(chat_id):
        return 0
    now = now or time.time()
    with _lock:
        state = _load(chat_id)
        near = [k for k, e in state.items() if now < e["due"] <= now + HANDOFF_SEC]
        for k in near:
            _pending_delete.append(state.pop(k)["id"])
        if near:
            _save(chat_id, state)
        _flush_deletes()
    return len(near)


def claim(chat_id, key, now=None):
    """Bot o'zi yuborishdan oldin. True — Telegram allaqachon yetkazgan, bot yubormasin."""
    now = now or time.time()
    with _lock:
        state = _load(chat_id)
        ent = state.pop(key, None)
        if ent is None:
            return False
        _save(chat_id, state)
        if ent["due"] <= now:
            return True
        _pending_delete.append(ent["id"])  # hali kelmagan — bot yuboradi, rejalashtirilgani o'chadi
        return False


def status_line(chat_id, now=None):
    now = now or time.time()
    n = sum(1 for e in _load(chat_id).values() if e["due"] > now)
    return f"📅 Telegram'da rejalashtirilgan: {n} ta (PC o'chiq bo'lsa ham keladi)" if enabled(chat_id) else ""
