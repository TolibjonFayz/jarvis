"""Hozir nima o'ynayapti + takrorlash (loop) — Windows media sessiyasi (GSMTC).

YouTube (brauzer/PWA), Spotify va boshqa pleerlar Windows'ga "hozir o'ynayapti"
ma'lumotini beradi: nomi, ijrochi/kanal, holat, pozitsiya. Repeat tugmasi YouTube'da
yopiq (is_repeat_enabled=False), lekin seek ochiq — shuning uchun loop'ni o'zimiz
qilamiz: bot har bir necha soniyada tekshiradi, qo'shiq tugashiga oz qolganda boshiga
qaytaradi. Qo'shiq almashsa (egasi o'zi boshqasini qo'ysa) — loop o'chadi.

Funksiyalar sinxron (ichida asyncio.run) — bot ularni asyncio.to_thread orqali chaqiradi.
"""
import asyncio
import datetime

END_MARGIN = 4.0      # tugashiga shuncha soniya qolganda boshiga qaytariladi
TICK_SEC = 3          # bot shu oraliqda loop_tick() chaqiradi (END_MARGIN dan kichik)

PLAYING, PAUSED = 4, 5
_STATUS = {PLAYING: "▶️", PAUSED: "⏸"}

LOOP = {}  # {"title", "chat_id", "count"} — yoqilgan bo'lsa

_APPS = (("youtube", "YouTube"), ("spotify", "Spotify"), ("chrome", "Chrome"),
         ("msedge", "Edge"), ("firefox", "Firefox"), ("music", "Musiqa"))


def _app_name(aumid):
    a = (aumid or "").lower()
    return next((name for key, name in _APPS if key in a), aumid or "pleer")


def _manager():
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as M,
    )
    return M.request_async()


def _secs(td):
    return td.total_seconds() if td else 0.0


async def _pick_session():
    """O'ynab turgan sessiya (bo'lmasa — Windows tanlagan joriy sessiya)."""
    mgr = await _manager()
    sessions = list(mgr.get_sessions())
    for s in sessions:
        if s.get_playback_info().playback_status == PLAYING:
            return s
    return mgr.get_current_session() or (sessions[0] if sessions else None)


async def _info(s):
    props = await s.try_get_media_properties_async()
    pb = s.get_playback_info()
    tl = s.get_timeline_properties()
    pos = _secs(tl.position)
    # Chrome pozitsiyani faqat holat o'zgarganda yangilaydi — o'tgan vaqtni qo'shamiz.
    if pb.playback_status == PLAYING and tl.last_updated_time:
        now = datetime.datetime.now(datetime.timezone.utc)
        pos += max(0.0, (now - tl.last_updated_time).total_seconds())
    dur = _secs(tl.end_time)
    return {
        "title": (props.title or "").strip(),
        "artist": (props.artist or "").strip(),
        "app": _app_name(s.source_app_user_model_id),
        "status": pb.playback_status,
        "position": min(pos, dur) if dur else pos,
        "duration": dur,
        "can_seek": bool(pb.controls.is_playback_position_enabled),
    }


def now_playing():
    """dict yoki None (hech narsa ochiq emas)."""
    async def run():
        s = await _pick_session()
        return await _info(s) if s else None
    return asyncio.run(run())


def _clock(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def now_playing_text():
    try:
        info = now_playing()
    except Exception as e:
        return f"❌ Pleerni o'qib bo'lmadi: {str(e)[:100]}"
    if not info or not info["title"]:
        return "🔇 Hozir kompyuterda hech narsa o'ynamayapti."
    lines = [f"🎵 **{info['title']}**"]
    if info["artist"]:
        lines.append(f"👤 {info['artist']}")
    state = _STATUS.get(info["status"], "⏹")
    if info["duration"]:
        state += f" {_clock(info['position'])} / {_clock(info['duration'])}"
    if LOOP and LOOP.get("title") == info["title"]:
        state += " · 🔁 takrorlanyapti"
    lines.append(f"{state} · {info['app']}")
    return "\n".join(lines)


async def _seek_start(s):
    return await s.try_change_playback_position_async(0)


def set_loop(on, chat_id=None):
    """Loop'ni yoqadi (hozirgi qo'shiqqa) yoki o'chiradi. Egasiga matn qaytaradi."""
    if not on:
        if not LOOP:
            return "🔁 Takrorlash yoqilmagan edi."
        title = LOOP["title"]
        LOOP.clear()
        return f"➡️ Takrorlash o'chirildi: {title}"
    try:
        info = now_playing()
    except Exception as e:
        return f"❌ Pleerni o'qib bo'lmadi: {str(e)[:100]}"
    if not info or not info["title"]:
        return "🔇 Hozir hech narsa o'ynamayapti — avval qo'shiq qo'y."
    if not info["can_seek"]:
        return f"❌ {info['app']} boshiga qaytarishga ruxsat bermaydi — takrorlab bo'lmaydi."
    if not info["duration"]:
        return "❌ Qo'shiq uzunligi noma'lum (jonli efirmi?) — takrorlab bo'lmaydi."
    LOOP.clear()
    LOOP.update(title=info["title"], chat_id=chat_id, count=0)
    return (f"🔁 Takrorlash yoqildi: **{info['title']}** ({_clock(info['duration'])})\n"
            "Boshqa qo'shiq qo'ysang yoki «loopni o'chir» desang to'xtaydi.")


def loop_tick():
    """Bot har TICK_SEC da chaqiradi. Egasiga xabar kerak bo'lsa (chat_id, matn), aks holda None."""
    if not LOOP:
        return None

    async def run():
        s = await _pick_session()
        if not s:
            return "gone", None
        info = await _info(s)
        if not info["title"]:
            return "ok", info  # sahifa yuklanyapti — nom vaqtincha bo'sh
        if info["title"] != LOOP["title"]:
            return "changed", info
        if info["status"] == PLAYING and info["duration"] and \
                info["duration"] - info["position"] <= END_MARGIN:
            await _seek_start(s)
            return "restarted", info
        return "ok", info

    try:
        state, info = asyncio.run(run())
    except Exception:
        return None  # vaqtinchalik xato (brauzer yopilyapti va h.k.) — keyingi safar
    if state == "restarted":
        LOOP["count"] += 1
        return None
    if state in ("changed", "gone"):
        chat_id, title = LOOP.get("chat_id"), LOOP["title"]
        LOOP.clear()
        why = "pleer yopildi" if state == "gone" else "boshqa qo'shiq qo'yildi"
        return chat_id, f"➡️ Takrorlash o'chdi ({why}): {title}"
    return None
