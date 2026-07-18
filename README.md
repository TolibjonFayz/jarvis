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

## Userbot: shaxsiy akkaunt (2-bosqich) ✅

JARVIS sening SHAXSIY Telegram akkauntingdan suhbatlarni o'qiy oladi va
(faqat sen tasdiqlaganingdan keyin!) xabar yubora oladi.

**Ulash (bir marta):**
1. https://my.telegram.org ga kir (o'z raqaming bilan)
2. **API development tools** → ilova yarat (nomi ixtiyoriy) → `api_id` va `api_hash` beradi
3. `.env` ga qo'sh:
   ```
   TG_API_ID=1234567
   TG_API_HASH=abcdef1234567890
   ```
4. Terminalda: `python setup_userbot.py` → telefon raqam (+998...) → Telegram'dan
   kelgan kod (2FA bo'lsa parol ham)
5. Botni qayta ishga tushir: `python bot.py`

**Tool'lar:** `tg_chats` (suhbatlar), `tg_read` (xabarlarni o'qish),
`tg_send` + `tg_confirm` (xabar yuborish — 2 bosqichli, tasdiqsiz KETMAYDI).

⚠️ **Diqqat:**
- `data/userbot.session` fayli — akkauntingga to'liq kirish kaliti. Hech kimga berma!
- Telegram spam/avtomatik ommaviy xabarlarni ban qiladi. JARVIS'ni faqat o'qish va
  yakka xabarlar uchun ishlat — ommaviy yuborish qildirma.

## Guruh moderatori 🛡️

Botni guruhga qo'shsang, so'kinish/haqoratli xabarlarni avtomatik o'chiradi,
buzg'unchini ogohlantiradi va takrorlansa guruhdan chiqaradi.

