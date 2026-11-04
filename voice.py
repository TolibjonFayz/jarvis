"""Ovoz: STT (Groq Whisper, tekin) + TTS (edge-tts, tekin).

Telegram: o'zbekcha (uz-UZ ovoz, Whisper language=uz). Kompyuter (voice_pc/HUD): inglizcha
(config.PC_VOICE_NAME, PC_LANG) — tillar parametr bilan beriladi.
Whisper alohida kunlik budjetga ega — FRIDAY suhbat tokenlarini yemaydi.
"""
import os
import re
import logging

from groq import Groq

import config

log = logging.getLogger("jarvis.voice")

client = Groq(api_key=config.GROQ_API_KEY, max_retries=0) if config.GROQ_API_KEY else None


def transcribe(path, language=None):
    """Ovoz faylini matnga aylantiradi (sinxron — thread'da chaqiriladi).
    language=None — Telegram standarti (config.VOICE_LANG)."""
    with open(path, "rb") as f:
        data = f.read()
    lang = config.VOICE_LANG if language is None else language
    r = client.audio.transcriptions.create(
        file=(os.path.basename(path), data),
        model=config.STT_MODEL,
        language=lang or None,
        response_format="text",
    )
    return str(r).strip()


async def tts(text, out_path, voice_name=None):
    """Matnni ovozga aylantiradi (mp3)."""
    import edge_tts

    c = edge_tts.Communicate(text, voice_name or config.VOICE_NAME)
    await c.save(out_path)


_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_PHRASES = {
    "uz": (" kod yozdim, chatda ko'ring. ", " havola chatda ", " ... davomi chatda."),
    "en": (" I've put the code on your screen. ", " the link is on your screen ", " ... the rest is on your screen."),
}


def speakable(text, limit=700, lang="uz"):
    """Javobning ovozga mos qismini qaytaradi:
    kod bloklari va linklar olib tashlanadi, uzunligi cheklanadi."""
    code, link, more = _PHRASES.get(lang, _PHRASES["uz"])
    t = _CODE_RE.sub(code, text or "")
    t = _INLINE_CODE_RE.sub(" ", t)
    t = _URL_RE.sub(link, t)
    t = re.sub(r"[*#_~|>•]+", " ", t)  # markdown belgilari ovozda o'qilmasin
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + more
    return t
