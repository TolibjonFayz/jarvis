"""Server (Railway) uchun STRING sessiya yaratadi.

Ishlatish:  python gen_session.py
Telefon raqam + Telegram kodni kiritasiz. Oxirida uzun STRING chiqadi —
uni Railway'da TG_SESSION nomli o'zgaruvchiga (variable) qo'yasiz.

DIQQAT: bu string akkauntingizga to'liq kirish beradi — hech kimga bermang!
"""
import config

if not (config.TG_API_ID and config.TG_API_HASH):
    raise SystemExit(
        "XATO: .env da TG_API_ID va TG_API_HASH yo'q. Avval ularni to'ldiring."
    )

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

print("Telegram'ga ulanmoqda... (telefon raqamni +998... formatda kiriting)\n")
with TelegramClient(StringSession(), config.TG_API_ID, config.TG_API_HASH) as client:
    me = client.get_me()
    print(f"\nULANDI: {me.first_name} (@{me.username})\n")
    print("=" * 60)
    print("Quyidagini nusxa olib, Railway'da TG_SESSION o'zgaruvchisiga qo'ying:")
    print("=" * 60)
    print(client.session.save())
    print("=" * 60)
    print("\nDIQQAT: bu string maxfiy — hech kimga bermang, hech qayerga yozmang!")
