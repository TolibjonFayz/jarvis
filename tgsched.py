"""PC o'chiq bo'lsa ham eslatmalar FRIDAY BOTI nomidan keladi — Cloudflare relay orqali.

Bot faqat kompyuter yoniq paytda ishlaydi (ish kunlari ~09-18). Kechki/tungi va dam olish
kunidagi eslatmalar yo'qolardi (Liverpool o'yini, Chempionlar ligasi 00:00, shom/xufton).
Telegram botlarga xabar rejalashtirishga ruxsat bermaydi; «Saqlangan xabarlar»ga
rejalashtirish egasiga yoqmadi ("menga shu bot yuborsin"). Shuning uchun:

- sync(): bot yoniq paytda har daqiqada kelgusi xabarlar ro'yxatini (eslatmalar,
  takroriylar, namoz, yillik sanalar, Man City) relay'ga yuboradi — faqat o'zgarganda.
  Vaqtiga HANDOFF_SEC dan kam qolganlari ro'yxatga KIRMAYDI: ularni bot o'zi yuboradi.
- relay (relay/src/index.js, Cloudflare Worker, cron har daqiqa) vaqti kelganini Bot API
  orqali yuboradi — ya'ni kompyuter o'chib qolsa, ro'yxatdagilar baribir keladi.
- claim(key): bot xabar yuborishdan oldin so'raydi. True = relay allaqachon yuborgan
  (PC o'chiq edi) — bot qayta yubormaydi. Kesh refresh_sent() bilan yangilanadi.
"""
import datetime
import hashlib
import json
import logging
import time
import urllib.request

import config
import memory
import net

log = logging.getLogger("jarvis")

HANDOFF_SEC = 3 * 60       # bundan yaqinini bot o'zi yuboradi (sync har daqiqada)
MAX_ITEMS = 250
PRAYER_DAYS = 3
RECURRING_DAYS = 3
DATE_DAYS = 60
FOOTBALL_DAYS = 7
REPUSH_SEC = 30 * 60       # o'zgarmasa ham shuncha vaqtda bir marta (relay holati tiklansin)
SENT_TTL = 60
DATE_HOUR = memory.DATE_HOUR

_prayer_cache = {}          # (shahar, sana) -> timings
_sent_cache = {"ts": 0.0, "keys": set()}


def configured():
    return bool(config.RELAY_URL and config.RELAY_KEY)


def enabled(chat_id):
    return (configured() and str(chat_id) == str(config.OWNER_ID)
            and memory.get_setting(chat_id, "tg_sched_on", "1") == "1")


def _request(method, path, body=None, timeout=15):
    net.prefer_ipv4()
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        config.RELAY_URL + path, data=data, method=method,
        headers={"x-friday-key": config.RELAY_KEY, "content-type": "application/json",
                 "user-agent": "FRIDAY"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _ts(d, hour, minute=0):
    return datetime.datetime.combine(d, datetime.time(hour, minute)).timestamp()


# --- Kerakli xabarlar ---

def _prayers(chat_id, today):
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
                log.warning("Relay: namoz vaqtlari olinmadi (%s): %s", d, str(e)[:80])
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
        log.warning("Relay: o'yinlar olinmadi: %s", str(e)[:80])
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
    """[(kalit, vaqt_ts, matn)] — HANDOFF dan keyingilari, vaqti bo'yicha."""
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
    items += _prayers(chat_id, today)
    for did, text, _m, _d, year, occ in memory.list_dates(chat_id, today):
        if (occ - today).days > DATE_DAYS:
            continue
        eve = occ - datetime.timedelta(days=1)
        items.append((f"date:{did}:{occ.isoformat()}:eve", _ts(eve, DATE_HOUR),
                      tools.date_alert_text(text, year, occ, False)))
        items.append((f"date:{did}:{occ.isoformat()}:day", _ts(occ, DATE_HOUR),
                      tools.date_alert_text(text, year, occ, True)))
    items += _football(chat_id, now_dt.astimezone())
    items = sorted((it for it in items if it[1] > now + HANDOFF_SEC), key=lambda it: it[1])
    return items[:MAX_ITEMS]


def sync(chat_id, now=None):
    """Ro'yxatni relay'ga yuboradi (o'zgargan bo'lsa). Yuborilgan xabarlar soni yoki None."""
    import fmt
    if not enabled(chat_id):
        return None
    now = now or time.time()
    items = [{"key": k, "due": round(due), "text": fmt.to_html(text)} for k, due, text in desired(chat_id, now)]
    digest = hashlib.sha1(json.dumps(items, sort_keys=True).encode("utf-8")).hexdigest()
    last_ts = float(memory.get_setting(chat_id, "relay_push_ts", "0") or 0)
    if digest == memory.get_setting(chat_id, "relay_hash", "") and now - last_ts < REPUSH_SEC:
        return None
    res = _request("PUT", "/alerts", {"items": items})
    memory.set_setting(chat_id, "relay_hash", digest)
    memory.set_setting(chat_id, "relay_push_ts", str(now))
    memory.set_setting(chat_id, "relay_count", str(res.get("items", len(items))))
    return res.get("items", len(items))


def clear(chat_id):
    """Relay navbatini bo'shatadi (o'chirilganda)."""
    if configured():
        _request("PUT", "/alerts", {"items": []})
    memory.set_setting(chat_id, "relay_hash", "")
    memory.set_setting(chat_id, "relay_count", "0")


def refresh_sent(force=False):
    """Relay yuborgan kalitlar keshini yangilaydi (bot oqimidan tashqarida chaqiriladi)."""
    if not configured() or (not force and time.time() - _sent_cache["ts"] < SENT_TTL):
        return
    try:
        _sent_cache["keys"] = set(_request("GET", "/sent", timeout=10).get("sent", {}))
        _sent_cache["ts"] = time.time()
    except Exception as e:
        log.warning("Relay /sent o'qilmadi: %s", str(e)[:100])


def claim(chat_id, key):
    """Bot o'zi yuborishdan oldin. True — relay allaqachon yuborgan, bot yubormasin."""
    return enabled(chat_id) and key in _sent_cache["keys"]


def status_line(chat_id):
    if not enabled(chat_id):
        return ""
    n = memory.get_setting(chat_id, "relay_count", "0")
    return f"📡 Relay navbatida: {n} ta xabar (PC o'chiq bo'lsa ham bot yuboradi)"
