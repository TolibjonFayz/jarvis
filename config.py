"""Sozlamalar: .env fayldan kalitlarni o'qiydi va papkalarni tayyorlaydi."""
import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
MODEL = os.getenv("MODEL", "openai/gpt-oss-120b")

# Userbot (shaxsiy akkaunt) — my.telegram.org dan. Ixtiyoriy.
TG_API_ID = int(os.getenv("TG_API_ID", "0"))
TG_API_HASH = os.getenv("TG_API_HASH", "")

# Guruh moderatsiyasi: nechta ogohlantirishdan KEYIN chiqarib yuborilsin.
# 2 = ikki marta ogohlantiriladi, 3-buzilishda guruhdan chiqariladi.
MOD_WARN_LIMIT = int(os.getenv("MOD_WARN_LIMIT", "2"))

# TEST rejimi: True bo'lsa egani ham tekshiradi (o'z akkaunting bilan sinash uchun).
# Sinab bo'lgach .env da MOD_TEST_MODE=0 qilib qo'ying (yoki o'chiring).
MOD_TEST_MODE = os.getenv("MOD_TEST_MODE", "0") == "1"

# Javob uchun maksimal token.
# Groq tekin darajasi daqiqasiga ~8000 token beradi va bu "ajratilgan" javob
# ham shu chegaraga kiradi. Shuning uchun past qo'ydik (429'ni kamaytiradi).
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "512"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# YOZISH faqat shu papka ichida (xavfsizlik uchun).
WORKSPACE = os.path.join(BASE_DIR, "workspace")

# O'QISH shu papka ichida ruxsat etilgan (loyihalarni tahlil qilish uchun).
READ_ROOT = os.getenv("READ_ROOT", r"D:\Tolibjon")

# Xotira ma'lumotlar bazasi shu yerda saqlanadi.
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "jarvis.db")

os.makedirs(WORKSPACE, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


def check():
    """Ishga tushishdan oldin kalitlar borligini tekshiradi."""
    missing = []
    if not GROQ_API_KEY:
        missing.append("GROQ_API_KEY")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if missing:
        raise SystemExit(
            "XATO: .env faylda quyidagilar to'ldirilmagan: "
            + ", ".join(missing)
            + "\n.env.example dan nusxa olib .env yasang va to'ldiring."
        )
