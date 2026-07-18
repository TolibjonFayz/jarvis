# JARVIS'ni Railway'ga qo'yish (24/7)

Bosqichma-bosqich. Eng muhim 2 narsa allaqachon kodda hal qilingan:
**doimiy disk** (`DATA_DIR`) va **string sessiya** (`TG_SESSION`).

---

## 1. String sessiya yaratish (lokalda, bir marta)

Serverda userbot uchun fayl session ishlamaydi (disk o'chib ketadi). Shuning uchun
sessiyani STRING qilib olamiz:

```powershell
cd D:\Tolibjon\Claude\jarvis
python gen_session.py
```
Telefon raqam (+998...) + Telegram kod → oxirida **uzun string** chiqadi.
Uni nusxa olib qo'ying — bu `TG_SESSION` qiymati bo'ladi.

> ⚠️ Bu string akkauntingizga to'liq kirish beradi — hech kimga bermang!

---

## 2. Kodni GitHub'ga yuklash

`.gitignore` allaqachon `.env`, `data/`, `*.session` ni chiqarib tashlaydi —
ya'ni **sirlar GitHub'ga ketmaydi**. Faqat kod ketadi.

```powershell
cd D:\Tolibjon\Claude\jarvis
git init
git add .
git commit -m "JARVIS bot"
```
Keyin GitHub'da **private** repo yarating va yuklang (GitHub ko'rsatgan buyruqlar):
```powershell
git remote add origin https://github.com/USERNAME/jarvis.git
git branch -M main
git push -u origin main
```

---

## 3. Railway loyihasi

1. https://railway.app → **New Project** → **Deploy from GitHub repo** → jarvis repo'ni tanlang.
2. Railway avtomatik Python'ni aniqlaydi (`requirements.txt` + `Procfile` + `nixpacks.toml`).

### 3a. Doimiy disk (Volume) qo'shish — MUHIM!
- Loyihada servisni oching → **Settings** → **Volumes** → **New Volume**
- **Mount path:** `/data`
- Bu xotira, eslatmalar, sozlamalar saqlanadigan joy (restartда o'chmaydi).

### 3b. O'zgaruvchilar (Variables)
Servis → **Variables** → quyidagilarni qo'shing:

| Nomi | Qiymati |
|------|---------|
| `GROQ_API_KEY` | `gsk_...` (o'zingizniki) |
| `TELEGRAM_BOT_TOKEN` | bot token |
| `OWNER_ID` | Telegram ID'ingiz |
| `TG_API_ID` | my.telegram.org dan |
| `TG_API_HASH` | my.telegram.org dan |
| `TG_SESSION` | 1-qadamdagi uzun string |
| `DATA_DIR` | `/data` |
| `MODEL` | `openai/gpt-oss-120b` |

Ixtiyoriy (agar o'zgartirmoqchi bo'lsangiz): `VOICE_NAME`, `BRIEF_HOUR`,
`MOD_VIDEO_MAX_MB`, `MOD_CAPTCHA` va h.k.

### 3c. Start buyrug'i
`Procfile` bor (`worker: python bot.py`), lekin ishlamasa:
Settings → **Deploy** → **Custom Start Command** → `python bot.py`

---

## 4. Ishga tushirish va tekshirish

- Railway avtomatik deploy qiladi. **Deployments → Logs** ni oching.
- `JARVIS ishga tushdi` ko'rinsa — tayyor! ✅
- Telegram'da botga yozib sinang.

---

## Muhim eslatmalar (halol)

- **Narx:** Railway ~$5/oy dan (haqiqiy bepul emas). Usage bo'yicha — video/NSFW
  ko'p ishlatilsa ko'proq.
- **NudeNet modeli** har restartда qayta yuklanadi (~bir necha soniya kechikish).
  Restart kam bo'lgani uchun muammo emas.
- **Kompyuteringni o'chirsangiz ham** endi JARVIS ishlaydi — server bulutda.
- **Lokalda ham** hamon ishlatishingiz mumkin (`python bot.py`) — lekin ikkalasini
  BIR VAQTDA ishlatmang (Telegram bitta botni ikki joydan ishlatishga xato beradi).
- **Yangilanish:** kodni o'zgartirsangiz → `git push` → Railway avtomatik qayta deploy qiladi.
