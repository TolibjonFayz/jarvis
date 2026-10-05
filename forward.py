"""Forward qilingan xabar -> bir tugma bilan amal (kalendar/eslatma/vazifa/xarajat/xulosa).

Oqim: egasi xabarni FRIDAY'ga forward qiladi -> qisqa ko'rinish + tugmalar (eng mosi
⭐ — oddiy qoidalar, token sarflanmaydi) -> tugma bosilganda faqat o'sha amal uchun
model ishga tushadi (majburiy tool chaqiruvi bilan).
"""
import datetime
import itertools
import re

import agent
import memory

ACTIONS = {
    "kal": "📅 Kalendar",
    "esl": "⏰ Eslatma",
    "todo": "✅ Vazifa",
    "pul": "💸 Xarajat",
    "xulosa": "📝 Xulosa",
}

# sid -> {chat_id, text, sender, date, done:set}. Bot qayta yoqilsa — yo'qoladi.
PENDING = {}
_seq = itertools.count(1)

_TIME_RE = re.compile(
    r"\b\d{1,2}[:.]\d{2}\b|\bsoat\s*\d|ertaga|indinga|bugun|kechqurun|ertalab|"
    r"dushanba|seshanba|chorshanba|payshanba|juma|shanba|yakshanba|\d{1,2}[-\s](yanvar|fevral|"
    r"mart|aprel|may|iyun|iyul|avgust|sentabr|oktabr|noyabr|dekabr)",
    re.IGNORECASE,
)
_MEET_RE = re.compile(
    r"uchrash|ko.?rish|yig.?ilish|majlis|meeting|zoom|meet|tadbir|to.?y|kelaman|kelasizmi|"
    r"boramiz|kelinglar|kutaman|qabul",
    re.IGNORECASE,
)
_APOS = re.compile(r"['‘’ʻʼ`]")


def suggest(text):
    """Tugmalar tartibi: birinchisi — tavsiya (⭐)."""
    plain = _APOS.sub("", text or "")
    if len(text) > 400:
        first = "xulosa"  # uzun post — ichida vaqt/narx bo'lsa ham avval xulosa kerak
    elif agent._MONEY_RE.search(plain):
        first = "pul"
    elif _TIME_RE.search(text) and _MEET_RE.search(text):
        first = "kal"
    elif _TIME_RE.search(text):
        first = "esl"
    else:
        first = "todo"
    return [first] + [a for a in ACTIONS if a != first]


def sender_name(origin):
    """MessageOrigin* -> ism (bo'lmasa '')."""
    if origin is None:
        return ""
    user = getattr(origin, "sender_user", None)
    if user is not None:
        return user.full_name
    if getattr(origin, "sender_user_name", None):
        return origin.sender_user_name
    chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
    return getattr(chat, "title", "") or ""


def add(chat_id, text, sender, date):
    sid = next(_seq)
    PENDING[sid] = {"chat_id": chat_id, "text": text, "sender": sender, "date": date, "done": set()}
    return sid


def _context(item):
    """Model uchun: kim yozgan, qachon. Eski xabarda "ertaga" o'sha kunga nisbatan."""
    parts = []
    if item["sender"]:
        parts.append(f"Yuboruvchi: {item['sender']}.")
    d = item["date"]
    if d:
        local = d.astimezone().date() if d.tzinfo else d.date()
        days = (datetime.date.today() - local).days
        if days > 0:
            parts.append(
                f"Xabar {days} kun oldin ({local:%Y-%m-%d}) yozilgan — undagi 'ertaga', 'bugun' "
                "kabi so'zlar O'SHA sanaga nisbatan; date ni aniq YYYY-MM-DD qilib ber."
            )
    return " ".join(parts)


_PROMPTS = {
    "kal": ("kal", "Shu forward qilingan xabardan Google Calendar'ga tadbir qo'sh (calendar_add). "
                   "Nomi qisqa: yuboruvchi ma'lum bo'lsa '<Ism> bilan — <mavzu>' (masalan 'Aziz bilan — KP'). "
                   "Xabarda sana yoki vaqt bo'lmasa — qo'shma, qaysi kun/soatligini so'ra."),
    "esl": ("esl", "Shu forward qilingan xabar bo'yicha bir martalik eslatma qo'y (set_reminder). "
                   "Matni qisqa, nima qilish kerakligini aytsin. Vaqt yo'q bo'lsa — qachon eslatishni so'ra."),
    "todo": ("todo", "Shu forward qilingan xabardan vazifa qo'sh (add_todo) — qisqa, buyruq shaklida."),
}


def run(sid, action):
    """Tugma bosilganda (sinxron — bot asyncio.to_thread bilan chaqiradi). Javob matni."""
    item = PENDING.get(sid)
    if item is None:
        return "Bu forward eskirgan (bot qayta ishga tushgan bo'lishi mumkin) — qayta forward qil."
    chat_id, text = item["chat_id"], item["text"][:3000]
    ctx = _context(item)

    if action == "pul":
        out = agent._money_flow(chat_id, f"{ctx}\nXabar: «{text}»") or (
            "💸 Bu xabardan xarajat topilmadi (summa ko'rinmadi)."
        )
    elif action == "xulosa":
        resp = agent._create(
            messages=[
                {"role": "system", "content": "Forward qilingan xabarni o'zbekcha 2-4 gapda xulosa qil. "
                                              "Undan egasiga biror ish chiqsa (uchrashuv, to'lov, javob "
                                              "kutilyapti) — oxirida bitta qatorda ayt. Faqat xabarda bor narsa."},
                {"role": "user", "content": f"{ctx}\n\n{text}"},
            ],
            # gpt-oss avval mulohaza qiladi va u ham shu chegaraga kiradi — 400 da
            # xulosa yarmida uzilib qolardi.
            max_tokens=1000,
        )
        out = "📝 " + agent._clean(resp.choices[0].message.content)
    elif action in _PROMPTS:
        cat, instruction = _PROMPTS[action]
        out = agent._tool_loop(chat_id, [], f"{instruction}\n{ctx}\nXabar: «{text}»", [cat], require=True)
    else:
        return "Noma'lum amal."

    item["done"].add(action)
    memory.add_message(chat_id, "user", f"[Forward → {ACTIONS[action]}] {text[:300]}")
    memory.add_message(chat_id, "assistant", out)
    return out


def preview(text, sender):
    head = f"📨 **{sender}**:\n" if sender else "📨 Forward:\n"
    short = text if len(text) <= 300 else text[:300] + "…"
    return head + f"«{short}»\n\nNima qilay?"
