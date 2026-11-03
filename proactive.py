"""Proaktiv miya: FRIDAY o'zi gapiradi — faqat muhim narsa bo'lsa.

Kuniga bir necha slotda (SLOTS) egasining hamma ma'lumotini bitta joyga yig'adi
(kalendar, javobsiz chatlar, todo, eslatmalar, pul, loyihalar, Man City, sanalar) va
model "hozir aytishga arziydigan narsa bormi?" deb o'ylaydi. Yo'q bo'lsa — jim.

Shovqin bo'lmasligi uchun:
- kuniga MAX_PER_DAY dan ko'p emas, oxirgi 3 kunda aytilgani qayta aytilmaydi (kalit);
- egasi 🔕 bosgan tur (kind) boshqa aytilmaydi, 👍 bosganlari modelga "foydali" deb beriladi;
- birinchi SHADOW_DAYS kun sinov rejimi: faqat importance=3 yuboriladi, qolgani logga.
Har nomzod data/proactive.jsonl ga yoziladi (yuborilgan-yuborilmagani bilan) — keyin tahlil.

Maxfiylik: javobsiz chatlardan faqat ism + kutish vaqti ketadi, xabar matni YO'Q.
"""
import datetime
import json
import logging
import os
import re
import time

import config
import memory

log = logging.getLogger("jarvis")

SLOTS = [(10, 0), (13, 0), (16, 30), (18, 0)]
SLOT_GRACE_MIN = 120      # kompyuter kech yonsa — slotdan 2 soat ichida ishlaydi
MAX_PER_DAY = 3
SHADOW_DAYS = 7
REPEAT_DAYS = 3
KINDS = ["kalendar", "javobsiz", "vazifa", "eslatma", "pul", "loyiha", "futbol", "sana", "boshqa"]
LOG_PATH = os.path.join(config.DATA_DIR, "proactive.jsonl")

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


# --- Signallar ---

def _calendar(now):
    import gcal
    if not gcal.available():
        return []
    out = []
    for e in gcal.events_between(now.date(), 2):
        day = "bugun" if e["day"] == now.date() else "ertaga"
        if day == "bugun" and e["time"][:5] != "kun b" and e["time"][:5] < f"{now:%H:%M}":
            continue  # o'tib ketgan
        loc = f" ({e['location']})" if e["location"] else ""
        out.append(f"{day} {e['time']}: {e['title']}{loc}")
    return out


def _unanswered():
    import userbot
    items = userbot.unanswered(min_minutes=60, max_days=3) or []
    out = []
    for u in items[:8]:
        h = u["minutes"] // 60
        wait = f"{h // 24} kun" if h >= 24 else f"{h} soat"
        unread = f", {u['unread']} o'qilmagan" if u["unread"] else ""
        out.append(f"{u['name']}: {wait} javob kutyapti{unread}")
    return out


