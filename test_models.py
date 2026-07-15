"""Qaysi Groq modeli sizning kalitingizda ishlashini tekshiradi.
Ishlatish:  python test_models.py
Natijada ✅ chiqqan modelni .env dagi MODEL= ga qo'ying.
"""
from groq import Groq
from config import GROQ_API_KEY

client = Groq(api_key=GROQ_API_KEY)

CANDIDATES = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
    "moonshotai/kimi-k2-instruct",
    "qwen/qwen3-32b",
]

print("Tekshirilmoqda...\n")
working = []
for m in CANDIDATES:
    try:
        r = client.chat.completions.create(
            model=m,
            messages=[{"role": "user", "content": "bir so'z bilan javob ber: salom"}],
            max_tokens=20,
        )
        text = (r.choices[0].message.content or "").strip().replace("\n", " ")
        print(f"✅ {m}: ISHLAYDI -> {text[:40]!r}")
        working.append(m)
    except Exception as e:
        msg = str(e).replace("\n", " ")
        print(f"❌ {m}: {msg[:90]}")

print("\n--- Natija ---")
if working:
    print(f"Ishlaydigan model(lar): {', '.join(working)}")
    print(f"Tavsiya: .env da  MODEL={working[0]}  qilib qo'ying.")
else:
    print("Hech qaysi model ishlamadi — kalitni yoki internetni tekshiring.")
