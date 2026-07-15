"""Miya: Groq'ni chaqiradi. Token tejash uchun 2 fazali:
Faza 1 (tool'siz, arzon) — oddiy suhbat shu yerda tugaydi.
Faza 2 (tool bilan) — faqat rostdan tool kerak bo'lganda."""
import json
import datetime

from groq import Groq

import memory
from config import GROQ_API_KEY, MODEL, MAX_TOKENS
from tools import TOOLS, execute_tool

# max_retries=1: 429 bo'lsa retry-storm budjetni yemasin.
client = Groq(api_key=GROQ_API_KEY, max_retries=1) if GROQ_API_KEY else None

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

TOOL_MARKER = "<TOOL>"


def build_system(router=False):
    """Qisqa system prompt (token tejash). router=True bo'lsa tool kerak-emasligini
    aniqlaydigan qo'shimcha yo'riqnoma qo'shiladi."""
    mems = memory.all_memories(limit=6)
    mem_text = "; ".join(mems) if mems else "yo'q"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    base = (
        "Sen JARVIS — shaxsiy AI yordamchisan (Iron Man uslubi). O'zbekcha, do'stona, aniq. "
        f"Hozir: {now}. "
        "Telegram chat: jadval/**/#/--- ISHLATMA, sof matn yoz, qisqa va foydali. "
        f"Foydalanuvchi haqida eslaganlaring: {mem_text}"
    )
    if router:
        base += (
            "\n\nMUHIM: agar javob uchun JONLI ma'lumot (internet qidiruv yoki ob-havo), "
            "ESLATMA qo'yish, yoki FAYL/BUYRUQ bilan ishlash kerak bo'lsa — boshqa hech narsa "
            f"yozma, faqat shu belgini yoz: {TOOL_MARKER}\n"
            "Aks holda (oddiy suhbat, savol, fikr, kod maslahati) — to'g'ridan-to'g'ri javob ber."
        )
    return base


def _tool_loop(chat_id, history, user_text):
    """Faza 2: to'liq tool aylanmasi."""
    messages = [{"role": "system", "content": build_system()}]
    messages += history
    messages.append({"role": "user", "content": user_text})

    final = ""
    for _ in range(15):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=_tools,
                tool_choice="auto",
                max_tokens=MAX_TOKENS,
            )
        except Exception as e:
            # Model tool'ni buzib chaqirsa — tool'siz qayta so'raymiz.
            if "tool_use_failed" in str(e):
                resp = client.chat.completions.create(
                    model=MODEL, messages=messages, max_tokens=MAX_TOKENS
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

        final = msg.content or ""
        break

    return final


def respond(chat_id, user_text):
    """Bitta xabarga javob. Avval arzon (tool'siz), kerak bo'lsa tool aylanmasi."""
    history = memory.get_history(chat_id, limit=6)

    # --- Faza 1: arzon, tool'siz ---
    p1_messages = [{"role": "system", "content": build_system(router=True)}]
    p1_messages += history
    p1_messages.append({"role": "user", "content": user_text})

    r1 = client.chat.completions.create(
        model=MODEL, messages=p1_messages, max_tokens=MAX_TOKENS
    )
    text1 = (r1.choices[0].message.content or "").strip()

    if text1 and TOOL_MARKER not in text1.upper():
        final = text1  # Oddiy suhbat — shu yerda tugadi (arzon).
    else:
        # --- Faza 2: tool kerak ---
        final = _tool_loop(chat_id, history, user_text)

    memory.add_message(chat_id, "user", user_text)
    memory.add_message(chat_id, "assistant", final)
    return final or "(javob bo'sh chiqdi)"
