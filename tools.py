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

# Xarajat kategoriyalari — qat'iy ro'yxat, aks holda hisobotda "ovqat",
# "tushlik", "obed" alohida qatorlarga bo'linib ketadi.
EXPENSE_CATEGORIES = [
    "ovqat", "transport", "uy", "kommunal", "aloqa", "kiyim",
    "sog'liq", "ta'lim", "ko'ngilochar", "sovg'a", "boshqa",
]
_PERIODS = {
    "bugun": "Bugun", "kecha": "Kecha", "hafta": "Shu hafta",
    "otgan_hafta": "O'tgan hafta", "oy": "Shu oy",
    "otgan_oy": "O'tgan oy", "yil": "Shu yil",
}

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
        "description": (
            "FAQAT egang aniq 'eslab qol' desa. text=qisqa o'zbekcha fakt, 'men/mening' "
            "emas: 'Ukasi Aziz', 'Qahvani shakarsiz ichadi'"
        ),
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "recall",
        "description": "Xotiradan qidirish. query bo'sh = hamma faktlar (raqamlangan)",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": ["string", "null"]}},
            "required": [],
        },
    },
    {
        "name": "forget",
        "description": "Faktni xotiradan o'chiradi: number=recall ro'yxatidagi raqam yoki text=fakt matnidan qism",
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {"type": ["number", "null"]},
                "text": {"type": ["string", "null"]},
            },
            "required": [],
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
        "description": "HAMMA eslatmalar: bir martalik + takroriy (raqamlangan)",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "cancel_reminder",
        "description": "Bir martalik eslatmani o'chiradi: number=list_reminders raqami yoki all=true (hammasi)",
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {"type": ["number", "null"]},
                "all": {"type": ["boolean", "null"]},
            },
            "required": [],
        },
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
        "description": "Takroriy eslatmani o'chiradi: number=takroriylar ro'yxatidagi raqam yoki all=true (hammasi)",
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {"type": ["number", "null"]},
                "all": {"type": ["boolean", "null"]},
            },
            "required": [],
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
        "description": "Vazifani bajarilgan deb belgilaydi. number=ro'yxatdagi raqam, text=vazifa matni yoki all=true (hammasi)",
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {"type": ["number", "null"]},
                "text": {"type": ["string", "null"]},
                "all": {"type": ["boolean", "null"]},
            },
            "required": [],
        },
    },
    {
        "name": "add_expense",
        "description": (
            "Xarajat(lar)ni yozadi — xabardagi HAR BIR xarajat items'da alohida. "
            "amount=so'mda butun son (25 ming=25000, 45k=45000, 1.2 mln=1200000). "
            "day=YYYY-MM-DD, faqat bugun bo'lmasa (kecha va h.k.). "
            "kommunal=svet/gaz/suv/chiqindi, aloqa=telefon/internet, "
            "uy=ijara/jihoz/xo'jalik, transport=taksi/benzin/metro."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "amount": {"type": "number"},
                            "category": {"type": "string", "enum": EXPENSE_CATEGORIES},
                            "note": {"type": ["string", "null"]},
                            "day": {"type": ["string", "null"]},
                        },
                        "required": ["amount", "category"],
                    },
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "expense_report",
        "description": "Xarajatlar hisoboti: jami, kategoriyalar bo'yicha, eng kattalari.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "enum": list(_PERIODS)},
                # null ruxsat: model ixtiyoriy maydonga null yuboradi, Groq esa
                # sxemaga mos kelmasa butun chaqiruvni rad etadi.
                "category": {"type": ["string", "null"], "enum": EXPENSE_CATEGORIES + [None]},
            },
            "required": ["period"],
        },
    },
    {
        "name": "list_expenses",
        "description": "Oxirgi kiritilgan xarajatlar (raqamlangan, 1=eng oxirgisi).",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": ["number", "null"]}},
            "required": [],
        },
    },
    {
        "name": "delete_expense",
        "description": "Xarajatni o'chiradi. number=list_expenses raqami (1=eng oxirgisi).",
        "input_schema": {
            "type": "object",
            "properties": {"number": {"type": "number"}},
            "required": ["number"],
        },
    },
    {
        "name": "set_budget",
        "description": (
            "OYLIK budjet qo'yadi/o'zgartiradi. category='jami' — umumiy budjet, "
            "aks holda xarajat kategoriyasi. amount=so'm (0 = o'chirish)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["jami"] + EXPENSE_CATEGORIES},
                "amount": {"type": "number"},
            },
            "required": ["category", "amount"],
        },
    },
    {
        "name": "calendar_events",
        "description": (
            "Google Calendar tadbirlari. period: bugun/ertaga/hafta; yoki date — aniq sana "
            "YYYY-MM-DD yoki hafta kuni so'zi ('juma') — O'ZING hisoblama"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": ["string", "null"], "enum": ["bugun", "ertaga", "hafta", None]},
                "date": {"type": ["string", "null"]},
            },
            "required": [],
        },
    },
    {
        "name": "calendar_add",
        "description": (
            "Google Calendar'ga tadbir qo'shadi. date: aniq sana aytilsa YYYY-MM-DD (12-mart -> "
            "YYYY-03-12), nisbiy bo'lsa SO'ZNING O'ZI: 'ertaga', 'indinga', 'juma', 'kelasi juma' — "
            "hafta kunini sanaga O'ZING aylantirma. time=HH:MM (bo'lmasa kun bo'yi), duration_min (standart 60)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "date": {"type": "string"},
                "time": {"type": ["string", "null"]},
                "duration_min": {"type": ["number", "null"]},
                "location": {"type": ["string", "null"]},
            },
            "required": ["title", "date"],
        },
    },
    {
        "name": "projects_list",
        "description": "Kod loyihalari (git repolar) ro'yxati: oxirgi faollik, branch, commit qilinmaganlar",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "project_status",
        "description": "Bitta loyiha holati: branch, push qilinmagan, commit qilinmagan fayllar, oxirgi commitlar",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "project_changes",
        "description": (
            "Davrdagi o'zgarishlar (commitlar). name=loyiha (ERP, bilim manba...), "
            "bo'sh = hamma loyihalar ('bugun nima qildim')"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
                "period": {"type": "string", "enum": ["bugun", "kecha", "hafta", "oy"]},
            },
            "required": ["period"],
        },
    },
    {
        "name": "budget_status",
        "description": "Shu oylik budjet holati: qancha ishlatildi, qancha qoldi",
        "input_schema": {"type": "object", "properties": {}, "required": []},
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
    {
        "name": "tg_leave",
        "description": "Shaxsiy Telegram: kanal yoki guruhdan chiqishga tayyorlaydi — egasi TUGMA bilan tasdiqlaydi",
        "input_schema": {
            "type": "object",
            "properties": {"chat": {"type": "string"}},
            "required": ["chat"],
        },
    },
    {
        "name": "tg_pin",
        "description": "Shaxsiy Telegram: chatni ro'yxat tepasiga pin qiladi (pin=false — unpin)",
        "input_schema": {
            "type": "object",
            "properties": {"chat": {"type": "string"}, "pin": {"type": ["boolean", "null"]}},
            "required": ["chat"],
        },
    },
    {
        "name": "unanswered",
        "description": "Shaxsiy Telegram: kimlar javob kutyapti (javob berilmagan shaxsiy xabarlar)",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_unanswered_alerts",
        "description": "Javobsiz xabarlar haqida kuniga 2 marta (12:00, 19:00) eslatishni yoqadi/o'chiradi",
        "input_schema": {
            "type": "object",
            "properties": {"on": {"type": "boolean"}},
            "required": ["on"],
        },
    },
    {
        "name": "digest_add",
        "description": "Kanalni kundalik dayjestga qo'shadi. channel=kanal nomi yoki @username",
        "input_schema": {
            "type": "object",
            "properties": {"channel": {"type": "string"}},
            "required": ["channel"],
        },
    },
    {
        "name": "digest_remove",
        "description": "Kanalni dayjestdan olib tashlaydi",
        "input_schema": {
            "type": "object",
            "properties": {"channel": {"type": "string"}},
            "required": ["channel"],
        },
    },
    {
        "name": "digest_list",
        "description": "Dayjestdagi kanallar. all=true — obuna bo'lingan HAMMA kanallar (tanlash uchun)",
        "input_schema": {
            "type": "object",
            "properties": {"all": {"type": ["boolean", "null"]}},
            "required": [],
        },
    },
    {
        "name": "digest_now",
        "description": "Dayjestni hozir tayyorlaydi (oxirgi dayjestdan keyingi postlar)",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "set_digest",
        "description": "Kundalik dayjestni yoqadi/o'chiradi; hour=soat (0-23, standart 21)",
        "input_schema": {
            "type": "object",
            "properties": {
                "on": {"type": "boolean"},
                "hour": {"type": ["number", "null"]},
            },
            "required": ["on"],
        },
    },
]

