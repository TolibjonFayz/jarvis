"""Ovoz: STT (Groq Whisper, tekin) + TTS (edge-tts, tekin, o'zbek ovozi).

Whisper alohida kunlik budjetga ega — JARVIS suhbat tokenlarini yemaydi.
"""
import os
import re
import logging

from groq import Groq

import config

log = logging.getLogger("jarvis.voice")

client = Groq(api_key=config.GROQ_API_KEY, max_retries=0) if config.GROQ_API_KEY else None


def transcribe(path):
    """Ovoz faylini matnga aylantiradi (sinxron — thread'da chaqiriladi)."""
    with open(path, "rb") as f:
        data = f.read()
    r = client.audio.transcriptions.create(
        file=(os.path.basename(path), data),
        model=config.STT_MODEL,
        language=config.VOICE_LANG or None,
        response_format="text",
    )
    return str(r).strip()


async def tts(text, out_path):
    """Matnni ovozga aylantiradi (mp3)."""
    import edge_tts

    c = edge_tts.Communicate(text, config.VOICE_NAME)
    await c.save(out_path)


_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")


def speakable(text, limit=700):
    """Javobning ovozga mos qismini qaytaradi:
    kod bloklari va linklar olib tashlanadi, uzunligi cheklanadi."""
    t = _CODE_RE.sub(" kod yozdim, chatda ko'ring. ", text or "")
    t = _INLINE_CODE_RE.sub(" ", t)
    t = _URL_RE.sub(" havola chatda ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + " ... davomi chatda."
    return t
