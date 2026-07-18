"""Agent qo'llari (tool'lar): fayl, buyruq, xotira, qidiruv, ob-havo, eslatma.
Ta'riflar token tejash uchun ataylab qisqa — nom o'zi tushunarli."""
import os
import re
import json
import time
import datetime
import subprocess
import urllib.request
import urllib.parse

from config import WORKSPACE, READ_ROOT, BRIEF_HOUR
import memory

# Qisqa tool ta'riflari (token tejash uchun).
TOOLS = [
    {
        "name": "read_file",
        "description": "Fayl o'qish. To'liq yo'l ham bo'ladi (D:\\Tolibjon ichida), nisbiy=workspace",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Fayl yozish/yaratish (FAQAT workspace ichida)",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "Papka tarkibi. To'liq yo'l ham bo'ladi (D:\\Tolibjon ichida), nisbiy=workspace",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "run_command",
        "description": "Shell buyruq bajarish (workspace)",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "remember",
        "description": "Muhim faktni xotiraga saqlash",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "recall",
        "description": "Xotiradan qidirish",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "web_search",
        "description": "Internetdan qidirish (dolzarb ma'lumot/yangilik)",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "read_url",
        "description": "Havolani (URL) ochib, sahifaning asosiy matnini o'qiydi. Maqola/sahifani o'qish yoki xulosa qilish uchun.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "get_weather",
        "description": "Ob-havo + 3 kunlik prognoz (shahar nomi)",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
    {
        "name": "set_reminder",
        "description": "Eslatma qo'yish. minutes=hozirdan necha daqiqa keyin",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "minutes": {"type": "number"}},
            "required": ["text", "minutes"],
        },
    },
    {
        "name": "list_reminders",
        "description": "Kutilayotgan eslatmalar ro'yxati",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_prayer_reminders",
        "description": "Namoz vaqtlariga eslatma qo'yadi (5 vaqt). days_ahead: 0=bugun, 1=ertaga",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "days_ahead": {"type": "number"},
            },
            "required": ["city"],
        },
    },
    {
        "name": "set_daily_prayers",
        "description": "Har kunga namoz eslatmalarini AVTOMATIK qo'yishni yoqadi/o'chiradi. on=true yoqadi",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "on": {"type": "boolean"},
            },
            "required": ["on"],
        },
    },
    {
        "name": "get_currency",
        "description": "Valyuta kursini beradi (Markaziy bank, so'mda). Masalan: USD, EUR, RUB",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "set_morning_brief",
        "description": "Har ertalab tonggi brifing (ob-havo+namoz+kurs+eslatmalar) yuborishni yoqadi/o'chiradi. on=true yoqadi",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "on": {"type": "boolean"},
            },
            "required": ["on"],
        },
    },
    {
        "name": "set_recurring_reminder",
        "description": (
            "TAKRORIY eslatma qo'yadi (har kuni yoki haftaning kunida). "
            "hour 0-23, minute 0-59. weekday: 0=Dushanba...6=Yakshanba; har kuni bo'lsa berilmaydi."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "hour": {"type": "number"},
                "minute": {"type": "number"},
                "weekday": {"type": "number"},
            },
            "required": ["text", "hour"],
        },
    },
    {
        "name": "list_recurring",
        "description": "Takroriy eslatmalar ro'yxatini beradi (raqamli).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "cancel_recurring",
        "description": "Takroriy eslatmani raqami bo'yicha o'chiradi (list_recurring dagi raqam).",
        "input_schema": {
            "type": "object",
            "properties": {"number": {"type": "number"}},
            "required": ["number"],
        },
    },
    {
        "name": "add_todo",
        "description": "Vazifalar ro'yxatiga (todo) yangi vazifa qo'shadi.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "list_todos",
        "description": "Vazifalar ro'yxatini (todo) beradi.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "complete_todo",
        "description": "Vazifani bajarilgan deb belgilaydi. number=ro'yxatdagi raqam yoki text=vazifa matni",
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {"type": "number"},
                "text": {"type": "string"},
            },
            "required": [],
        },
    },
    {
        "name": "tg_chats",
        "description": "Shaxsiy Telegram: oxirgi suhbatlar ro'yxati",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "number"}},
            "required": [],
        },
    },
    {
        "name": "tg_read",
        "description": "Shaxsiy Telegram: suhbatdan oxirgi xabarlarni o'qish. chat=ism yoki @username",
        "input_schema": {
            "type": "object",
            "properties": {"chat": {"type": "string"}, "limit": {"type": "number"}},
            "required": ["chat"],
        },
    },
    {
        "name": "tg_send",
        "description": "Shaxsiy Telegram: xabarni yuborishga tayyorlaydi. Foydalanuvchi TUGMA bilan tasdiqlaydi — o'zing tasdiq so'rama",
        "input_schema": {
            "type": "object",
            "properties": {"chat": {"type": "string"}, "text": {"type": "string"}},
            "required": ["chat", "text"],
        },
    },
]

