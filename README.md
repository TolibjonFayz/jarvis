# JARVIS — shaxsiy AI yordamchi (Telegram bot, Groq)

Iron Man'ning JARVIS'iga o'xshagan shaxsiy AI agent. Telegram orqali gaplashadi,
kod yozadi, fikr aytadi, fayllar bilan ishlaydi va sen haqingda eslab qoladi.
**Miya: Groq (tekin API, dunyoning hamma yeridan ishlaydi).**

## Nima qila oladi

- 💬 Suhbat — model bilan gaplashish, fikr/g'oya olish
- 💻 Kod yozish — `workspace/` papkasida fayl yaratadi/o'qiydi, buyruq bajaradi
- 🔍 Internet qidiruv — DuckDuckGo orqali dolzarb ma'lumot
- 🌤️ Ob-havo — istalgan shahar uchun
- ⏰ Eslatma — vaqti kelganda Telegram'ga o'zi yozadi
- 🧠 Xotira — sen haqingda va joriy suhbatni eslab qoladi (SQLite)
- 🔒 Xavfsizlik — faqat sen (OWNER_ID) bilan gaplashadi

**Tool'lar:** read_file, write_file, list_files, run_command, remember, recall,
web_search, get_weather, set_reminder, list_reminders

---

## O'rnatish (bosqichma-bosqich)

### 1. Kerakli 3 ta narsa

**a) Groq API kaliti — TEKIN, karta shart emas**
1. https://console.groq.com/keys ga kir (Google/email bilan ro'yxatdan o't)
2. **Create API Key** → nusxa ol (`gsk_...`)

**b) Telegram bot token**
1. Telegram'da **@BotFather** ni ochib `/newbot` yoz
2. Botga ism va username ber → token beradi (`123456:ABC...`)

**c) O'zingning Telegram ID'ing**
1. Telegram'da **@userinfobot** ga yoz → `Id: 123456789` beradi

### 2. Python paketlarini o'rnatish

```powershell
cd D:\Tolibjon\Claude\jarvis
pip install -r requirements.txt
```

### 3. Sozlash

`.env.example` dan nusxa olib `.env` fayl yasang va to'ldiring:

```
GROQ_API_KEY=gsk_...
TELEGRAM_BOT_TOKEN=123456789:ABC...
OWNER_ID=123456789
MODEL=openai/gpt-oss-120b
```

### 4. Ishga tushirish

```powershell
python bot.py
```

Endi Telegram'da botingga `/start` yoz va gaplash!

> Model ishlamasa: `python test_models.py` ni ishga tushiring — qaysi model
> ishlashini aytadi, o'shani `.env` dagi `MODEL=` ga qo'ying.

---

## Narx haqida

**Groq tekin darajasi (free tier) bor** — karta shart emas, geografik cheklovsiz.
Faqat so'rov chegarasi bor (daqiqada/kunda), shaxsiy foydalanishga bemalol yetadi.

| Model | Tavsif |
|-------|--------|
| `openai/gpt-oss-120b` | Tool uchun eng ishonchli, kuchli (tavsiya) |
| `openai/gpt-oss-20b` | Tezroq, yengilroq |
| `qwen/qwen3-32b` | Yaxshi muqobil |

> `llama-3.3-70b` tool chaqirishни ba'zan buzib yuboradi (`tool_use_failed`) —
> shuning uchun `gpt-oss` tavsiya etiladi.

---

## Qanday ishlaydi (tuzilma)

```
bot.py       -> Telegram: xabar qabul qiladi/yuboradi
agent.py     -> Groq'ni tool'lar bilan aylanma chaqiradi (miya)
tools.py     -> Qo'llar: read_file, write_file, run_command, remember, recall
memory.py    -> Xotira: suhbat tarixi + uzoq muddatli eslab qolish
config.py    -> Sozlamalar (.env dan)
workspace/   -> Agent kod yozadigan papka (xavfsiz qamalgan)
data/        -> Xotira bazasi (jarvis.db)
```

**Modul dizayn:** miyani almashtirmoqchi bo'lsang (Claude, Gemini, Ollama...),
faqat `agent.py` o'zgaradi — bot, tool'lar, xotira o'z holicha qoladi.
Har yangi imkoniyat = yangi **tool** (`tools.py` ga qo'shasan).

---

## Keyingi bosqichlar (g'oyalar)

- **2-bosqich:** Telegram *userbot* (Telethon) — o'z akkauntingdan xabar o'qish/yuborish
- **3-bosqich:** Ovoz — Whisper (nutq→matn) + TTS (matn→ovoz)
- **Boshqa tool'lar:** internetdan qidirish, kalendar, eslatma, ob-havo va h.k.

---

## ⚠️ Xavfsizlik eslatmasi

`run_command` tool'i haqiqiy buyruqlarni bajaradi. Faqat egasi (OWNER_ID) bilan
gaplashadi va faqat `workspace/` ichida ishlaydi, lekin baribar o'z kompyuteringda
ehtiyot bo'l. Botni notanish odamlarga ochma.
"# jarvis" 