# Tool natijasi shu belgi bilan boshlansa — agent uni modelga qaytarmay,
# egasiga so'zma-so'z beradi (dayjest havolalari, ro'yxatlar buzilmasin).
FINAL = "\x00FINAL\x00"
DIGEST_HOUR = 21

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


def _som(n):
    return f"{int(n):,}".replace(",", " ") + " so'm"


_CAT_EMOJI = {
    "ovqat": "🍽", "transport": "🚕", "uy": "🏠", "kommunal": "💡",
    "aloqa": "📱", "kiyim": "👕", "sog'liq": "💊", "ta'lim": "📚",
    "ko'ngilochar": "🎉", "sovg'a": "🎁", "boshqa": "📦",
}


def _cat(category):
    return f"{_CAT_EMOJI.get(category, '📦')} {category}"


def _dm(day):
    """'2026-09-22' -> '22.09'"""
    return f"{day[8:10]}.{day[5:7]}"


def _period_range(period, today=None):
    """Davr nomi -> (boshlanish, tugash) sanalari (ikkalasi ham kiradi)."""
    d = today or datetime.date.today()
    if period == "bugun":
        return d, d
    if period == "kecha":
        y = d - datetime.timedelta(days=1)
        return y, y
    if period == "hafta":
        return d - datetime.timedelta(days=d.weekday()), d
    if period == "otgan_hafta":
        start = d - datetime.timedelta(days=d.weekday() + 7)
        return start, start + datetime.timedelta(days=6)
    if period == "oy":
        return d.replace(day=1), d
    if period == "otgan_oy":
        end = d.replace(day=1) - datetime.timedelta(days=1)
        return end.replace(day=1), end
    if period == "yil":
        return d.replace(month=1, day=1), d
    raise ValueError(f"noma'lum davr: {period}")