# Tasdiq kutayotgan xabarlar: sid -> {chat_id, to_id, to_name, text, shown}
# bot.py bularga inline tugma chiqaradi; tugma bosilganda yuboriladi/bekor bo'ladi.
import itertools
_send_seq = itertools.count(1)
PENDING_SENDS = {}

# Hafta kunlari (0=Dushanba ... 6=Yakshanba — Python weekday tartibi)
_DAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]

# Namoz nomlari: Aladhan (inglizcha) -> o'zbekcha
PRAYERS = [
    ("Fajr", "Bomdod"),
    ("Dhuhr", "Peshin"),
    ("Asr", "Asr"),
    ("Maghrib", "Shom"),
    ("Isha", "Xufton"),
]


def _safe_path(path):
    """YOZISH yo'li: faqat workspace ichida (xavfsizlik)."""
    full = os.path.abspath(os.path.join(WORKSPACE, path))
    root = os.path.abspath(WORKSPACE)
    if not (full == root or full.startswith(root + os.sep)):
        raise ValueError("yozish faqat workspace ichida ruxsat etilgan")
    return full


def _safe_read_path(path):
    """O'QISH yo'li: READ_ROOT ichida hamma joyda ruxsat, lekin maxfiy
    fayllar (.env, *.session) taqiqlangan."""
    if os.path.isabs(path):
        full = os.path.abspath(path)
    else:
        # Nisbiy yo'l — workspace'ga nisbatan
        full = os.path.abspath(os.path.join(WORKSPACE, path))
    root = os.path.abspath(READ_ROOT)
    if not (full == root or full.startswith(root + os.sep)):
        raise ValueError(f"o'qish faqat {READ_ROOT} ichida ruxsat etilgan")
    base = os.path.basename(full).lower()
    if base == ".env" or base.endswith(".session") or base.endswith(".session-journal"):
        raise ValueError("maxfiy faylni o'qish taqiqlangan")
    return full


def _web_search(query, n=4):
    from ddgs import DDGS

    results = DDGS().text(query, max_results=n)
    if not results:
        return "Hech narsa topilmadi."
    blocks = []
    for r in results:
        body = (r.get("body", "") or "")[:180]
        blocks.append(f"{r.get('title', '')}\n{body}\n{r.get('href', '')}")
    return "\n\n".join(blocks)


def _get_weather(city):
    url = "https://wttr.in/" + urllib.parse.quote(city) + "?format=j1&lang=en"
    raw = urllib.request.urlopen(url, timeout=15).read().decode("utf-8")
    data = json.loads(raw)
    cur = data["current_condition"][0]
    lines = [
        f"{city} hozir: {cur['weatherDesc'][0]['value']}, {cur['temp_C']}°C "
        f"(his {cur['FeelsLikeC']}°C), namlik {cur['humidity']}%, "
        f"shamol {cur['windspeedKmph']}km/h",
        "Prognoz:",
    ]
    for d in data["weather"][:3]:
        noon = d["hourly"][4]
        lines.append(
            f"- {d['date']}: {d['mintempC']}..{d['maxtempC']}°C, "
            f"{noon['weatherDesc'][0]['value']}"
        )
    return "\n".join(lines)


