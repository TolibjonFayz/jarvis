"""Miya: Groq'ni chaqiradi. Token tejash uchun 2 fazali + kategoriyali tool'lar:

Faza 1 (router, tool'siz, arzon) — oddiy suhbat shu yerda tugaydi.
  Tool kerak bo'lsa model <TOOL:kategoriya> deb belgi qaytaradi.
Faza 2 (tool bilan) — FAQAT kerakli kategoriya tool'lari yuboriladi
  (hamma 15 ta emas — bu eng katta token tejash).
"""
import re
import json
import datetime

from groq import Groq, RateLimitError

import memory
from config import GROQ_API_KEY, MODEL, MAX_TOKENS
from tools import TOOLS, execute_tool

# max_retries=0: 429 da kutmasdan darhol zaxira modelga o'tamiz.
client = Groq(api_key=GROQ_API_KEY, max_retries=0) if GROQ_API_KEY else None

# Zaxira zanjiri: asosiy model chegarasi (kunlik/daqiqalik) tugasa,
# keyingisiga o'tamiz. Groq'da har model uchun ALOHIDA tekin budjet bor.
MODEL_CHAIN = [
    MODEL,
    "openai/gpt-oss-20b",
    "qwen/qwen3-32b",
]

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _create(**kwargs):
    """Chaqiruv: 429 bo'lsa zanjirdagi keyingi modelga o'tadi."""
    last_err = None
    for m in MODEL_CHAIN:
        try:
            return client.chat.completions.create(model=m, **kwargs)
        except RateLimitError as e:
            last_err = e
            continue
    raise last_err


def _clean(text):
    """qwen kabi modellarning <think> bloklarini olib tashlaydi."""
    return _THINK_RE.sub("", text or "").strip()

# Router javobi (Faza 1) uchun kichikroq chegara — Groq max_tokens'ni ham
# daqiqalik budjetga qo'shib hisoblaydi.
ROUTER_MAX_TOKENS = min(384, MAX_TOKENS)

# Tool ta'riflarini OpenAI/Groq formatiga bir marta o'giramiz.
_tools = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in TOOLS
]

# Kategoriya -> tool nomlari. Router qaysi kategoriya keragini aytadi,
# Faza 2 faqat o'shalarni yuboradi (token tejash).
TOOL_CATEGORIES = {
    "web": ["web_search", "get_weather", "get_currency", "read_url"],
    "tg": ["tg_chats", "tg_read", "tg_send"],
    "file": ["read_file", "write_file", "list_files", "run_command"],
    "esl": [
        "set_reminder", "list_reminders", "set_prayer_reminders",
        "set_daily_prayers", "set_morning_brief",
        "set_recurring_reminder", "list_recurring", "cancel_recurring",
    ],
    "todo": ["add_todo", "list_todos", "complete_todo"],
    "xot": ["remember", "recall"],
}

_TOOL_RE = re.compile(r"<\s*TOOL\s*:?\s*([a-z, ]*)>?", re.IGNORECASE)

# Tool nomi -> kategoriyasi (router xatosidan kategoriya aniqlash uchun).
_TOOL2CAT = {t: c for c, ts in TOOL_CATEGORIES.items() for t in ts}


def _trim_history(msgs, each=500):
    """Eski xabarlarni qisqartiradi — to'liq matn tarixda shart emas."""
    return [
        {"role": m["role"], "content": (m["content"] or "")[:each]}
        for m in msgs
    ]


def build_system(router=False):
    """Qisqa system prompt. router=True bo'lsa kategoriya tanlash yo'rig'i qo'shiladi."""
    mems = [m[:80] for m in memory.all_memories(limit=6)]
    mem_text = "; ".join(mems) if mems else "yo'q"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    base = (
        "Sen JARVIS — shaxsiy AI yordamchisan (Iron Man uslubi). O'zbekcha, do'stona, aniq. "
        f"Hozir: {now}. "
        "Telegram chat: jadval/**/#/--- ISHLATMA, sof matn yoz, qisqa va foydali. "
        "Egangning shaxsiy Telegramini o'qiy olasan; xabar yuborishni tg_send tayyorlaydi, "
        "foydalanuvchi TUGMA bilan tasdiqlaydi (o'zing tasdiq so'rama). "
        "Fayl o'qish: D:\\Tolibjon ichida; yozish/buyruq: faqat workspace. "
        f"Eslaganlaring: {mem_text}"
    )
    if router:
        base += (
            "\n\nMUHIM: tool kerak bo'lsa boshqa HECH NARSA yozma, faqat <TOOL:kat> yoz. "
            "kat: web=internet qidiruv/ob-havo/valyuta kursi/havola(URL) o'qish, tg=shaxsiy Telegram suhbat/xabar, "
            "file=fayl/kod yozish/buyruq bajarish, "
            "esl=eslatma/namoz/avto-namoz/tonggi brifing/takroriy eslatma, "
            "todo=vazifalar ro'yxati (qo'shish/ko'rish/bajarildi), "
            "xot=eslab qolish yoki xotiradan izlash. "
            "Bir nechtasi kerak bo'lsa vergul bilan: <TOOL:web,esl>. "
            "Aks holda (suhbat, savol, maslahat) to'g'ridan-to'g'ri QISQA javob ber."
        )
    return base


