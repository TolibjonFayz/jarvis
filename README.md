# FRIDAY — shaxsiy AI yordamchi (Telegram)

Iron Man'dagi F.R.I.D.A.Y.'ga o'xshagan shaxsiy yordamchi. Telegram orqali o'zbekcha
gaplashadi, xarajatlaringni hisoblaydi, sen haqingda eslab qoladi, kanallaringni
o'qib xulosa qiladi, loyihalaringni kuzatadi va kalendaringni yuritadi.
Faqat egasi (`OWNER_ID`) bilan gaplashadi.

**Miya:** Groq (tekin). **Rasm:** Gemini (tekin). **Ovoz:** Whisper + edge-tts (tekin).
Kompyuterda fonda ishlaydi — Windows'ga kirganda o'zi yonadi.

---

## Nima qila oladi

| Soha | Misol |
|---|---|
| 💬 Suhbat, kod | «Python'da fayl o'qish kodini yoz», «buni tushuntir» |
| 🧠 Aqlli xotira | O'zi eslab qoladi. «men haqimda nima bilasan?», «…ni unut» |
| 💸 Xarajatlar | «taksi 25 ming, obed 45k», «bu oy qancha sarfladim?» |
| 💰 Oylik budjet | «ovqatga oyiga 2 mln budjet», «budjetim qalay?» — 80%/100% da ogohlantiradi |
| 📅 Google Calendar | «ertaga 15:00 da Aziz bilan uchrashuv qo'sh», «bu hafta nima bor?» |
| ⏰ Eslatmalar | «30 daqiqadan keyin eslat», «har dushanba 18:00 yig'ilish» |
| ✅ Todo | «ro'yxatga qo'sh: kitob o'qish», «vazifalarim?» |
| 🕌 Namoz, ☀️ brifing | Har kuni namoz eslatmalari; ertalab ob-havo, namoz, kurs, kalendar, budjet, kechagi commitlar |
| 📰 Kanallar dayjesti | «kun.uz kanalini dayjestga qo'sh» — har kuni kechqurun xulosa, har band postga havola |
| 📥 Javobsiz xabarlar | «kimga javob bermadim?» — 12:00 va 19:00 da o'zi eslatadi |
| 👨‍💻 Loyihalar | «loyihalarim qanday?», «ERP'da shu oy nima o'zgardi?», «bugun nima qildim?» |
| 📱 Shaxsiy Telegram | Chatlarni o'qiydi; xabar yuborish faqat ✅ tugma bilan tasdiqlanganda |
| 🔍 Ma'lumot | Internet qidiruv, havola o'qish, ob-havo, Markaziy bank kursi |
| 📄 Hujjat, 🖼 rasm | PDF/DOCX/TXT xulosasi; rasm/chek/skrinshot (chek + «xarajatga qo'sh») |
| 🎤 Ovoz | Ovozli xabarni tushunadi, javobni ovoz bilan ham beradi |
| 🛡 Guruh moderatsiyasi | So'kinish, 18+ rasm/video, spamer, CAPTCHA, xavfli linklar |

**Buyruqlar:** `/start` · `/status` (holat, model statistikasi) · `/dayjest` · `/javobsiz` · `/reset`

---

## Qaysi ma'lumot qayerga ketadi

| Xizmat | Nima uchun | Nima boradi |
|---|---|---|
| Groq | Asosiy miya, xotira, dayjest, moderatsiya | Suhbat, xotira faktlari, o'qilgan chat/kanal matni |
| Gemini (tekin) | Faqat rasm ko'rish | **Faqat rasm + izoh.** Xotira, tarix, Telegram, xarajatlar YUBORILMAYDI |
| Google Calendar | Tadbirlar | Faqat `calendar.events` ruxsati |
| Hech qayerga | Javobsiz xabarlar, loyihalar (git), NSFW tekshiruv | Lokal hisoblanadi |

> Gemini tekin tarifida Google ma'lumotni o'qitishga ishlatadi va odamlar ko'rishi
> mumkin — FRIDAY'ga pasport, karta, parol yoki shaxsiy yozishma skrinshotini yuborma.

**Modellar** (Groq'da har modelning kunlik budjeti alohida):
- Suhbat: `openai/gpt-oss-120b` → limit tugasa `openai/gpt-oss-20b` → `qwen/qwen3.8-27b`
- Xotira va moderatsiya: `qwen/qwen3.8-27b` (asosiy budjetga tegmaydi)
- Rasm: `gemini-3.8-flash` → `3.7-flash` → `3.5-flash-lite` → `3.1-flash-lite`
- Ovoz: `whisper-large-v3` (o'zbekcha) + edge-tts `uz-UZ-MadinaNeural`

Groq modellari vaqti-vaqti bilan olib tashlanadi — ishlamay qolsa `python test_models.py`.

---

## O'rnatish

**1. Kalitlar (hammasi tekin):**
- Groq: https://console.groq.com/keys → `gsk_...`
- Telegram bot: **@BotFather** → `/newbot` → token
- Telegram ID'ing: **@userinfobot**

**2. Paketlar:**
```powershell
cd D:\Tolibjon\Claude\jarvis
pip install -r requirements.txt
```

**3. `.env`** — `.env.example` dan nusxa olib to'ldir (kamida `GROQ_API_KEY`,
`TELEGRAM_BOT_TOKEN`, `OWNER_ID`).

**4. Ishga tushirish:**
- Sinash uchun: `python bot.py`
- Doimiy (Windows'ga kirganda o'zi yonadi, yiqilsa qayta turadi, kompyuterni
  uxlashdan to'xtatadi):
  ```powershell
  powershell -ExecutionPolicy Bypass -File setup_autostart.ps1
  Start-ScheduledTask -TaskName FRIDAY
  ```
  Log: `data/bot.log`. O'chirish: `Unregister-ScheduledTask -TaskName FRIDAY`.

**Ixtiyoriy qismlar:**
- **Userbot** (chatlar, dayjest, javobsizlar): https://my.telegram.org → API development
  tools → `TG_API_ID`/`TG_API_HASH` `.env` ga → `python setup_userbot.py`
- **Rasm:** https://aistudio.google.com/apikey → `GEMINI_API_KEY`
- **Calendar:** [GCAL_SETUP.md](GCAL_SETUP.md) → `python setup_gcal.py`

---

## Tuzilma

```
bot.py        Telegram: handlerlar, buyruqlar, fon vazifalari (eslatma, dayjest, brifing)
agent.py      Miya: router + kategoriyali tool'lar, pul/majburiy yo'nalishlar
tools.py      43 ta tool ta'rifi va bajarilishi (xarajat, budjet, brifing...)
brain.py      Aqlli xotira: faktlarni ajratish, suhbat xulosasi
memory.py     SQLite (data/jarvis.db): tarix, faktlar, xarajat, budjet, kanallar...
digest.py     Kanallar dayjesti + javobsiz xabarlar
projects.py   Git loyihalar (faqat o'qish)
gcal.py       Google Calendar
vision.py     Gemini rasm ko'rish
voice.py      Whisper + edge-tts
userbot.py    Telethon: shaxsiy akkaunt
moderation.py, nsfw.py, security.py   Guruh himoyasi
fmt.py        Markdown -> Telegram HTML
net.py        IPv4-first (bu tarmoqda IPv6 osiladi)
run_forever.pyw, setup_autostart.ps1  Windows'da fonda ishlash
```

**Yangi imkoniyat qo'shish:** `tools.py` ga tool ta'rifi + bajarilishi → `agent.py`
dagi `TOOL_CATEGORIES` ga kategoriya → router matniga bir-ikki so'z.

**Ishonchlilik qoidalari** (tekin modellar gallyutsinatsiya qiladi — shu sabab):
- **Pul** xabarlari routerni chetlab o'tadi, model faqat tool tanlaydi, javob bazadan
  so'zma-so'z (aks holda summalarni buzar va «yozildi» deb yolg'on aytardi).
- **`FINAL`** belgili tool natijalari (dayjest, ro'yxatlar, kalendar, loyihalar) modelsiz beriladi.
- **Majburiy yo'nalishlar** (`_FORCED_ROUTES`): kanal, javobsiz, loyiha, kalendar so'zlari
  to'g'ri tool'ga boradi — router nomlarni o'ylab topardi.
- **Nisbiy sanalar** («ertaga», «juma») kodda hisoblanadi (`gcal.resolve_date`).
- `remember` faqat aniq «eslab qol» buyrug'ida; qolganini fondagi `brain.extract` qiladi.

---

## Guruh moderatori 🛡

Botni guruhga qo'shib **admin** qil (xabar o'chirish, ban, cheklash huquqlari bilan).

- **Matn:** so'zlar ro'yxati (bir zumda) + AI (`qwen3.8-27b`) nozik haqoratlar uchun.
- **Rasm/video/stiker:** lokal NudeNet (offline, hech qayerga yuborilmaydi). Video:
  muqova + `MOD_VIDEO_MAX_MB` gacha bo'lsa userbot orqali 6 kadr. Ulkan videolar
  yuklanmaydi; `MOD_BLOCK_BIG_VIDEO=1` bo'lsa o'chiriladi.
- **Yangi a'zo:** CAS spamer bazasi, 18+ profil rasmi, CAPTCHA («Men odamman»).
- **Linklar:** IP-manzil, scam iboralar, `data/blocklist.txt` dagi domenlar.
- **Chora:** `MOD_WARN_LIMIT` (2) ogohlantirish, keyin ban. Egasi va adminlarga tegilmaydi.

> CAPTCHA'ni sinash uchun ikkinchi akkaunt kerak (guruh yaratuvchisini cheklab bo'lmaydi).
> NudeNet ~95% aniq — shuning uchun darrov ban emas, ogohlantirish bor.

---

## ⚠️ Xavfsizlik

- `data/` papkasi git'ga tushmaydi: `userbot.session` (akkauntingga to'liq kirish!),
  Google token, baza. Hech kimga berma.
- `run_command` haqiqiy buyruq bajaradi (faqat `workspace/` ichida, faqat egasi uchun).
- Userbot sessiyasini bir vaqtda ikki joyda ishlatma — Telegram sessiyani bekor qilishi mumkin.
- Telegram ommaviy avtomatik xabarlarni ban qiladi — userbot faqat yakka xabar uchun.
- `DEPLOY_RAILWAY.md`, `Procfile`, `nixpacks.toml` — eski server rejasi, hozir ishlatilmaydi.
