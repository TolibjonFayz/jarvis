# Google Calendar'ni FRIDAY'ga ulash (bir marta, ~15 daqiqa)

FRIDAY faqat **tadbirlarga** ruxsat oladi (`calendar.events`): ko'radi va qo'shadi.
Kalendar sozlamalari, Gmail va boshqa Google ma'lumotlariga tegmaydi.

1. **Loyiha:** https://console.cloud.google.com → yuqoridagi loyiha tanlagich →
   **New project** → nomi `FRIDAY` → Create.
2. **Calendar API:** chap menyu → *APIs & Services* → *Library* → "Google Calendar API"
   → **Enable**.
3. **Ruxsat oynasi (OAuth consent / Google Auth Platform):**
   - *Branding*: App name `FRIDAY`, support email va developer email — o'z emailing.
   - *Audience*: User type **External**.
   - **Muhim:** *Publishing status* ni **In production** qil ("Publish app").
     Aks holda ("Testing") ruxsat har **7 kunda** o'chib qoladi.
     Google "tasdiqlanmagan ilova" deb ogohlantiradi — shaxsiy foydalanish uchun normal.
4. **Kalit fayl:** *Clients* (yoki *Credentials*) → **Create client** → Application type
   **Desktop app** → Create → **Download JSON**. Faylni shu nom bilan saqla:
   `D:\Tolibjon\Claude\jarvis\data\google_client.json`
5. **Ulash:** terminalda:
   ```
   cd D:\Tolibjon\Claude\jarvis
   python setup_gcal.py
   ```
   Brauzer ochiladi → Google akkaunting → "Google hasn't verified this app" chiqsa
   **Advanced → Go to FRIDAY (unsafe)** → **Continue**. Terminalda "Tayyor!" chiqadi.
6. Botni qayta ishga tushir.

`data/` papkasi git'ga tushmaydi — kalit va token faqat shu kompyuterda qoladi.
Ruxsatni istalgan payt bekor qilish: https://myaccount.google.com/permissions → FRIDAY → Remove.