def _read_url(url, limit=6000):
    """Havoladan asosiy matnni ajratadi (trafilatura)."""
    import trafilatura

    if not re.match(r"^https?://", url):
        url = "https://" + url
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return "Sahifani ochib bo'lmadi (link noto'g'ri yoki bloklangan)."
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
    if not text or not text.strip():
        return "Sahifadan matn ajratib bo'lmadi (rasm/video sahifa bo'lishi mumkin)."
    return text.strip()[:limit]


def extract_document_text(path, filename="", mime=""):
    """Hujjatdan matn ajratadi: PDF (pypdf), DOCX (python-docx), matn fayllar."""
    name = (filename or path).lower()
    mime = mime or ""
    try:
        if name.endswith(".pdf") or "pdf" in mime:
            from pypdf import PdfReader

            reader = PdfReader(path)
            return "\n".join((p.extract_text() or "") for p in reader.pages).strip()
        if name.endswith(".docx") or "word" in mime or "officedocument" in mime:
            import docx

            d = docx.Document(path)
            return "\n".join(p.text for p in d.paragraphs).strip()
        # txt / md / kod / csv va h.k.
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except Exception as e:
        return f"__XATO__: {e}"


def _prayer_times(city, date, country="Uzbekistan"):
    ds = date.strftime("%d-%m-%Y")
    url = (
        f"https://api.aladhan.com/v1/timingsByCity/{ds}"
        f"?city={urllib.parse.quote(city)}&country={urllib.parse.quote(country)}&method=14"
    )
    data = json.loads(urllib.request.urlopen(url, timeout=15).read().decode("utf-8"))
    return data["data"]["timings"]


def set_prayer_reminders_for(chat_id, city, days_ahead=1):
    """Berilgan kun uchun namoz eslatmalarini qo'yadi. (o'rnatilganlar ro'yxati)."""
    date = datetime.date.today() + datetime.timedelta(days=days_ahead)
    timings = _prayer_times(city, date)
    now = time.time()
    lines = []
    for eng, uz in PRAYERS:
        hhmm = timings[eng].split()[0]
        h, m = map(int, hhmm.split(":"))
        due = datetime.datetime.combine(date, datetime.time(h, m)).timestamp()
        if due <= now:
            continue
        memory.add_reminder(chat_id, f"{uz} namozi vaqti kirdi 🕌", due)
        lines.append(f"- {uz}: {hhmm}")
    return date, lines


def _get_currency(code=None):
    url = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"
    data = json.loads(urllib.request.urlopen(url, timeout=15).read().decode("utf-8"))
    if code:
        code = code.upper().strip()
        for d in data:
            if d["Ccy"] == code:
                arrow = "↑" if (d["Diff"] or "0")[0] not in "-0" else ""
                return f"{d['Nominal']} {code} = {d['Rate']} so'm ({d['CcyNm_UZ']}), o'zgarish {d['Diff']} {arrow}".strip()
        return f"'{code}' valyuta topilmadi."
    # standart: USD, EUR, RUB
    out = [f"Markaziy bank kursi ({data[0]['Date']}):"]
    for d in data:
        if d["Ccy"] in ("USD", "EUR", "RUB"):
            out.append(f"- {d['Nominal']} {d['Ccy']} = {d['Rate']} so'm (o'zg. {d['Diff']})")
    return "\n".join(out)


def compose_brief(chat_id, city="Tashkent"):
    """Tonggi brifing: sana + ob-havo + namoz vaqtlari + bugungi eslatmalar + valyuta."""
    today = datetime.date.today()
    parts = [f"☀️ Xayrli tong! Bugun {today.strftime('%d.%m.%Y')}"]

    try:
        parts.append("🌤️ " + _get_weather(city))
    except Exception:
        pass

    try:
        timings = _prayer_times(city, today)
        pr = "  ".join(f"{uz} {timings[eng].split()[0]}" for eng, uz in PRAYERS)
        parts.append("🕌 Namoz: " + pr)
    except Exception:
        pass

    try:
        curr = _get_currency("USD")
        parts.append("💵 " + curr)
    except Exception:
        pass

    pend = memory.list_pending_reminders(chat_id)
    today_rem = [
        (t, ts) for t, ts in pend
        if datetime.date.fromtimestamp(ts) == today and "namozi vaqti" not in t
    ]
    if today_rem:
        lines = [
            f"  • {datetime.datetime.fromtimestamp(ts).strftime('%H:%M')} — {t}"
            for t, ts in today_rem
        ]
        parts.append("⏰ Bugungi eslatmalar:\n" + "\n".join(lines))

    return "\n\n".join(parts)