def _subset_tools(cats):
    """Kategoriyalarga mos tool'larni qaytaradi; noaniq bo'lsa hammasini."""
    allowed = set()
    for c in cats:
        allowed.update(TOOL_CATEGORIES.get(c, []))
    if not allowed:
        return _tools
    return [t for t in _tools if t["function"]["name"] in allowed]


def _tool_loop(chat_id, history, user_text, cats):
    """Faza 2: tool aylanmasi — faqat kerakli kategoriya tool'lari bilan."""
    tools = _subset_tools(cats)
    messages = [{"role": "system", "content": build_system()}]
    messages += history
    messages.append({"role": "user", "content": user_text})

    final = ""
    for _ in range(15):
        try:
            resp = _create(
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_tokens=MAX_TOKENS,
            )
        except Exception as e:
            s = str(e)
            if "tool_use_failed" in s:
                # Model tool'ni buzib chaqirdi — tool'siz qayta so'raymiz.
                resp = _create(messages=messages, max_tokens=MAX_TOKENS)
            elif "output_parse_failed" in s:
                # Model mulohazasida adashdi — bir marta qayta urinamiz.
                resp = _create(
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    max_tokens=MAX_TOKENS,
                )
            else:
                raise
        msg = resp.choices[0].message

        if msg.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                result = execute_tool(tc.function.name, args, chat_id)
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result}
                )
            continue

        final = _clean(msg.content)
        break

    return final


def respond(chat_id, user_text):
    """Bitta xabarga javob. Avval arzon router, kerak bo'lsa kategoriyali tool aylanmasi."""
    history = _trim_history(memory.get_history(chat_id, limit=6))

    # --- Faza 1: arzon, tool'siz router ---
    p1_messages = [{"role": "system", "content": build_system(router=True)}]
    p1_messages += history
    p1_messages.append({"role": "user", "content": user_text})

    try:
        r1 = _create(messages=p1_messages, max_tokens=ROUTER_MAX_TOKENS)
        text1 = _clean(r1.choices[0].message.content)
    except Exception as e:
        s = str(e)
        # Ikkala holat ham "tool kerak" degani:
        #  - tool_use_failed: model marker o'rniga tool chaqirdi
        #  - output_parse_failed: model mulohazasida adashdi (odatda tool haqida)
        if "tool_use_failed" not in s and "output_parse_failed" not in s:
            raise
        # Xato matnidan kategoriyani topishga urinamiz:
        cat = ""
        mm = _TOOL_RE.search(s)  # ichida <TOOL:tg> yozilgan bo'lishi mumkin
        if mm and mm.group(1):
            c = mm.group(1).split(",")[0].strip().lower()
            if c in TOOL_CATEGORIES:
                cat = c
        if not cat:
            nm = re.search(r'"name":\s*"(\w+)"', s)
            name = (nm.group(1).lower() if nm else "")
            cat = name if name in TOOL_CATEGORIES else _TOOL2CAT.get(name, "")
        text1 = f"<TOOL:{cat}>"

    m = _TOOL_RE.search(text1)
    if text1 and not m:
        final = text1  # Oddiy suhbat — shu yerda tugadi (arzon).
    else:
        cats = []
        if m and m.group(1):
            cats = [c.strip().lower() for c in m.group(1).split(",")]
        final = _tool_loop(chat_id, history, user_text, cats)

    memory.add_message(chat_id, "user", user_text)
    memory.add_message(chat_id, "assistant", final)
    return final or "(javob bo'sh chiqdi)"
