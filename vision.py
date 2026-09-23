"""Rasm ko'rish: Gemini (tekin) — Groq'da vision model yo'q.

MAXFIYLIK: Gemini tekin tarifida Google yuborilgan ma'lumotni o'qitishga
ishlatadi va odamlar ko'rib chiqishi mumkin. Shuning uchun bu yerga FAQAT
rasmning o'zi va egasining izohi boradi — xotira, suhbat tarixi, Telegram
xabarlari, xarajatlar YUBORILMAYDI. Javobni baribir Groq'dagi agent yozadi
(rasm tavsifi unga matn sifatida beriladi).
"""
import base64
import json
import logging
import socket
import urllib.error
import urllib.request

import config

log = logging.getLogger("jarvis.vision")

API = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"

_PROMPT = (
    "Rasmni o'zbek tilida aniq tasvirla. Rasmda matn bo'lsa — uni aynan ko'chir. "
    "Chek/hisob-faktura bo'lsa: do'kon, sana, har bir mahsulot va narxi, jami summa. "
    "Kod/xato skrinshoti bo'lsa: kod va xato matnini aynan ko'chir. "
    "Taxmin qilma, ko'rinmagan narsani yozma. Qisqa va tartibli yoz."
)


def _prefer_ipv4():
    """Bu tarmoqda IPv6 ulanish osilib qoladi (DNS esa avval IPv6 beradi) —
    IPv4 manzillarni oldinga qo'yamiz. IPv6 o'chirilmaydi, faqat tartib."""
    if getattr(socket.getaddrinfo, "_ipv4_first", False):
        return
    orig = socket.getaddrinfo

    def getaddrinfo(*args, **kwargs):
        return sorted(orig(*args, **kwargs), key=lambda r: r[0] != socket.AF_INET)

    getaddrinfo._ipv4_first = True
    socket.getaddrinfo = getaddrinfo


_prefer_ipv4()


class VisionError(Exception):
    pass


def available():
    return bool(config.GEMINI_API_KEY)


def describe(image_bytes, mime="image/jpeg", note=""):
    """Rasm tavsifi (matn). Hamma model limitga urilsa VisionError."""
    if not available():
        raise VisionError("GEMINI_API_KEY sozlanmagan")
    parts = [
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(image_bytes).decode()}},
        {"text": _PROMPT + (f"\nEgasining izohi: {note}" if note else "")},
    ]
    body = json.dumps({"contents": [{"parts": parts}]}).encode()
    last = ""
    for model in config.VISION_MODELS:
        req = urllib.request.Request(
            API.format(model), data=body, method="POST",
            headers={"x-goog-api-key": config.GEMINI_API_KEY,
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            # 429 = limit, 404 = model yo'q, 5xx = band — keyingi modelga.
            last = f"{model}: HTTP {e.code}"
            log.warning("Gemini %s", last)
            continue
        except OSError as e:
            last = f"{model}: {e}"
            log.warning("Gemini tarmoq xatosi: %s", e)
            continue
        cands = data.get("candidates") or []
        text = "".join(
            p.get("text", "") for p in (cands[0].get("content", {}).get("parts", []) if cands else [])
        ).strip()
        if text:
            return text
        last = f"{model}: bo'sh javob ({(cands[0].get('finishReason') if cands else 'no candidates')})"
    raise VisionError(last or "javob yo'q")
