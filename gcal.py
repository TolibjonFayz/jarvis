"""Google Calendar: tadbirlarni ko'rish va qo'shish (egasining asosiy kalendari).

Sozlash (bir marta): data/google_client.json (OAuth Desktop client) +
`python setup_gcal.py` -> data/google_token.json. Ruxsat faqat
calendar.events — kalendar sozlamalari va boshqa Google ma'lumotlariga tegmaydi.
O'chirish faqat TUGMA bilan tasdiqlangandan keyin (bot.on_button) — chatdagi
noto'g'ri tushunish tadbirni yo'qotmasin. Tahrirlash yo'q.
"""
import datetime
import logging
import os

import config
import net

log = logging.getLogger("jarvis.gcal")

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CLIENT_FILE = os.path.join(config.DATA_DIR, "google_client.json")
TOKEN_FILE = os.path.join(config.DATA_DIR, "google_token.json")
TZ = "Asia/Tashkent"
_TZINFO = datetime.timezone(datetime.timedelta(hours=config.TZ_OFFSET))

NOT_READY = (
    "Google Calendar hali ulanmagan. GCAL_SETUP.md dagi qadamlarni bajarib, "
    "`python setup_gcal.py` ni ishga tushir."
)

net.prefer_ipv4()
_service = None


def available():
    return os.path.exists(TOKEN_FILE)


def _svc():
    """Calendar servisi; token eskirgan bo'lsa yangilab, faylga qayta yozadi."""
    global _service
    if _service is not None:
        return _service
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _service


def _range(period, date=None):
    today = datetime.datetime.now(_TZINFO).date()
    if date:
        start = resolve_date(date)
        end = start + datetime.timedelta(days=1)
    elif period == "ertaga":
        start = today + datetime.timedelta(days=1)
        end = start + datetime.timedelta(days=1)
    elif period == "hafta":
        start, end = today, today + datetime.timedelta(days=7)
    else:  # bugun
        start, end = today, today + datetime.timedelta(days=1)
    as_dt = lambda d: datetime.datetime.combine(d, datetime.time(), _TZINFO).isoformat()
    return as_dt(start), as_dt(end), start, end


_DAYS = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
_WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]


def resolve_date(text):
    """'2026-09-25' | 'bugun' | 'ertaga' | 'indinga' | 'juma' | 'kelasi juma' -> date.

    Model "juma kuni" ni sanaga o'zi aylantirganda adashardi (chorshanbadan
    jumani 27.09 — yakshanba deb yozdi), shuning uchun nisbiy sanani kod hisoblaydi.
    """
    s = (text or "").strip().lower().replace("‘", "'").replace("’", "'")
    today = datetime.datetime.now(_TZINFO).date()
    try:
        return datetime.date.fromisoformat(s[:10])
    except ValueError:
        pass
    if not s or s.startswith("bugun"):
        return today
    if s.startswith("ertaga"):
        return today + datetime.timedelta(days=1)
    if s.startswith(("indin", "ertadan keyin")):
        return today + datetime.timedelta(days=2)
    for i, name in enumerate(_WEEKDAYS):
        if name in s and not (name == "shanba" and ("yakshanba" in s or "dushanba" in s
                                                    or "seshanba" in s or "chorshanba" in s
                                                    or "payshanba" in s)):
            ahead = (i - today.weekday()) % 7
            if any(w in s for w in ("kelasi", "keyingi", "kelgusi")):
                ahead += 7
            return today + datetime.timedelta(days=ahead)
    raise ValueError(f"sanani tushunmadim: {text}")


def events(period="bugun", date=None, limit=30):
    """[{day, time, title, location}] — ko'rinish uchun tayyor."""
    t_min, t_max, _s, _e = _range(period, date)
    resp = _svc().events().list(
        calendarId="primary", timeMin=t_min, timeMax=t_max, singleEvents=True,
        orderBy="startTime", maxResults=limit, timeZone=TZ,
    ).execute()
    out = []
    for ev in resp.get("items", []):
        st, en = ev.get("start", {}), ev.get("end", {})
        if "dateTime" in st:
            s = datetime.datetime.fromisoformat(st["dateTime"]).astimezone(_TZINFO)
            e = datetime.datetime.fromisoformat(en["dateTime"]).astimezone(_TZINFO)
            day, time_ = s.date(), f"{s:%H:%M}–{e:%H:%M}"
        else:
            day, time_ = datetime.date.fromisoformat(st["date"]), "kun bo'yi"
        out.append({
            "day": day, "time": time_,
            "title": ev.get("summary") or "(nomsiz)",
            "location": ev.get("location") or "",
        })
    return out