def expense_report(chat_id, period, category=None):
    start, end = _period_range(period)
    rows = memory.expenses_between(chat_id, start.isoformat(), end.isoformat())
    if category:
        rows = [r for r in rows if r[1] == category]
    label = _PERIODS[period] + (f" · {_cat(category)}" if category else "")
    if not rows:
        return f"📊 **{label}**: xarajat yozilmagan."

    total = sum(r[0] for r in rows)
    out = [f"📊 **{label}** — {_som(total)}"]
    days = (end - start).days + 1
    sub = f"{len(rows)} ta xarajat"
    if days > 1:
        sub += f" · kuniga ~{_som(total / days)}"
    out.append(sub)

    if not category:
        by_cat = {}
        for amount, cat, _note, _day in rows:
            by_cat[cat] = by_cat.get(cat, 0) + amount
        out.append("\n**Kategoriyalar**")
        for cat, s in sorted(by_cat.items(), key=lambda x: -x[1]):
            out.append(f"{_cat(cat)} — {_som(s)} ({round(s * 100 / total)}%)")

    top = sorted(rows, key=lambda r: -r[0])[:3]
    out.append("\n**Eng kattalari**")
    for amount, cat, note, day in top:
        out.append(f"• {_dm(day)} {note or cat} — {_som(amount)}")
    return "\n".join(out)


# --- Oylik budjet ---

BUDGET_LEVELS = (80, 100)


def _month_spent(chat_id, today=None):
    """Shu oy: {kategoriya: summa, 'jami': umumiy}."""
    d = today or datetime.date.today()
    rows = memory.expenses_between(chat_id, d.replace(day=1).isoformat(), d.isoformat())
    spent = {"jami": 0}
    for amount, cat, _note, _day in rows:
        spent[cat] = spent.get(cat, 0) + amount
        spent["jami"] += amount
    return spent


