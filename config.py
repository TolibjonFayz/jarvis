"""Sozlamalar: .env fayldan kalitlarni o'qiydi va papkalarni tayyorlaydi."""
import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
MODEL = os.getenv("MODEL", "openai/gpt-oss-120b")

# Javob uchun maksimal token.
# Groq tekin darajasi daqiqasiga ~8000 token beradi va bu "ajratilgan" javob
# ham shu chegaraga kiradi. Shuning uchun past qo'ydik (429'ni kamaytiradi).
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "512"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Agent fayllar bilan FAQAT shu papka ichida ishlaydi (xavfsizlik uchun).
WORKSPACE = os.path.join(BASE_DIR, "workspace")

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