def events_text(period="bugun", date=None):
    if not available():
        return NOT_READY
    items = events(period, date)
    _tmin, _tmax, start, end = _range(period, date)
    label = (
        f"{start:%d.%m}" if date else
        {"bugun": "Bugun", "ertaga": "Ertaga", "hafta": "7 kun"}.get(period, "Bugun")
    )
    if not items:
        return f"📅 {label}: tadbir yo'q."
    out = [f"📅 **{label}** — {len(items)} ta tadbir"]
    multi_day = (end - start).days > 1
    for it in items:
        day = f"{_DAYS[it['day'].weekday()]} {it['day']:%d.%m} · " if multi_day else ""
        loc = f" · 📍 {it['location'][:40]}" if it["location"] else ""
        out.append(f"• {day}{it['time']} — **{it['title']}**{loc}")
    return "\n".join(out)


def add_event(title, date, time=None, duration_min=60, location="", description=""):
    """Tadbir qo'shadi. time=None — kun bo'yi. Tasdiq matnini qaytaradi."""
    if not available():
        return NOT_READY
    try:
        day = resolve_date(date)
    except ValueError as e:
        return f"❌ {e}. Sanani YYYY-MM-DD yoki 'ertaga', 'juma' kabi yoz."
    # "12-mart" — model yilni goh joriy, goh keyingi deb yozadi. Yangi tadbir
    # o'tmishda bo'lishi deyarli yo'q: o'tib ketgan sana -> keyingi yil.
    rolled = ""
    today = datetime.datetime.now(_TZINFO).date()
    if day < today:
        try:
            day = day.replace(year=today.year if day.replace(year=today.year) >= today else today.year + 1)
        except ValueError:  # 29-fevral
            day = day.replace(year=today.year + 1, day=28)
        rolled = " (sana o'tib ketgan edi — keyingi yilga qo'yildi)"
    this_year = day.year == datetime.datetime.now(_TZINFO).year
    dm = f"{day:%d.%m}" if this_year else f"{day:%d.%m.%Y}"
    body = {"summary": title.strip()[:200]}
    if location:
        body["location"] = location[:200]
    if description:
        body["description"] = description[:1000]
    if time:
        hh, mm = (int(x) for x in time.split(":")[:2])
        start = datetime.datetime.combine(day, datetime.time(hh, mm), _TZINFO)
        end = start + datetime.timedelta(minutes=max(int(duration_min or 60), 5))
        body["start"] = {"dateTime": start.isoformat(), "timeZone": TZ}
        body["end"] = {"dateTime": end.isoformat(), "timeZone": TZ}
        when = f"{_DAYS[day.weekday()]} {dm}, {start:%H:%M}–{end:%H:%M}"
    else:
        body["start"] = {"date": day.isoformat()}
        body["end"] = {"date": (day + datetime.timedelta(days=1)).isoformat()}
        when = f"{_DAYS[day.weekday()]} {dm}, kun bo'yi"
    ev = _svc().events().insert(calendarId="primary", body=body).execute()
    link = ev.get("htmlLink", "")
    return f"📅 Kalendarga qo'shildi: **{body['summary']}** — {when}{rolled}" + (
        f" [↗]({link})" if link else ""
    )


def find_events(title="", date=None, days=60):
    """Nomi (qism) va/yoki sana bo'yicha kelgusi tadbirlar: [{id, title, when}]."""
    today = datetime.datetime.now(_TZINFO).date()
    if date:
        start = resolve_date(date)
        end = start + datetime.timedelta(days=1)
    else:
        start, end = today, today + datetime.timedelta(days=days)
    as_dt = lambda d: datetime.datetime.combine(d, datetime.time(), _TZINFO).isoformat()
    resp = _svc().events().list(
        calendarId="primary", timeMin=as_dt(start), timeMax=as_dt(end), singleEvents=True,
        orderBy="startTime", maxResults=100, timeZone=TZ,
    ).execute()
    q = (title or "").lower().strip()
    out = []
    for ev in resp.get("items", []):
        name = ev.get("summary") or "(nomsiz)"
        if q and q not in name.lower():
            continue
        st = ev.get("start", {})
        if "dateTime" in st:
            s = datetime.datetime.fromisoformat(st["dateTime"]).astimezone(_TZINFO)
            when = f"{_DAYS[s.weekday()]} {s:%d.%m %H:%M}"
        else:
            d = datetime.date.fromisoformat(st["date"])
            when = f"{_DAYS[d.weekday()]} {d:%d.%m}, kun bo'yi"
        out.append({"id": ev["id"], "title": name, "when": when})
    return out


def delete_event(event_id):
    """Faqat tugma bilan tasdiqlangandan keyin chaqiriladi."""
    _svc().events().delete(calendarId="primary", eventId=event_id).execute()
    return True


def brief_line():
    """Brifing uchun bugungi tadbirlar (ulanmagan yoki bo'sh bo'lsa '')."""
    if not available():
        return ""
    items = events("bugun")
    if not items:
        return ""
    return "📅 Bugun:\n" + "\n".join(f"  • {it['time']} — {it['title']}" for it in items[:8])
