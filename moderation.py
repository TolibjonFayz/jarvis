"""Guruh moderatsiyasi: so'kinish/haqoratni aniqlash.

2 qatlam:
1) Lokal so'zlar ro'yxati — bepul, bir zumda, aniq so'kinishlar uchun.
2) AI tekshiruv — nozik/kontekstli haqoratlar uchun. ATAYLAB alohida arzon
   modelda (llama-3.1-8b-instant): Groq'da har model uchun kunlik budjet
   ALOHIDA, shuning uchun moderatsiya JARVIS suhbat budjetini yemaydi.
"""
import re

from groq import Groq

from config import GROQ_API_KEY

MOD_MODEL = "llama-3.1-8b-instant"

client = Groq(api_key=GROQ_API_KEY, max_retries=0) if GROQ_API_KEY else None

# Faqat ANIQ qo'pol so'zlar (o'zbek + rus + translit). Yengil so'zlar
# ("ahmoq" kabi) ataylab yo'q — ular kontekstga bog'liq, AI qatlam hal qiladi.
_BAD_STEMS = [
    # o'zbek
    "jalab", "jalap", "qanjiq", "qotoq", "qutoq", "kotak",
    "dalbayo", "dolbayo",
    # rus translit
    "suka", "blyat", "blyad", "pidor", "pidaras", "gandon",
    "xuy", "huy", "pizd", "yeban", "ebanut", "mudak",
    # rus kirill
    "сука", "блять", "блядь", "пидор", "пидорас", "гандон",
    "хуй", "пизд", "ебан", "мудак", "долбоё",
]

_BAD_RE = re.compile(
    r"\b(" + "|".join(_BAD_STEMS) + r")\w*",
    re.IGNORECASE | re.UNICODE,
)

_APOS_RE = re.compile(r"[''ʼ`´]")
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

_SYSTEM = (
    "Sen guruh moderatorisan. Xabarda so'kinish yoki SHAXSGA qaratilgan "
    "haqorat/kamsitish bormi shuni aniqla.\n"
    "Haqorat EMAS: salomlashish, savol, tanqid, bahs, salbiy fikr, hazil.\n"
    "Haqorat: shaxsni so'kish, kamsitish, tahqirlash, aqlini/qadrini erga urish.\n"
    "Faqat bitta so'z bilan javob ber: HA (haqorat bor) yoki YOQ (yo'q)."
)

# Few-shot: model formatni aniq tushunishi uchun (aniqlikni sezilarli oshiradi).
_FEWSHOT = [
    {"role": "user", "content": "salom, ishlar qalay?"},
    {"role": "assistant", "content": "YOQ"},
    {"role": "user", "content": "sen ahmoqsan, gapingni ham bilmaysan"},
    {"role": "assistant", "content": "HA"},
]


def _normalize(text):
    return _APOS_RE.sub("", (text or "").lower())


def check_message(text):
    """(yomonmi, sabab) qaytaradi. Xato bo'lsa (False, '') — guruh to'xtamasin."""
    if not text or len(text.strip()) < 2:
        return False, ""

    # 1-qatlam: so'zlar ro'yxati (bepul)
    if _BAD_RE.search(_normalize(text)):
        return True, "so'kinish"

    # 2-qatlam: AI (alohida arzon model)
    if client is None:
        return False, ""
    try:
        r = client.chat.completions.create(
            model=MOD_MODEL,
            messages=[{"role": "system", "content": _SYSTEM}]
            + _FEWSHOT
            + [{"role": "user", "content": text[:500]}],
            max_tokens=200,
            temperature=0,
        )
        raw = r.choices[0].message.content or ""
        verdict = _THINK_RE.sub("", raw).strip().upper()
        if verdict.startswith("HA"):
            return True, "haqorat"
    except Exception:
        # AI ishlamasa (429 va h.k.) — jim o'tamiz, guruh ishlashda davom etadi.
        pass
    return False, ""