def _todos(chat_id, now):
    with memory._conn() as c:
        rows = c.execute(
            "SELECT text, ts FROM todos WHERE chat_id=? AND done=0 ORDER BY id", (chat_id,)
        ).fetchall()
    out = []
    for r in rows[:10]:
        age = int((now.timestamp() - (r["ts"] or now.timestamp())) // 86400)
        out.append(f"{r['text']} ({age} kundan beri ochiq)" if age else r["text"])
    return out


def _reminders(chat_id, now):
    end = now.timestamp() + 24 * 3600
    return [f"{datetime.datetime.fromtimestamp(due):%d.%m %H:%M} — {text}"
            for text, due in memory.list_pending_reminders(chat_id)
            if due < end and "namozi vaqti" not in text]


def _money(chat_id, now):
    import tools
    today = now.date()
    spent = tools._month_spent(chat_id, today)
    budgets = memory.list_budgets(chat_id)
    out = []
    import calendar
    days_in = calendar.monthrange(today.year, today.month)[1]
    month_pct = round(today.day * 100 / days_in)
    som = lambda n: f"{n:,}".replace(",", " ")
    for cat, limit in budgets.items():
        s = spent.get(cat, 0)
        out.append(f"budjet {cat}: {som(s)} / {som(limit)} so'm ({round(s * 100 / limit)}%; "
                   f"oyning {month_pct}% o'tdi)")
    week = sum(a for a, *_ in memory.expenses_between(
        chat_id, (today - datetime.timedelta(days=6)).isoformat(), today.isoformat()))
    prev = sum(a for a, *_ in memory.expenses_between(
        chat_id, (today - datetime.timedelta(days=13)).isoformat(),
        (today - datetime.timedelta(days=7)).isoformat()))
    if week or prev:
        out.append(f"oxirgi 7 kun xarajat: {som(week)} so'm, undan oldingi 7 kun: {som(prev)} so'm")
    return out


def _projects(now):
    import projects
    out = []
    for repo in projects.repos():
        try:
            week = projects._commits(repo, "7kun")
        except Exception:
            continue
        if not week:
            continue
        hours = int((now.timestamp() - max(c["ts"] for c in week)) // 3600)
        ago = f"{hours // 24} kun" if hours >= 24 else f"{hours} soat"
        today_n = sum(1 for c in week if c["ts"] >= now.replace(hour=0, minute=0).timestamp())
        out.append(f"{repo['name']}: 7 kunda {len(week)} commit, bugun {today_n}, "
                   f"oxirgisi {ago} oldin")
    return out[:10]


def _football(chat_id, now):
    if memory.get_setting(chat_id, "football", "0") != "1":
        return []
    import football
    out = []
    for m in football.fixtures():
        hours = (m["kickoff"] - now.astimezone()).total_seconds() / 3600
        if 0 < hours <= 36:
            out.append(f"{football.match_title(m)}: {m['kickoff'].astimezone():%d.%m %H:%M}")
    return out


def _dates(chat_id, now):
    today = now.date()
    return [f"{text}: {occ:%d.%m} ({(occ - today).days} kundan keyin)"
            for _id, text, _m, _d, _y, occ in memory.list_dates(chat_id, today)
            if (occ - today).days <= 7]


def gather(chat_id, now=None):
    """{tur: [qator]} — har manba alohida; biri yiqilsa qolganlari ishlaydi."""
    now = now or datetime.datetime.now()
    sources = {
        "kalendar": lambda: _calendar(now),
        "javobsiz": _unanswered,
        "vazifa": lambda: _todos(chat_id, now),
        "eslatma": lambda: _reminders(chat_id, now),
        "pul": lambda: _money(chat_id, now),
        "loyiha": lambda: _projects(now),
        "futbol": lambda: _football(chat_id, now),
        "sana": lambda: _dates(chat_id, now),
    }
    out = {}
    for kind, fn in sources.items():
        try:
            lines = fn()
        except Exception as e:
            log.info("Miya: %s signali olinmadi: %s", kind, str(e)[:80])
            continue
        if lines:
            out[kind] = lines
    return out


# --- Log va fikr-mulohaza ---

def _log_rows(days=REPEAT_DAYS):
    if not os.path.exists(LOG_PATH):
        return []
    since = time.time() - days * 86400
    rows = []
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("ts", 0) >= since:
                rows.append(r)
    return rows


def _append(row):
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def muted(chat_id):
    return [k for k in (memory.get_setting(chat_id, "proactive_mute", "") or "").split(",") if k]


def mute(chat_id, kind):
    kinds = muted(chat_id)
    if kind not in kinds:
        kinds.append(kind)
    memory.set_setting(chat_id, "proactive_mute", ",".join(kinds))


def unmute(chat_id):
    memory.set_setting(chat_id, "proactive_mute", "")


def like(chat_id, kind):
    n = int(memory.get_setting(chat_id, f"proactive_like_{kind}", "0") or 0)
    memory.set_setting(chat_id, f"proactive_like_{kind}", str(n + 1))


def liked(chat_id):
    return [k for k in KINDS if int(memory.get_setting(chat_id, f"proactive_like_{k}", "0") or 0)]


def shadow(chat_id, now=None):
    """Sinov rejimi (birinchi SHADOW_DAYS kun): faqat eng muhimlari yuboriladi."""
    now = now or time.time()
    since = float(memory.get_setting(chat_id, "proactive_since", "0") or 0)
    if not since:
        memory.set_setting(chat_id, "proactive_since", str(now))
        return True
    return now - since < SHADOW_DAYS * 86400


# --- Qaror ---

def _prompt(chat_id, signals, now, recent):
    lines = [f"Hozir: {now:%Y-%m-%d %H:%M}, {['dushanba', 'seshanba', 'chorshanba', 'payshanba', 'juma', 'shanba', 'yakshanba'][now.weekday()]}."]
    for kind, items in signals.items():
        lines.append(f"\n[{kind}]")
        lines += [f"- {x}" for x in items]
    if recent:
        lines.append("\nOxirgi kunlarda allaqachon aytilgan (QAYTARMA):")
        lines += [f"- {r['key']}: {r['text'][:120]}" for r in recent]
    if liked(chat_id):
        lines.append("\nEgang foydali deb belgilagan turlar: " + ", ".join(liked(chat_id)))
    return "\n".join(lines)


# Birinchi jonli sinovda (2026-11-03) "shaxmat'da 5 kun commit yo'q" (importance 3!) va
# "ovqat budjeti 0 — sarflashni boshla" degan — shovqin. Shuning uchun YOMON misollar aniq.
_SYSTEM = (
    "Sen FRIDAY'ning proaktiv miyasisan. Quyida egangning hozirgi holati. Vazifang: "
    "egang O'ZI so'ramasa ham HOZIR bilishi kerak bo'lgan narsa bormi — hal qil. "
    "Ko'p hollarda to'g'ri javob: hech narsa. Har nomzod uchun o'zingdan so'ra: "
    "'buni aytmasam egang aniq nima yo'qotadi?' — javob noaniq bo'lsa, TASHLA.\n"
    "YAXSHI (aytishga arziydi): odam 1 kundan ko'p javob kutyapti, ayniqsa u bilan "
    "yaqinda uchrashuv bo'lsa; budjet oyning o'tgan qismidan ancha tez sarflanyapti "
    "(masalan 80% sarflangan, oyning 40% o'tgan) yoki oshib ketgan; bugun/ertaga muddat "
    "bilan eslatma yoki vazifa; kechki o'yin + ertasi erta uchrashuv; ertaga tug'ilgan kun.\n"
    "YOMON (aytma): shaxsiy/hobbi loyihada commit yo'qligi (bu normal); xarajat 0 yoki kam "
    "(yaxshi narsa, yoki yozilmagan); odatiy kundalik odatlar (Duolingo kabi); kalendarni "
    "shunchaki takrorlash; maslahat/nasihat; 'ehtimol', 'balki' bilan boshlanadigan taxminlar.\n"
    "Faqat berilgan ma'lumotdan foydalan, raqam va ismni to'qima.\n"
    "Javob FAQAT JSON: {\"alerts\": [{\"kind\": tur, \"key\": qisqa barqaror kalit "
    "(masalan javobsiz:Aziz yoki pul:ovqat), \"importance\": 1-3, \"text\": o'zbekcha 1-2 gap, "
    "do'stona, 'bro' deb murojaat mumkin, aniq raqam/ism bilan}]}. importance 3 = bugun "
    "e'tibor bermasa aniq zarar (javob kutayotgan odam, muddat, budjet oshishi); 2 = foydali; "
    f"1 = qiziq xolos. tur: {', '.join(KINDS)}. Ko'pi bilan 2 ta. "
    "Hech narsa bo'lmasa {\"alerts\": []}."
)


def decide(chat_id, signals, now, recent):
    import agent
    if not signals:
        return []
    resp = agent._create(
        messages=[{"role": "system", "content": _SYSTEM},
                  {"role": "user", "content": _prompt(chat_id, signals, now, recent)}],
        # gpt-oss mulohazasi ham shu chegaraga kiradi: 900 da katta holatda "length" bilan
        # bo'sh javob qaytib, muhim signal jimgina yo'qolardi.
        max_tokens=2000,
    )
    choice = resp.choices[0]
    text = agent._clean(choice.message.content)
    m = _JSON_RE.search(text or "")
    if not m:
        log.info("Miya: JSON yo'q (finish=%s): %s", getattr(choice, "finish_reason", "?"),
                 (text or "")[:120])
        return []
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return []
    out = []
    for a in (data.get("alerts") or [])[:2]:
        if not isinstance(a, dict) or not (a.get("text") or "").strip():
            continue
        kind = a.get("kind") if a.get("kind") in KINDS else "boshqa"
        try:
            imp = max(1, min(3, int(a.get("importance", 2))))
        except (TypeError, ValueError):
            imp = 2
        out.append({"kind": kind, "key": str(a.get("key") or kind)[:60],
                    "importance": imp, "text": a["text"].strip()[:500]})
    return out


def run(chat_id, now=None, force=False):
    """Bir slot: nomzodlarni topadi, filtrlaydi, logga yozadi. Yuboriladiganlar ro'yxati.
    force=True (/miya hozir): kunlik chegara va sinov rejimi qo'llanmaydi."""
    now = now or datetime.datetime.now()
    signals = gather(chat_id, now)
    rows = _log_rows()
    recent = [r for r in rows if r.get("sent")]
    candidates = decide(chat_id, signals, now, recent)
    today_sent = sum(1 for r in recent
                     if datetime.datetime.fromtimestamp(r["ts"]).date() == now.date())
    sent_keys = {r["key"] for r in recent}
    is_shadow = shadow(chat_id, now.timestamp())
    blocked = set(muted(chat_id))
    out = []
    for a in candidates:
        why = ""
        if a["kind"] in blocked:
            why = "mute"
        elif a["key"] in sent_keys:
            why = "takror"
        elif not force and today_sent + len(out) >= MAX_PER_DAY:
            why = "kunlik_chegara"
        elif not force and is_shadow and a["importance"] < 3:
            why = "sinov_rejimi"
        row = dict(a, id=f"{int(now.timestamp())}{len(out)}", ts=now.timestamp(),
                   sent=not why, why=why)
        _append(row)
        if not why:
            out.append(row)
    log.info("Miya: %d signal turi, %d nomzod, %d yuboriladi",
             len(signals), len(candidates), len(out))
    return out


def due_slot(chat_id, now=None):
    """Hozir ishlash kerak bo'lgan slot kaliti (yoki None). Kaliti saqlanadi."""
    now = now or datetime.datetime.now()
    if memory.get_setting(chat_id, "proactive_on", "1") != "1":
        return None
    past = [datetime.datetime.combine(now.date(), datetime.time(h, m))
            for h, m in SLOTS if (h, m) <= (now.hour, now.minute)]
    if not past or (now - past[-1]).total_seconds() > SLOT_GRACE_MIN * 60:
        return None
    key = f"{past[-1]:%Y-%m-%d %H:%M}"
    if memory.get_setting(chat_id, "proactive_slot") == key:
        return None
    memory.set_setting(chat_id, "proactive_slot", key)
    return key


def find(alert_id):
    for r in _log_rows(days=30):
        if r.get("id") == alert_id:
            return r
    return None


def feedback(alert_id, value):
    _append({"fb": value, "id": alert_id, "ts": time.time()})


def status_text(chat_id):
    on = memory.get_setting(chat_id, "proactive_on", "1") == "1"
    rows = [r for r in _log_rows(days=1) if "key" in r
            and datetime.datetime.fromtimestamp(r["ts"]).date() == datetime.date.today()]
    lines = [f"🧠 **Proaktiv miya**: {'yoqilgan' if on else 'o‘chirilgan'}"
             + (" · sinov rejimi (faqat eng muhimlari)" if on and shadow(chat_id) else ""),
             "Slotlar: " + ", ".join(f"{h:02d}:{m:02d}" for h, m in SLOTS)
             + f" · kuniga ≤{MAX_PER_DAY} xabar"]
    if muted(chat_id):
        lines.append("🔕 Aytilmaydi: " + ", ".join(muted(chat_id)))
    if rows:
        lines.append("\nBugun o'ylaganlari:")
        for r in rows:
            mark = "📨" if r["sent"] else f"🤐 ({r['why']})"
            lines.append(f"{mark} [{r['kind']}] {r['text']}")
    else:
        lines.append("\nBugun hali hech narsa aytmadi.")
    lines.append("\n/miya hozir — hozir o'ylab ko'rsin · /miya off|on · /miya unmute")
    return "\n".join(lines)
