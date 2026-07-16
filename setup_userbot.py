"""Userbot'ni BIR MARTA ulash: telefon raqam + Telegram'dan kelgan kod.
Ishlatish:  python setup_userbot.py

Oldin .env ga yozing (my.telegram.org -> API development tools):
  TG_API_ID=1234567
  TG_API_HASH=abcdef...
"""
import os

import config

if not (config.TG_API_ID and config.TG_API_HASH):
    raise SystemExit(
        "XATO: .env da TG_API_ID va TG_API_HASH yo'q.\n"
        "1) my.telegram.org ga kiring (o'z raqamingiz bilan)\n"
        "2) 'API development tools' -> ilova yarating (nomi ixtiyoriy)\n"
        "3) api_id va api_hash ni .env ga yozing:\n"
        "   TG_API_ID=1234567\n"
        "   TG_API_HASH=abcdef1234567890\n"
    )

from telethon.sync import TelegramClient

SESSION = os.path.join(config.DATA_DIR, "userbot")

print("Telegram'ga ulanmoqda... (telefon raqamni +998... formatda kiriting)")
with TelegramClient(SESSION, config.TG_API_ID, config.TG_API_HASH) as client:
    me = client.get_me()
    uname = f"@{me.username}" if me.username else ""
    print(f"\nULANDI: {me.first_name} {uname}")
    print(f"Sessiya saqlandi: {SESSION}.session")
    print("DIQQAT: bu fayl akkauntingizga to'liq kirish beradi — hech kimga bermang!")
    print("\nEndi botni qayta ishga tushiring: python bot.py")