**Qanday ulash:**
1. Botni guruhga qo'sh
2. Botni **admin** qil, quyidagi huquqlar bilan:
   - **Delete messages** (xabar o'chirish)
   - **Ban users** (a'zolarni chiqarish)
3. Tayyor — bot avtomatik ishlaydi. Sozlash shart emas.

**Nimalarni tekshiradi:**
- **Matn** — so'kinish/haqorat: (1) so'zlar ro'yxati (bepul, bir zumda);
  (2) AI tahlil (`llama-3.1-8b-instant`, alohida budjet) — nozik haqoratlar
- **Rasm/video/sticker** — 18+ (nude/shahvoniy) kontent: lokal NudeNet
  (bepul, offline, Groq token yemaydi, rasm hech qayerga yuborilmaydi)
- **Yangi a'zo** — qo'shilganda profil rasmi 18+ ga tekshiriladi
- Rasm ostidagi yozuv (caption) so'kinishlari ham tekshiriladi

**Chora:**
- 1-2 buzilish: xabar o'chiriladi + ogohlantirish (`MOD_WARN_LIMIT`, standart 2)
- Keyingisi: guruhdan chiqariladi + sabab yoziladi
- **Egasi (OWNER_ID) va guruh adminlari tegilmaydi**
- Guruh xabarlari JARVIS "miya"siga bormaydi — faqat moderatsiya (token tejash)

### Xavfsizlik (yangi a'zolar + linklar)

- 🛡️ **CAS** — yangi a'zoni ma'lum spamerlar bazasidan tekshiradi (bepul, api.cas.chat).
  Spamer bo'lsa darrov chiqariladi.
- 🤖 **Kirish CAPTCHA** — yangi a'zoning ovozi o'chiriladi; `MOD_CAPTCHA_SEC` soniya ichida
  "Men odamman" tugmasini bosmasa chiqariladi. Botlarni to'xtatadi.
- 🔞 **Profil rasm** — yangi a'zoning profil rasmi 18+ bo'lsa chiqariladi.
- 🔗 **Xavfli linklar** — IP-manzilli, scam (free crypto/airdrop), yoki qora ro'yxatdagi
  domenli linklar o'chiriladi + ogohlantiriladi. Qora ro'yxat: `data/blocklist.txt`
  (har qatorda bitta domen).

**Kerakli admin huquqlari:** xabar o'chirish, a'zolarni chiqarish (ban),
a'zolarni cheklash (mute — CAPTCHA uchun).

> ⚠️ CAPTCHA'ni sinash uchun **ikkinchi akkaunt** kerak — guruh yaratuvchisini
> (egasini) Telegram cheklashga ruxsat bermaydi.

**Video tekshiruvi (2 qatlam):**
- **Muqova (thumbnail)** — barcha videolar uchun, tez (bot orqali).
- **Chuqur skaner** — hajmi `MOD_VIDEO_MAX_MB` (standart 50MB) gacha videolar
  userbot orqali yuklanib, 6 ta kadr namunasi tekshiriladi (opencv). Shu bilan 18+
  narsa videoning o'rtasida bo'lsa ham topiladi.
- **Ulkan videolar** (masalan 1GB) — YUKLANMAYDI (kompyuter + DoS himoyasi).
  Faqat muqova tekshiriladi. `MOD_BLOCK_BIG_VIDEO=1` qo'ysang — tekshirib
  bo'lmaydigan katta videolar avtomatik o'chiriladi (qattiq siyosat).

**Cheklovlar (halol):**
- NudeNet ~95% aniq — kamdan-kam yanglishishi mumkin. Shuning uchun darrov ban
  emas, ogohlantirish tizimi bor.
- Ochiqroq (bikini/plaj) rasmlar odatda o'tadi; juda ochiq bo'lsa `nsfw.py` dagi
  `_THRESHOLD` bilan sozlanadi.
- Chuqur video skaner userbot ulanган bo'lishini talab qiladi (2-bosqich).

## Ovoz — gaplashadigan JARVIS 🎤

Shaxsiy chatda **ovozli xabar** yuborsang:
1. JARVIS tushunadi (Groq Whisper — tekin, alohida budjet)
2. Nima eshitganini ko'rsatadi: 🎤 «...»
3. Javobni **matn + OVOZ** bilan qaytaradi (edge-tts, o'zbek ovozi — Sardor)

Kod bloklari va linklar ovozda o'qilmaydi ("kod yozdim, chatda ko'ring" deydi).

**Sozlash (.env, ixtiyoriy):**
```
VOICE_REPLY=1                    # 0 = faqat matn, ovozsiz javob
VOICE_NAME=uz-UZ-SardorNeural    # yoki uz-UZ-MadinaNeural (ayol ovozi)
VOICE_LANG=uz                    # '' = til avto-aniqlash (ruscha/inglizcha uchun)
```

> Halol eslatma: Whisper'ning o'zbekchasi mukammal emas — ba'zi so'zlarni xato
> yozishi mumkin. Aniq va sekin gapirsang yaxshi tushunadi, JARVIS miyasi esa
> kichik xatolarni kontekstdan tushunib ketadi.

## Kundalik avto-funksiyalar ⚡

JARVIS'ga yozib yoqasan (bir marta):
- **Avto-namoz:** «har kunga namoz eslatmasini yoq» → har kuni ertalab o'zi qo'yadi
- **Tonggi brifing:** «tonggi brifingni yoq» → har kuni soat `BRIEF_HOUR` (standart 7:00) da
  ob-havo + namoz vaqtlari + valyuta + bugungi eslatmalarni bitta xabar qilib yuboradi
- **Valyuta:** «dollar kursi qancha?» → Markaziy bank rasmiy kursi (tekin)

Sozlash: `.env` da `BRIEF_HOUR=7`, `TZ_OFFSET=5` (Toshkent).

## Link / hujjat o'quvchi 🔗

- **Link:** «bu maqolani o'qib ber https://...» → sahifani ochib, asosiy matnini
  o'qiydi va xulosa qiladi (trafilatura).
- **Hujjat:** shaxsiy chatga **PDF / DOCX / TXT** tashlasang → matnini ajratib,
  qisqacha mazmunini aytadi (pypdf + python-docx).

> Skanerlanган (rasm) PDF'lardan matn chiqmaydi — faqat matnli hujjatlar.

## Todo + takroriy eslatma ✅

- **Vazifalar (todo):** «ro'yxatga qo'sh: kitob o'qish» → «vazifalarim?» → «1-chisini bajardim»
- **Takroriy eslatma:** «har kuni 9:00 da tabletka ichishni eslat», «har dushanba 18:00 yig'ilish»
  → o'z vaqtida takrorlanib keladi. Ko'rish: «takroriy eslatmalarim?», o'chirish raqami bo'yicha.

## Keyingi bosqichlar (g'oyalar)

- **Boshqa tool'lar:** yangiliklar, tarjima, kalkulyator va h.k.
- **24/7 server** — Railway (DEPLOY_RAILWAY.md)

---

## ⚠️ Xavfsizlik eslatmasi

`run_command` tool'i haqiqiy buyruqlarni bajaradi. Faqat egasi (OWNER_ID) bilan
gaplashadi va faqat `workspace/` ichida ishlaydi, lekin baribar o'z kompyuteringda
ehtiyot bo'l. Botni notanish odamlarga ochma.
"# jarvis" 
