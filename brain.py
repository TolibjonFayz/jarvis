"""Aqlli xotira: suhbatdan faktlarni o'zi ajratadi, keraklisini topadi, eski
suhbatni xulosaga aylantiradi.

- extract: har EXTRACT_EVERY ta foydalanuvchi xabaridan keyin fonda suhbatni
  ko'rib, uzoq muddatli faktlarni qo'shadi / yangilaydi / o'chiradi.
- relevant_facts: har doim muhim faktlar + joriy xabarga mos keladiganlari
  (so'z boshlari bo'yicha — Groq'da embedding yo'q, faktlar soni kichik).
- summarize: oyna (agent HISTORY_WINDOW) dan chiqib ketgan eski xabarlar
  qisqa xulosaga yig'iladi — bot mavzuni tez unutmasin.

Hammasi ALOHIDA modelda (qwen) — asosiy gpt-oss-120b budjetiga tegmaydi.
"""
import json
import logging
import re
import threading

from groq import Groq, RateLimitError

import memory
from config import GROQ_API_KEY

log = logging.getLogger("jarvis")

BRAIN_MODELS = ["qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
EXTRACT_EVERY = 3        # nechta yangi foydalanuvchi xabaridan keyin ajratish
SUMMARIZE_MIN = 8        # oynadan chiqqan nechta xabar yig'ilsa xulosa
SUMMARY_MAX_CHARS = 600
FACT_MAX_CHARS = 120
CATEGORIES = ["shaxsiy", "oila", "ish", "loyiha", "afzallik", "odamlar", "reja", "boshqa"]

client = Groq(api_key=GROQ_API_KEY, max_retries=0) if GROQ_API_KEY else None
_lock = threading.Lock()
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_WORD_RE = re.compile(r"[a-zа-яёқғўҳ']+", re.IGNORECASE)
_APOS_RE = re.compile(r"[‘’ʻʼ`]")


def _chat(system, user, max_tokens=700):
    last = None
    for m in BRAIN_MODELS:
        try:
            r = client.chat.completions.create(
                model=m,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=0,
            )
            return _THINK_RE.sub("", r.choices[0].message.content or "").strip()
        except RateLimitError as e:
            last = e
    raise last


def _json(text):
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# --- Kerakli faktlarni topish ---

def _stems(text):
    """So'z boshlari (3 harf): o'zbekcha qo'shimchalar ("ukam", "ukasi" ~ "uka")."""
    text = _APOS_RE.sub("'", (text or "").lower())
    return {w[:3] for w in _WORD_RE.findall(text) if len(w) >= 3}


ALL_FACTS_UPTO = 25      # shuncha faktgacha hammasi beriladi (~400 token)


def relevant_facts(user_text, core=6, related=6):
    """Faktlar kam bo'lsa — hammasi; ko'p bo'lsa muhimlari + xabarga moslari."""
    facts = memory.list_memories()
    if len(facts) <= ALL_FACTS_UPTO:
        return [f["text"] for f in facts]
    core_facts = [f for f in facts if f["importance"] >= 3][:core]
    chosen = {f["id"] for f in core_facts}
    q = _stems(user_text)
    scored = []
    for f in facts:
        if f["id"] in chosen:
            continue
        overlap = len(q & _stems(f["text"]))
        if overlap:
            scored.append((overlap, f["importance"], f["id"], f))
    scored.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    return [f["text"] for f in core_facts] + [s[3]["text"] for s in scored[:related]]


def summary(chat_id):
    return memory.get_setting(chat_id, "conv_summary", "") or ""


# --- Faktlarni ajratish ---

_EXTRACT_SYSTEM = (
    "Sen xotira menejerisan. Egasi (foydalanuvchi) va uning AI yordamchisi JARVIS suhbatidan "
    "egasi haqida UZOQ MUDDAT foydali faktlarni ajratasan.\n"
    "SAQLA: ism, oila va yaqinlar, yashash joyi, ishi, loyihalari, ko'nikmalari, "
    "afzalliklari/odatlari (nima yoqadi/yoqmaydi), rejalari va maqsadlari, "
    "tanishlari (kim kim), muhim sanalar.\n"
    "SAQLAMA: salomlashish, bir martalik savollar, ob-havo, valyuta, xarajatlar va "
    "eslatmalar (ular alohida saqlanadi), JARVISning o'zi haqidagi gaplar, taxminlar, "
    "vaqtinchalik holat (charchadim, hozir ovqatlanyapman).\n"
    "Faktni o'zbek tilida, qisqa (100 belgigacha), egasi haqida uchinchi shaxssiz yoz: "
    "'Ismi Tolibjon', 'Ukasi Aziz, 20 yosh', 'Qahvani shakarsiz ichadi'.\n"
    "Mavjud faktlar ro'yxati beriladi. Yangi ma'lumot mavjud faktni aniqlashtirsa yoki "
    "o'zgartirsa — update qil (yangi fakt qo'shma). Egasi biror faktni noto'g'ri desa yoki "
    "unutishni so'rasa — delete qil. Takror qo'shma.\n"
    f"category: {', '.join(CATEGORIES)}. "
    "importance: 3=har doim kerak (ism, oila a'zolari, asosiy ish), 2=foydali "
    "(loyihalar, afzalliklar), 1=mayda.\n"
    "Faqat JSON qaytar: {\"ops\": [{\"op\": \"add\", \"text\": \"...\", \"category\": \"...\", "
    "\"importance\": 2}, {\"op\": \"update\", \"id\": 5, \"text\": \"...\"}, "
    "{\"op\": \"delete\", \"id\": 7}]}. Hech narsa bo'lmasa: {\"ops\": []}"
)


def _facts_block(facts):
    if not facts:
        return "(yo'q)"
    return "\n".join(f"#{f['id']} [{f['category']}] {f['text']}" for f in facts)


def extract(chat_id, force=False):
    """Oxirgi ajratishdan keyingi suhbatdan faktlarni yangilaydi."""
    upto = int(memory.get_setting(chat_id, "extract_upto", "0") or 0)
    msgs = memory.history_after(chat_id, upto)
    users = [m for m in msgs if m["role"] == "user"]
    if not users or (len(users) < EXTRACT_EVERY and not force):
        return 0

    dialog = "\n".join(
        f"{'Ega' if m['role'] == 'user' else 'JARVIS'}: "
        f"{m['content'][:400] if m['role'] == 'user' else m['content'][:150]}"
        for m in msgs
    )
    facts = memory.list_memories()
    prompt = f"Mavjud faktlar:\n{_facts_block(facts)}\n\nYangi suhbat:\n{dialog}"
    data = _json(_chat(_EXTRACT_SYSTEM, prompt))
    memory.set_setting(chat_id, "extract_upto", msgs[-1]["id"])
    if not data:
        return 0
    return apply_ops(data.get("ops") or [], {f["id"] for f in facts})


def apply_ops(ops, known_ids):
    n = 0
    for op in ops:
        if not isinstance(op, dict):
            continue
        kind = op.get("op")
        text = (op.get("text") or "").strip()[:FACT_MAX_CHARS]
        cat = op.get("category") if op.get("category") in CATEGORIES else None
        try:
            imp = min(max(int(op.get("importance", 2)), 1), 3)
        except (TypeError, ValueError):
            imp = 2
        fid = op.get("id")
        if kind == "add" and text and not memory.memory_exists(text):
            memory.add_memory(text, cat or "boshqa", imp)
            n += 1
        elif kind == "update" and fid in known_ids and text:
            memory.update_memory(fid, text, cat, op.get("importance") and imp)
            n += 1
        elif kind == "delete" and fid in known_ids:
            memory.delete_memory(fid)
            n += 1
    if n:
        log.info("Xotira yangilandi: %d ta o'zgarish", n)
    return n


# --- Suhbat xulosasi ---

_SUMMARY_SYSTEM = (
    "Suhbat xulosasini yangila. Oldingi xulosa va yangi xabarlar beriladi. Natija: "
    f"o'zbekcha, {SUMMARY_MAX_CHARS} belgigacha, faqat keyingi suhbatga kerakli narsalar "
    "(qaysi mavzular, nima kelishildi, nima ochiq qoldi). Salomlashish, ob-havo kabi "
    "arzimas narsalarni tashla. Faqat xulosa matnini yoz."
)


def summarize(chat_id, window):
    """Oynadan (oxirgi `window` xabar) chiqib ketgan xabarlarni xulosaga qo'shadi."""
    upto = int(memory.get_setting(chat_id, "summary_upto", "0") or 0)
    msgs = memory.history_after(chat_id, upto)
    old = msgs[:-window] if window else msgs
    if len(old) < SUMMARIZE_MIN:
        return False
    old = old[:40]
    dialog = "\n".join(
        f"{'Ega' if m['role'] == 'user' else 'JARVIS'}: {m['content'][:300]}" for m in old
    )
    prompt = f"Oldingi xulosa:\n{summary(chat_id) or '(yo`q)'}\n\nYangi xabarlar:\n{dialog}"
    text = _chat(_SUMMARY_SYSTEM, prompt, max_tokens=500)
    if text:
        memory.set_setting(chat_id, "conv_summary", text[:SUMMARY_MAX_CHARS])
    memory.set_setting(chat_id, "summary_upto", old[-1]["id"])
    return True


def after_turn(chat_id, window):
    """Javobdan keyin fonda: faktlar + xulosa. Javobni kechiktirmaydi."""
    if client is None:
        return

    def run():
        if not _lock.acquire(blocking=False):
            return  # oldingisi hali ishlayapti — keyingi safar ushlaydi
        try:
            extract(chat_id)
            summarize(chat_id, window)
        except Exception as e:
            log.warning("Aqlli xotira xatosi: %s", str(e)[:200])
        finally:
            _lock.release()

    threading.Thread(target=run, daemon=True).start()
