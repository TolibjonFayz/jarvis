"""NSFW (18+) rasm/video aniqlash — lokal NudeNet.

Bepul, offline, Groq token yemaydi, rasm/video hech qayerga yuborilmaydi.
Diagnostika: har tekshiruvda NudeNet nima ko'rganini log qiladi.
"""
import os
import logging
import tempfile
import threading

log = logging.getLogger("jarvis.nsfw")

_detector = None
_lock = threading.Lock()

# ANIQ ochiq (exposed) NSFW klasslar.
_NSFW_CLASSES = {
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "FEMALE_BREAST_EXPOSED",
    "BUTTOCKS_EXPOSED",
    "ANUS_EXPOSED",
}

# Chegaralar: rasm sifatli -> balandroq; video kadr sifati past -> pastroq.
_IMG_THRESHOLD = 0.40
_VID_THRESHOLD = 0.30


def _get():
    global _detector
    if _detector is None:
        from nudenet import NudeDetector

        _detector = NudeDetector()
    return _detector


def _detect(path):
    """Faylni tekshirib, (nsfw_bor, eng_baland_class, eng_baland_ball, hammasidan_maks)
    qaytaradi. Xato bo'lsa bo'sh."""
    try:
        with _lock:
            dets = _get().detect(path)
    except Exception as e:
        log.warning("NudeNet detect xatosi: %s", e)
        return []
    return dets or []


def _judge(dets, threshold):
    """(nsfwmi, sabab, log_matni)."""
    hit_cls, hit_score = None, 0.0
    best_cls, best_score = None, 0.0
    for d in dets:
        cls = d.get("class", "")
        score = float(d.get("score", 0) or 0)
        if cls in _NSFW_CLASSES:
            if score >= threshold and score > hit_score:
                hit_cls, hit_score = cls, score
            if score > best_score:
                best_cls, best_score = cls, score
    if hit_cls:
        return True, "18+ kontent", f"{hit_cls}={hit_score:.2f} (chegara {threshold})"
    if best_cls:
        return False, "", f"eng yuqori {best_cls}={best_score:.2f} < {threshold}"
    return False, "", "18+ belgi topilmadi"


def is_nsfw_file(path, threshold=None):
    """(nsfwmi, sabab). Rasm uchun."""
    dets = _detect(path)
    bad, reason, dbg = _judge(dets, _IMG_THRESHOLD if threshold is None else threshold)
    log.info("NSFW rasm tekshiruvi: %s", dbg)
    return bad, reason


def is_nsfw_bytes(data, suffix=".jpg"):
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


def is_nsfw_video(path, frames=9):
    """Videodan bir necha kadr namunasini olib tekshiradi (opencv)."""
    try:
        import cv2
    except Exception:
        log.warning("opencv yo'q — video tekshirib bo'lmadi")
        return False, ""

    cap = None
    checked = 0
    max_cls, max_score = None, 0.0
    try:
        cap = cv2.VideoCapture(path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        if total <= 0:
            log.warning("Video o'qib bo'lmadi (kodek?) — 0 kadr topildi: %s", path)
            return False, ""
        for i in range(1, frames + 1):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * i / (frames + 1)))
            ok, frame = cap.read()
            if not ok:
                continue
            checked += 1
            fd, tmp = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
            try:
                cv2.imwrite(tmp, frame)
                dets = _detect(tmp)
            finally:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
            bad, reason, _dbg = _judge(dets, _VID_THRESHOLD)
            for d in dets:
                cls = d.get("class", "")
                sc = float(d.get("score", 0) or 0)
                if cls in _NSFW_CLASSES and sc > max_score:
                    max_cls, max_score = cls, sc
            if bad:
                log.info(
                    "Video: %d kadr, %d/%d-kadrда 18+ topildi (%s=%.2f)",
                    total, i, frames, reason, max_score,
                )
                return True, reason
        summary = (
            f"eng yuqori {max_cls}={max_score:.2f} < {_VID_THRESHOLD}"
            if max_cls else "18+ belgi topilmadi"
        )
        log.info("Video: %d kadr, %d tekshirildi — toza (%s)", total, checked, summary)
    except Exception as e:
        log.warning("Video tekshiruv xatosi: %s", e)
    finally:
        if cap is not None:
            cap.release()
    return False, ""