def execute_tool(name, tool_input, chat_id=None):
    """Bitta tool'ni bajaradi va natijani (matn) qaytaradi."""
    try:
        if name == "read_file":
            with open(_safe_read_path(tool_input["path"]), "r", encoding="utf-8", errors="replace") as f:
                return f.read()[:20000]

        if name == "write_file":
            p = _safe_path(tool_input["path"])
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(tool_input["content"])
            return f"Yozildi: {tool_input['path']}"

        if name == "list_files":
            p = _safe_read_path(tool_input.get("path", "."))
            items = []
            for it in sorted(os.listdir(p)):
                mark = "/" if os.path.isdir(os.path.join(p, it)) else ""
                items.append(it + mark)
            return "\n".join(items) if items else "(bo'sh papka)"

        if name == "run_command":
            result = subprocess.run(
                tool_input["command"],
                shell=True,
                cwd=WORKSPACE,
                capture_output=True,
                text=True,
                timeout=120,
            )
            out = (result.stdout or "") + (result.stderr or "")
            return out[:8000] or f"(chiqishsiz tugadi, exit code {result.returncode})"

        if name == "remember":
            memory.add_memory(tool_input["text"])
            return "Eslab qoldim."

        if name == "recall":
            hits = memory.search_memories(tool_input["query"])
            return "\n".join(hits) if hits else "Bu haqda hech narsa topilmadi."

        if name == "web_search":
            return _web_search(tool_input["query"])

        if name == "read_url":
            return _read_url(tool_input["url"])

        if name == "get_weather":
            return _get_weather(tool_input["city"])

        if name == "set_reminder":
            minutes = float(tool_input.get("minutes", 0))
            text = tool_input["text"]
            due = time.time() + minutes * 60
            memory.add_reminder(chat_id, text, due)
            when = datetime.datetime.fromtimestamp(due).strftime("%H:%M")
            return f"Eslatma o'rnatildi: {minutes:g} daqiqadan keyin (soat {when}) — '{text}'"

        if name == "list_reminders":
            pend = memory.list_pending_reminders(chat_id)
            if not pend:
                return "Faol eslatma yo'q."
            lines = []
            for text, due_ts in pend:
                when = datetime.datetime.fromtimestamp(due_ts).strftime("%Y-%m-%d %H:%M")
                lines.append(f"- {when}: {text}")
            return "\n".join(lines)

        if name == "tg_chats":
            import userbot
            return userbot.list_chats(int(tool_input.get("limit", 10)))

        if name == "tg_read":
            import userbot
            return userbot.read_messages(
                tool_input["chat"], int(tool_input.get("limit", 10))
            )

        if name == "tg_send":
            import userbot
            if not userbot._ensure_started():
                return userbot.NOT_READY
            resolved = userbot.resolve_chat(tool_input["chat"])
            if resolved is None:
                return (
                    f"'{tool_input['chat']}' topilmadi. tg_chats bilan "
                    "suhbatlar ro'yxatini ko'rib, aniq nomini ishlat."
                )
            to_id, to_name = resolved
            sid = next(_send_seq)
            PENDING_SENDS[sid] = {
                "chat_id": chat_id,
                "to_id": to_id,
                "to_name": to_name,
                "text": tool_input["text"],
                "shown": False,
            }
            return (
                f"Xabar tayyorlandi: {to_name} ga. Foydalanuvchiga tasdiq TUGMASI "
                "ko'rsatiladi — sen faqat qisqa qilib 'tayyorladim, tugma bilan "
                "tasdiqlang' de. Tasdiq so'ramа, qayta tayyorlama."
            )

        if name == "set_prayer_reminders":
            city = tool_input.get("city", "Tashkent")
            days = int(tool_input.get("days_ahead", 1))
            date, lines = set_prayer_reminders_for(chat_id, city, days)
            if not lines:
                return "Bu kun uchun namoz vaqtlari o'tib ketgan."
            return (
                f"{city} uchun {date.strftime('%d.%m.%Y')} namoz eslatmalari qo'yildi:\n"
                + "\n".join(lines)
            )

        if name == "set_daily_prayers":
            on = bool(tool_input.get("on"))
            city = tool_input.get("city") or memory.get_setting(chat_id, "prayer_city", "Tashkent")
            if not on:
                memory.set_setting(chat_id, "auto_prayer", "0")
                return "Kundalik avto-namoz eslatmasi o'chirildi."
            memory.set_setting(chat_id, "auto_prayer", "1")
            memory.set_setting(chat_id, "prayer_city", city)
            # Bugungisini darrov qo'yamiz (ertaga avtomatik davom etadi).
            _, lines = set_prayer_reminders_for(chat_id, city, 0)
            extra = ("\nBugungisi ham qo'yildi:\n" + "\n".join(lines)) if lines else ""
            return (
                f"Kundalik avto-namoz YOQILDI ({city}). Har kuni ertalab o'zi qo'yadi." + extra
            )

        if name == "get_currency":
            return _get_currency(tool_input.get("code"))

        if name == "set_morning_brief":
            on = bool(tool_input.get("on"))
            city = tool_input.get("city") or memory.get_setting(chat_id, "brief_city", "Tashkent")
            if not on:
                memory.set_setting(chat_id, "morning_brief", "0")
                return "Tonggi brifing o'chirildi."
            memory.set_setting(chat_id, "morning_brief", "1")
            memory.set_setting(chat_id, "brief_city", city)
            return (
                f"Tonggi brifing YOQILDI ({city}). Har kuni ertalab soat "
                f"{BRIEF_HOUR}:00 da yuboriladi. Mana bugungisi:\n\n"
                + compose_brief(chat_id, city)
            )

        if name == "set_recurring_reminder":
            text = tool_input["text"]
            hour = int(tool_input["hour"])
            minute = int(tool_input.get("minute", 0) or 0)
            dow = tool_input.get("weekday")
            dow = int(dow) if dow is not None and dow != "" else None
            memory.add_recurring(chat_id, text, hour, minute, dow)
            when = f"{_DAYS[dow]} kunlari" if dow is not None else "har kuni"
            return f"Takroriy eslatma qo'yildi: {when} soat {hour:02d}:{minute:02d} — '{text}'"

        if name == "list_recurring":
            rows = memory.list_recurring(chat_id)
            if not rows:
                return "Takroriy eslatma yo'q."
            out = []
            for i, (_id, text, h, m, dow) in enumerate(rows, 1):
                when = _DAYS[dow] if dow is not None else "har kuni"
                out.append(f"{i}. {when} {h:02d}:{m:02d} — {text}")
            return "\n".join(out)

        if name == "cancel_recurring":
            t = memory.cancel_recurring(chat_id, int(tool_input["number"]))
            return f"O'chirildi: {t}" if t else "Bunday raqamli takroriy eslatma yo'q."

        if name == "add_todo":
            memory.add_todo(chat_id, tool_input["text"])
            return f"Ro'yxatga qo'shildi: {tool_input['text']}"

        if name == "list_todos":
            todos = memory.list_todos(chat_id)
            if not todos:
                return "Vazifalar ro'yxati bo'sh."
            return "\n".join(f"{i}. {t}" for i, (_id, t) in enumerate(todos, 1))

        if name == "complete_todo":
            num = tool_input.get("number")
            num = int(num) if num is not None and num != "" else None
            done = memory.complete_todo(chat_id, num, tool_input.get("text"))
            return f"Bajarildi ✅: {done}" if done else "Bunday vazifa topilmadi."

        return f"Noma'lum tool: {name}"

    except Exception as e:
        return f"Tool xatosi: {e}"
