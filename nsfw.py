"""NSFW (18+) rasm aniqlash — lokal NudeNet.

Bepul, offline, Groq token yemaydi, rasmlar hech qayerga yuborilmaydi (maxfiylik).
"""
import os
import tempfile
import threading

_detector = None
_lock = threading.Lock()

# Faqat ANIQ ochiq (exposed) NSFW klasslar. Yopiq (COVERED), oyoq, qo'ltiq,
# yuz — normal, ularга tegmaymiz. Bikini/plaj rasmlari odatda "COVERED" -> o'tadi.
_NSFW_CLASSES = {
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "BUTTOCKS_EXPOSED",
    "ANUS_EXPOSED",
}
_THRESHOLD = 0.55


def _get():
    global _detector
    if _detector is None:
        from nudenet import NudeDetector

        _detector = NudeDetector()
    return _detector


def is_nsfw_file(path):
    """(nsfwmi, sabab). Model ishlamasa (False, '') — guruh to'xtamasin."""
    try:
        with _lock:  # NudeDetector'ni ketma-ket chaqiramiz (xavfsizlik)
            dets = _get().detect(path)
        for det in dets:
            if det.get("class") in _NSFW_CLASSES and det.get("score", 0) >= _THRESHOLD:
                return True, "18+ kontent"
    except Exception:
        pass
    return False, ""


def is_nsfw_bytes(data, suffix=".jpg"):
    """Rasm baytlarini vaqtinchalik faylga yozib tekshiradi."""
    if not data:
        return False, ""
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        return is_nsfw_file(tmp)
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass
