"""Qaysi Groq modeli TOOL'larni to'g'ri chaqirishini tekshiradi.
Ishlatish:  python test_tools.py
[OK] chiqqan modelni .env dagi MODEL= ga qo'ying.
"""
from groq import Groq
from config import GROQ_API_KEY

client = Groq(api_key=GROQ_API_KEY)

tools = [
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Foydalanuvchi haqidagi muhim faktni saqlaydi.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    }
]

CANDIDATES = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "moonshotai/kimi-k2-instruct",
    "qwen/qwen3-32b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]

print("Tool chaqirish tekshirilmoqda...\n")
good = []
for m in CANDIDATES:
    try:
        r = client.chat.completions.create(
            model=m,
            messages=[
                {"role": "user", "content": "Esla: mening ismim Ali. remember tool'ini ishlat."}
            ],
            tools=tools,
            tool_choice="auto",
            max_tokens=200,
        )
        msg = r.choices[0].message
        if msg.tool_calls:
            tc = msg.tool_calls[0]
            print(f"[OK]   {m} -> {tc.function.name}({tc.function.arguments})")
            good.append(m)
        else:
            print(f"[WARN] {m}: tool chaqirmadi (matn qaytardi)")
    except Exception as e:
        err = str(e).replace("\n", " ")
        print(f"[FAIL] {m}: {err[:110]}")

print("\n--- Natija ---")
if good:
    print(f"Tool'ni to'g'ri chaqiradigan model(lar): {', '.join(good)}")
    print(f"Tavsiya: .env da  MODEL={good[0]}  qilib qo'ying.")
else:
    print("Hech qaysi model tool'ni to'g'ri chaqirmadi.")