def _bar(pct, width=10):
    filled = min(width, round(pct * width / 100))
    return "▓" * filled + "░" * (width - filled)


def _days_left(today=None):
    d = today or datetime.date.today()
    nxt = (d.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
    return (nxt - d).days  # bugun ham kiradi


def _budget_label(cat):
    return "💰 Umumiy" if cat == "jami" else _cat(cat)


def budget_status(chat_id):
    budgets = memory.list_budgets(chat_id)
    if not budgets:
        return (
            "Budjet qo'yilmagan. Masalan: \"ovqatga oyiga 2 mln budjet\" yoki "
            "\"umumiy budjet 8 mln\"."
        )
    spent = _month_spent(chat_id)
    days = _days_left()
    out = [f"📊 **Budjet** — {datetime.date.today():%m.%Y}, oy oxirigacha {days} kun"]
    for cat, limit in budgets.items():
        s = spent.get(cat, 0)
        pct = round(s * 100 / limit)
        left = limit - s
        out.append(f"\n{_budget_label(cat)}: {_som(s)} / {_som(limit)}")
        out.append(f"{_bar(pct)} {pct}%")
        if left > 0:
            out.append(f"Qoldi {_som(left)} · kuniga ~{_som(left / days)}")
        else:
            out.append(f"🔴 {_som(-left)} oshib ketdi")
    return "\n".join(out)


def budget_alerts(chat_id):
    """Xarajatdan keyin: 80%/100% chegarasi YANGI kesib o'tilgan budjetlar.
    Har chegara oyiga bir marta aytiladi (settings'da eslab qolinadi)."""
    budgets = memory.list_budgets(chat_id)
    if not budgets:
        return []
    spent = _month_spent(chat_id)
    month = datetime.date.today().strftime("%Y-%m")
    alerts = []
    for cat, limit in budgets.items():
        pct = spent.get(cat, 0) * 100 / limit
        level = max((lv for lv in BUDGET_LEVELS if pct >= lv), default=0)
        key = f"budget_alert_{cat}_{month}"
        if level <= int(memory.get_setting(chat_id, key, "0") or 0):
            continue
        memory.set_setting(chat_id, key, level)
        left = limit - spent.get(cat, 0)
        if level >= 100:
            alerts.append(
                f"🔴 **{_budget_label(cat)} budjeti tugadi**: {round(pct)}% "
                f"({_som(-left)} oshdi)" if left < 0 else
                f"🔴 **{_budget_label(cat)} budjeti tugadi** (100%)"
            )
        else:
            alerts.append(
                f"🟠 **{_budget_label(cat)} budjetining {round(pct)}% ishlatildi** — "
                f"qoldi {_som(left)}, {_days_left()} kunga"
            )
    return alerts


def budget_brief(chat_id):
    """Brifing uchun bitta qator (umumiy budjet bo'lsa u, aks holda eng to'lgan)."""
    budgets = memory.list_budgets(chat_id)
    if not budgets:
        return ""
    spent = _month_spent(chat_id)
    cat = "jami" if "jami" in budgets else max(budgets, key=lambda c: spent.get(c, 0) / budgets[c])
    pct = round(spent.get(cat, 0) * 100 / budgets[cat])
    return f"💰 Budjet ({_budget_label(cat).split(' ', 1)[1]}): {pct}% ishlatildi · {_days_left()} kun qoldi"


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

    yday = (today - datetime.timedelta(days=1)).isoformat()
    spent = sum(r[0] for r in memory.expenses_between(chat_id, yday, yday))
    if spent:
        parts.append(f"💸 Kecha sarflading: **{_som(spent)}**")

    line = budget_brief(chat_id)
    if line:
        parts.append(line)

    for mod in ("gcal", "projects"):
        try:
            line = __import__(mod).brief_line()
            if line:
                parts.append(line)
        except Exception:
            pass

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
            text = tool_input["text"].strip()
            if memory.memory_exists(text):
                return "Buni allaqachon bilaman."
            memory.add_memory(text, "boshqa", 3)
            return f"🧠 Eslab qoldim: {text}"

        if name == "recall":
            facts = memory.list_memories()
            query = (tool_input.get("query") or "").strip().lower()
            numbered = list(enumerate(facts, 1))
            if query:
                numbered = [(i, f) for i, f in numbered if query in f["text"].lower()]
            if not numbered:
                return "Bu haqda hech narsa bilmayman." if query else "Xotira hozircha bo'sh."
            return "🧠 **Bilganlarim**\n" + "\n".join(f"{i}. {f['text']}" for i, f in numbered)

        if name == "forget":
            facts = memory.list_memories()
            num = tool_input.get("number")
            text = (tool_input.get("text") or "").strip().lower()
            target = None
            if num is not None and 1 <= int(num) <= len(facts):
                target = facts[int(num) - 1]
            elif text:
                target = next((f for f in facts if text in f["text"].lower()), None)
            if not target:
                return "Bunday fakt topilmadi."
            memory.delete_memory(target["id"])
            return f"🗑 Unutdim: {target['text']}"

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
            # Ikkala turi birga: avval faqat bir martaliklar ko'rsatilardi va
            # takroriylar bo'lsa ham "eslatma yo'q" deb javob berardi.
            pend = memory.pending_reminders_with_id(chat_id)
            rec = memory.list_recurring(chat_id)
            if not pend and not rec:
                return FINAL + "⏰ Kutilayotgan eslatma yo'q (bir martalik ham, takroriy ham)."
            out = []
            if pend:
                out.append(f"⏰ **Bir martalik** ({len(pend)})")
                out += [
                    f"{i}. {datetime.datetime.fromtimestamp(ts):%d.%m %H:%M} — {text}"
                    for i, (_id, text, ts) in enumerate(pend, 1)
                ]
            if rec:
                out.append(f"\n🔁 **Takroriy** ({len(rec)})")
                out += [
                    f"{i}. {_DAYS[dow] if dow is not None else 'har kuni'} {h:02d}:{m:02d} — {text}"
                    for i, (_id, text, h, m, dow) in enumerate(rec, 1)
                ]
            return FINAL + "\n".join(out)

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

        if name in ("tg_leave", "tg_pin"):
            import userbot
            if not userbot._ensure_started():
                return userbot.NOT_READY
            ch = userbot.find_chat(tool_input["chat"])
            if not ch:
                return f"'{tool_input['chat']}' topilmadi. tg_chats bilan aniq nomini ko'r."
            if name == "tg_pin":
                pin = tool_input.get("pin")
                pin = True if pin is None else bool(pin)
                try:
                    userbot.pin_chat(ch["id"], pin)
                except Exception as e:
                    if "PinnedDialogsTooMuch" in type(e).__name__:
                        return FINAL + (
                            "📌 Pin joylari to'lgan (Telegram: 5 ta, Premium'da 10 ta). "
                            "Avval birini unpin qil — masalan «X ni pindan ol»."
                        )
                    raise
                return FINAL + (f"📌 «{ch['name']}» pin qilindi." if pin else f"«{ch['name']}» pindan olindi.")
            if ch["kind"] == "shaxsiy":
                return FINAL + "Shaxsiy suhbatdan chiqib bo'lmaydi — faqat kanal yoki guruhdan."
            sid = next(_send_seq)
            PENDING_SENDS[sid] = {
                "kind": "leave", "chat_id": chat_id, "to_id": ch["id"],
                "to_name": f"{ch['name']} ({ch['kind']})", "text": "", "shown": False,
            }
            return FINAL + f"🚪 «{ch['name']}» {ch['kind']}idan chiqishni tasdiqlang 👇"

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
            if tool_input.get("all"):
                n = memory.cancel_all_recurring(chat_id)
                return f"🗑 {n} ta takroriy eslatma o'chirildi." if n else "Takroriy eslatma yo'q edi."
            if tool_input.get("number") is None:
                return "Qaysi birini? number (raqam) yoki all=true ber."
            t = memory.cancel_recurring(chat_id, int(tool_input["number"]))
            return f"🗑 O'chirildi: {t}" if t else "Bunday raqamli takroriy eslatma yo'q."

        if name == "cancel_reminder":
            if tool_input.get("all"):
                n = memory.cancel_reminder(chat_id, all_=True)
                return f"🗑 {n} ta eslatma bekor qilindi." if n else "Kutilayotgan bir martalik eslatma yo'q edi."
            num = tool_input.get("number")
            n = memory.cancel_reminder(chat_id, int(num)) if num is not None else 0
            return "🗑 Eslatma bekor qilindi." if n else "Bunday raqamli eslatma yo'q."

        if name == "add_todo":
            memory.add_todo(chat_id, tool_input["text"])
            return f"Ro'yxatga qo'shildi: {tool_input['text']}"

        if name == "list_todos":
            todos = memory.list_todos(chat_id)
            if not todos:
                return "Vazifalar ro'yxati bo'sh."
            return "\n".join(f"{i}. {t}" for i, (_id, t) in enumerate(todos, 1))

        if name == "complete_todo":
            if tool_input.get("all"):
                n = memory.complete_all_todos(chat_id)
                return f"✅ {n} ta vazifa bajarildi deb belgilandi." if n else "Ochiq vazifa yo'q edi."
            num = tool_input.get("number")
            num = int(num) if num is not None and num != "" else None
            done = memory.complete_todo(chat_id, num, tool_input.get("text"))
            return f"Bajarildi ✅: {done}" if done else "Bunday vazifa topilmadi."

        if name == "add_expense":
            # Eski format (bitta xarajat to'g'ridan-to'g'ri) ham qabul qilinadi.
            items = tool_input.get("items") or [tool_input]
            today = datetime.date.today().isoformat()
            lines = []
            for it in items:
                amount = int(round(float(it["amount"])))
                if amount <= 0:
                    lines.append("❌ Summa musbat bo'lishi kerak.")
                    continue
                category = it.get("category")
                if category not in EXPENSE_CATEGORIES:
                    category = "boshqa"
                day = it.get("day") or today
                try:
                    datetime.date.fromisoformat(day)
                except ValueError:
                    day = today
                note = (it.get("note") or "").strip()
                memory.add_expense(chat_id, amount, category, note, day)
                when = "" if day == today else f" ({_dm(day)})"
                lines.append(f"✅ **{note or category}**{when} — {_som(amount)} · {_cat(category)}")
            spent = sum(r[0] for r in memory.expenses_between(chat_id, today, today))
            lines.append(f"\nBugun jami: **{_som(spent)}**")
            alerts = budget_alerts(chat_id)
            if alerts:
                lines.append("\n" + "\n".join(alerts))
            return "\n".join(lines)

        if name == "set_budget":
            category = tool_input.get("category") or "jami"
            if category != "jami" and category not in EXPENSE_CATEGORIES:
                return f"Noma'lum kategoriya. Mumkin: jami, {', '.join(EXPENSE_CATEGORIES)}"
            amount = int(round(float(tool_input.get("amount") or 0)))
            memory.set_budget(chat_id, category, amount)
            label = "💰 Umumiy oylik budjet" if category == "jami" else f"{_cat(category)} budjeti"
            if amount <= 0:
                return f"🗑 {label} o'chirildi."
            return f"{label}: **{_som(amount)}** / oy.\n\n" + budget_status(chat_id)

        if name == "budget_status":
            return budget_status(chat_id)

        if name == "calendar_events":
            import gcal
            return FINAL + gcal.events_text(
                tool_input.get("period") or "bugun", tool_input.get("date") or None
            )

        if name == "calendar_add":
            import gcal
            return FINAL + gcal.add_event(
                tool_input["title"], tool_input["date"], tool_input.get("time") or None,
                tool_input.get("duration_min") or 60, tool_input.get("location") or "",
            )

        if name == "projects_list":
            import projects
            return FINAL + projects.list_text()

        if name == "project_status":
            import projects
            return FINAL + projects.status_text(tool_input["name"])

        if name == "project_changes":
            import projects
            return FINAL + projects.changes_text(
                tool_input.get("name") or None, tool_input.get("period") or "bugun"
            )

        if name == "expense_report":
            return expense_report(chat_id, tool_input["period"], tool_input.get("category"))

        if name == "list_expenses":
            limit = int(tool_input.get("limit") or 10)
            rows = memory.recent_expenses(chat_id, min(max(limit, 1), 30))
            if not rows:
                return "Hali xarajat yozilmagan."
            return "🧾 **Oxirgi xarajatlar**\n" + "\n".join(
                f"{i}. {_dm(day)} {note or cat} — {_som(amount)} · {_cat(cat)}"
                for i, (_id, amount, cat, note, day) in enumerate(rows, 1)
            )

        if name == "delete_expense":
            row = memory.delete_expense(chat_id, int(tool_input["number"]))
            if not row:
                return "Bunday raqamli xarajat yo'q."
            _id, amount, cat, note, day = row
            return f"🗑 O'chirildi: {_dm(day)} **{note or cat}** — {_som(amount)}"

        if name == "unanswered":
            import digest
            text = digest.unanswered_text()
            return FINAL + (text or "✅ Hamma shaxsiy xabarlarga javob berilgan.")

        if name == "set_unanswered_alerts":
            on = bool(tool_input.get("on"))
            memory.set_setting(chat_id, "unanswered_alerts", "1" if on else "0")
            return (
                "📥 Javobsiz xabarlar eslatmasi yoqildi: har kuni 12:00 va 19:00."
                if on else "Javobsiz xabarlar eslatmasi o'chirildi."
            )

        if name == "digest_add":
            import userbot
            if not userbot._ensure_started():
                return userbot.NOT_READY
            ch = userbot.find_channel(tool_input["channel"])
            if not ch:
                return (
                    f"'{tool_input['channel']}' kanali topilmadi (faqat obuna bo'lingan "
                    "kanallar). digest_list all=true bilan ro'yxatni ko'r."
                )
            added = memory.add_digest_channel(chat_id, ch["id"], ch["title"], ch["username"])
            if memory.get_setting(chat_id, "digest") is None:
                memory.set_setting(chat_id, "digest", "1")
                memory.set_setting(chat_id, "digest_hour", str(DIGEST_HOUR))
            hour = memory.get_setting(chat_id, "digest_hour", str(DIGEST_HOUR))
            if not added:
                return f"«{ch['title']}» allaqachon dayjestda."
            return f"📰 «{ch['title']}» dayjestga qo'shildi. Dayjest har kuni {hour}:00 da keladi."

        if name == "digest_remove":
            title = memory.remove_digest_channel(chat_id, tool_input["channel"])
            return f"«{title}» dayjestdan olib tashlandi." if title else "Bunday kanal dayjestda yo'q."

        if name == "digest_list":
            followed = memory.list_digest_channels(chat_id)
            ids = {c["channel_id"] for c in followed}
            if tool_input.get("all"):
                import userbot
                chans = userbot.list_channels()
                if chans is None:
                    return userbot.NOT_READY
                if not chans:
                    return "Hech qanday kanalga obuna emassan."
                chans.sort(key=lambda c: c["id"] not in ids)  # dayjestdagilar tepada
                lines = [f"📺 **Obuna bo'lingan kanallar** ({len(chans)}) — ✅ dayjestda"]
                lines += [
                    f"{'✅' if c['id'] in ids else '▫️'} {c['title']}"
                    + (f" (@{c['username']})" if c["username"] else "")
                    for c in chans
                ]
                return FINAL + "\n".join(lines)
            if not followed:
                return "Dayjestda kanal yo'q. digest_list all=true — obuna kanallar ro'yxati."
            on = memory.get_setting(chat_id, "digest", "0") == "1"
            hour = memory.get_setting(chat_id, "digest_hour", str(DIGEST_HOUR))
            head = f"📰 **Dayjest** — {'har kuni ' + hour + ':00' if on else 'o‘chiq'}"
            return FINAL + head + "\n" + "\n".join(f"• {c['title']}" for c in followed)

        if name == "digest_now":
            import digest
            return FINAL + digest.build_digest(chat_id)

        if name == "set_digest":
            on = bool(tool_input.get("on"))
            memory.set_setting(chat_id, "digest", "1" if on else "0")
            hour = tool_input.get("hour")
            if hour is not None:
                memory.set_setting(chat_id, "digest_hour", str(min(max(int(hour), 0), 23)))
            h = memory.get_setting(chat_id, "digest_hour", str(DIGEST_HOUR))
            return f"📰 Kundalik dayjest yoqildi: har kuni {h}:00." if on else "Kundalik dayjest o'chirildi."

        return f"Noma'lum tool: {name}"

    except Exception as e:
        return f"Tool xatosi: {e}"
