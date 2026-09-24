"""Jonli sifat sinovi: HAQIQIY Groq bilan tipik so'rovlar, to'g'ri tool chaqirildimi.

Token sarflaydi (~20-40K) — faqat katta o'zgarishdan keyin ishga tushir:
    python evals/live_eval.py            # hammasi
    python evals/live_eval.py 1 4        # faqat 1- va 4-holat

Vaqtinchalik baza, soxta kalendar; userbot ishlatilmaydi — haqiqiy ma'lumotlarga tegmaydi.
Natija oxirida: o'tdi/yiqildi va shu sinovga ketgan token.
"""
import os
import re
import sys
import tempfile
import time
from types import SimpleNamespace as NS

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="friday-eval-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent  # noqa: E402
import brain  # noqa: E402
import gcal  # noqa: E402
import memory  # noqa: E402

CHAT = 777
PAUSE = 4  # daqiqalik limitni urmaslik uchun

# (so'rov, chaqirilishi SHART tool'lar, chaqirilmasligi SHART tool'lar, javobda bo'lishi kerak regex)
CASES = [
    ("salom, qalaysan?", set(), {"set_reminder", "add_expense"}, r"[a-zA-Z']"),
    ("python'da list comprehension nima? bitta misol", set(), set(), r"\["),
    ("taksi 25 ming, obed 45k", {"add_expense"}, set(), r"70 000"),
    ("bu oy qancha sarfladim?", {"expense_report"}, set(), r"70 000"),
    ("ertaga soat 9 da dori ichishni eslat", {"set_reminder"}, {"set_recurring_reminder"}, None),
    ("eslatmalarim", {"list_reminders"}, set(), r"dori"),
    ("dollar kursi qancha?", {"get_currency"}, set(), r"\d"),
    ("bu hafta nima bor?", {"agenda"}, set(), None),
    ("juma kuni soat 15:00 da ERP demo qo'sh", {"calendar_add"}, set(), r"Ju "),
    ("eslatmalarni hammasini o'chir", {"cancel_reminder"}, set(), None),
]


def fake_calendar():
    added = []

    class Ev:
        def list(self, **kw):
            return NS(execute=lambda: {"items": []})

        def insert(self, calendarId, body):
            added.append(body)
            return NS(execute=lambda: {"htmlLink": ""})

    gcal._svc = lambda: NS(events=lambda: Ev())
    gcal.available = lambda: True
    return added


def main(selected):
    memory.init_db()
    brain.after_turn = lambda *a, **k: None
    fake_calendar()
    called = []
    real_exec = agent.execute_tool
    agent.execute_tool = lambda name, args, chat_id=None: (called.append(name), real_exec(name, args, chat_id))[1]
    # Pul oqimi execute_tool'ni agent orqali chaqiradi — o'sha ham ushlanadi.

    passed = 0
    runs = [(i, c) for i, c in enumerate(CASES, 1) if not selected or i in selected]
    for i, (text, must, forbid, pattern) in runs:
        called.clear()
        t = time.time()
        try:
            out = agent.respond(CHAT, text)
        except Exception as e:
            out = f"XATO: {e}"
        problems = []
        if must - set(called):
            problems.append(f"chaqirilmadi: {sorted(must - set(called))}")
        if forbid & set(called):
            problems.append(f"keraksiz: {sorted(forbid & set(called))}")
        if pattern and not re.search(pattern, out):
            problems.append(f"javobda yo'q: {pattern}")
        ok = not problems
        passed += ok
        print(f"{'✅' if ok else '❌'} {i:2}. {text[:45]:45} {time.time() - t:4.1f}s  tools={called}")
        if not ok:
            print(f"      {'; '.join(problems)}\n      javob: {out[:160]!r}")
        time.sleep(PAUSE)

    used = memory.usage_since(1)
    print(f"\n{passed}/{len(runs)} o'tdi · tokenlar: " +
          ", ".join(f"{m.split('/')[-1]}={t}" for m, t in used.items()))
    print("Model:", agent.STATS["calls"], "| limitga urildi:", agent.STATS["rate_limited"])
    return passed == len(runs)


if __name__ == "__main__":
    sel = {int(a) for a in sys.argv[1:] if a.isdigit()}
    sys.exit(0 if main(sel) else 1)
