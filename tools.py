"""Agent qo'llari (tool'lar): fayl, buyruq, xotira, qidiruv, ob-havo, eslatma.
Ta'riflar token tejash uchun ataylab qisqa — nom o'zi tushunarli."""
import os
import json
import time
import datetime
import subprocess
import urllib.request
import urllib.parse

from config import WORKSPACE, READ_ROOT
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


def _prayer_times(city, date, country="Uzbekistan"):
    ds = date.strftime("%d-%m-%Y")
    url = (
        f"https://api.aladhan.com/v1/timingsByCity/{ds}"
        f"?city={urllib.parse.quote(city)}&country={urllib.parse.quote(country)}&method=14"
    )
    data = json.loads(urllib.request.urlopen(url, timeout=15).read().decode("utf-8"))
    return data["data"]["timings"]


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
            date = datetime.date.today() + datetime.timedelta(days=days)
            timings = _prayer_times(city, date)
            now = time.time()
            set_lines = []
            for eng, uz in PRAYERS:
                hhmm = timings[eng].split()[0]  # "03:19 (+05)" -> "03:19"
                h, m = map(int, hhmm.split(":"))
                due = datetime.datetime.combine(date, datetime.time(h, m)).timestamp()
                if due <= now:
                    continue  # vaqti o'tib ketgan
                memory.add_reminder(chat_id, f"{uz} namozi vaqti kirdi 🕌", due)
                set_lines.append(f"- {uz}: {hhmm}")
            if not set_lines:
                return "Bu kun uchun namoz vaqtlari o'tib ketgan."
            return (
                f"{city} uchun {date.strftime('%d.%m.%Y')} namoz eslatmalari qo'yildi:\n"
                + "\n".join(set_lines)
            )

        return f"Noma'lum tool: {name}"

    except Exception as e:
        return f"Tool xatosi: {e}"
