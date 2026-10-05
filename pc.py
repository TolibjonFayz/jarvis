"""Kompyuterni Telegram'dan boshqarish (Windows): ekran, qulflash, quvvat, holat, link.

Xavfsizlik:
- Faqat egasi (bot.py _authorized). Ekran rasmi faqat Telegram'ga, Gemini'ga emas.
- Uxlatish/o'chirish/restart FAQAT tasdiq tugmasidan keyin (bot.on_button).
  O'chirish/restart 60 s kechikadi — shu orada «Bekor qilish» (shutdown /a) ishlaydi.
- Ixtiyoriy buyruq bajarish YO'Q (keyingi bosqich: oldindan ruxsat berilgan ro'yxat).
"""
import ctypes
import datetime
import os
import subprocess
import tempfile
import threading
import time
import urllib.parse

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
POWER_DELAY = 60  # o'chirish/restartdan oldin bekor qilish uchun vaqt (s)

POWER_LABELS = {
    "sleep": "😴 Uxlatish",
    "shutdown": "⏻ O'chirish",
    "restart": "🔄 Qayta yoqish",
}


def screenshot():
    """Hamma monitorlar -> JPEG fayl. (yo'l, qora_ekranmi). Qora = qulflangan/uxlagan."""
    from PIL import ImageGrab

    img = ImageGrab.grab(all_screens=True).convert("RGB")
    lo, hi = img.convert("L").getextrema()
    if img.width > 2560:  # 2 monitor 4K bo'lsa ham Telegram'ga sig'sin
        img = img.resize((2560, int(img.height * 2560 / img.width)))
    path = os.path.join(tempfile.gettempdir(), f"friday_screen_{int(time.time())}.jpg")
    img.save(path, "JPEG", quality=85)
    return path, hi < 10


def lock():
    """Ekranni qulflaydi (parol bilan ochiladi)."""
    if not ctypes.windll.user32.LockWorkStation():
        raise OSError("qulflab bo'lmadi")


def _suspend():
    # SetSuspendState(hibernate=False, force=True, disable_wake=False)
    ctypes.windll.powrprof.SetSuspendState(False, True, False)


def power(action):
    """Tasdiqlangandan keyin chaqiriladi. Natija matni."""
    if action == "sleep":
        # 5 s kechiktiramiz — bot avval javob yuborib ulgursin (uxlagach bot ham to'xtaydi).
        threading.Timer(5, _suspend).start()
        return "😴 5 soniyadan keyin uxlaydi. Uyg'otilguncha FRIDAY ham javob bermaydi."
    if action in ("shutdown", "restart"):
        flag = "/s" if action == "shutdown" else "/r"
        subprocess.run(
            ["shutdown", flag, "/t", str(POWER_DELAY), "/c", "FRIDAY: Telegram orqali so'raldi"],
            check=True, creationflags=_NO_WINDOW,
        )
        what = "o'chadi" if action == "shutdown" else "qayta yoqiladi"
        return f"⏻ Kompyuter {POWER_DELAY} soniyadan keyin {what}. Bekor qilish uchun tugmani bos."
    raise ValueError(f"noma'lum amal: {action}")


def cancel_power():
    r = subprocess.run(["shutdown", "/a"], capture_output=True, creationflags=_NO_WINDOW)
    return "✅ Bekor qilindi — kompyuter yoqiq qoladi." if r.returncode == 0 else (
        "Bekor qiladigan narsa yo'q (o'chirish rejalashtirilmagan yoki allaqachon boshlangan)."
    )


def _fmt_gb(n):
    return f"{n / 2**30:.1f} GB"


def status_text():
    import psutil

    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    up = datetime.timedelta(seconds=int(time.time() - psutil.boot_time()))
    days, rem = divmod(up.total_seconds(), 86400)
    uptime = (f"{int(days)} kun " if days else "") + f"{int(rem // 3600)} soat {int(rem % 3600 // 60)} daqiqa"
    lines = [
        "🖥 **Kompyuter holati**",
        f"⏱ Yoqilganiga: {uptime}",
        f"⚙️ CPU: {cpu:.0f}% · 🧠 Xotira: {ram.percent:.0f}% ({_fmt_gb(ram.used)} / {_fmt_gb(ram.total)})",
    ]
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        warn = " ⚠️" if u.percent >= 90 else ""
        lines.append(f"💾 {part.mountpoint} — {_fmt_gb(u.free)} bo'sh ({u.percent:.0f}% band){warn}")
    try:
        import nowplaying
        info = nowplaying.now_playing()
        if info and info["title"]:
            lines.append(f"🎵 {info['title'][:60]} · {info['app']}")
    except Exception:
        pass
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if bat:
        lines.append(f"🔋 {bat.percent:.0f}%{' · zaryadda' if bat.power_plugged else ''}")
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procs.append((p.info["memory_info"].rss, p.info["name"]))
        except (psutil.Error, AttributeError, TypeError):
            continue
    top = sorted(procs, reverse=True)[:3]
    if top:
        lines.append("Ko'p xotira olayotganlar: " + ", ".join(f"{n} ({_fmt_gb(m)})" for m, n in top))
    return "\n".join(lines)


def open_url(url):
    """Linkni kompyuter brauzerida ochadi — faqat http/https (fayl/dastur emas)."""
    url = (url or "").strip()
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError("faqat http(s) havola ochiladi")
    os.startfile(url)
    return f"🌐 Kompyuterda ochildi: {url}"


# --- Musiqa ---

DEFAULT_MUSIC = "yangi o'zbek qo'shiqlari mix"
_VIDEO_ID_RE = __import__("re").compile(r'"videoId":"([\w-]{11})"')


def find_youtube(query):
    """YouTube qidiruvidagi birinchi video havolasi (topilmasa — qidiruv sahifasi)."""
    import urllib.request

    import net

    net.prefer_ipv4()  # Google manzillari — bu tarmoqda IPv6 osiladi
    search = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    try:
        req = urllib.request.Request(search, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "uz,ru,en"})
        html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "replace")
        m = _VIDEO_ID_RE.search(html)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}", True
    except OSError:
        pass
    return search, False


def play_music(query=""):
    """Kompyuterda YouTube'da qo'shiq qo'yadi. query bo'sh bo'lsa — standart mix."""
    q = (query or "").strip() or DEFAULT_MUSIC
    url, exact = find_youtube(q)
    os.startfile(url)
    return (f"🎵 Kompyuterda qo'yildi: {q}" if exact
            else f"🎵 YouTube'da qidiruv ochildi: {q} (birinchi videoni o'zim topa olmadim)")


# Windows virtual klavishlari — YouTube, Spotify, istalgan pleerda ishlaydi.
_MEDIA_KEYS = {
    "play_pause": (0xB3, "⏯ Pauza/davom"),
    "next": (0xB0, "⏭ Keyingisi"),
    "prev": (0xB1, "⏮ Oldingisi"),
    "volume_up": (0xAF, "🔊 Ovoz balandladi"),
    "volume_down": (0xAE, "🔉 Ovoz pasaydi"),
    "mute": (0xAD, "🔇 Ovoz o'chirildi/yoqildi"),
}


def media(action, times=1):
    """Media klavishini bosadi. volume_* da bir bosish ~2%, shuning uchun bir necha marta."""
    if action not in _MEDIA_KEYS:
        raise ValueError(f"noma'lum amal: {action}")
    vk, label = _MEDIA_KEYS[action]
    n = max(1, min(int(times or 1), 50))
    if action.startswith("volume") and times in (None, 1):
        n = 5  # ~10%
    for _ in range(n):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
    return label


# --- Ovoz darajasi (Windows Core Audio, pycaw) ---
# Media klavishlari natijani bilmaydi — bu yerda darajani O'QIB, haqiqiy raqamni aytamiz
# (avval model "ovoz oshirildi" deb yolg'on yozgan edi).

def _endpoint():
    import comtypes
    from pycaw.pycaw import AudioUtilities

    comtypes.CoInitialize()  # bot uni fon oqimida chaqiradi — COM har oqimda alohida
    dev = AudioUtilities.GetSpeakers()
    return dev, dev.EndpointVolume


def volume(action, value=None):
    """action: up, down, set (value=0..100), mute, unmute, get. Natija: haqiqiy daraja."""
    import comtypes

    dev, ep = _endpoint()
    try:
        before = round(ep.GetMasterVolumeLevelScalar() * 100)
        if action == "up":
            target = min(100, before + int(value or 10))
        elif action == "down":
            target = max(0, before - int(value or 10))
        elif action == "set":
            if value is None:
                raise ValueError("necha foiz? (0-100)")
            target = max(0, min(100, int(value)))
        else:
            target = before
        if action in ("mute", "unmute"):
            ep.SetMute(1 if action == "mute" else 0, None)
        elif action != "get":
            ep.SetMasterVolumeLevelScalar(target / 100, None)
            if target > 0 and ep.GetMute():
                ep.SetMute(0, None)
        after = round(ep.GetMasterVolumeLevelScalar() * 100)
        muted = bool(ep.GetMute())
        name = getattr(dev, "FriendlyName", "") or "ovoz qurilmasi"
    finally:
        comtypes.CoUninitialize()
    icon = "🔇" if muted else ("🔊" if after >= before else "🔉")
    if action == "get":
        return f"{icon} Ovoz: {after}%{' (o‘chiq)' if muted else ''} — {name}"
    if action in ("mute", "unmute"):
        return f"{icon} Ovoz {'o‘chirildi' if muted else 'yoqildi'} ({after}%) — {name}"
    return f"{icon} Ovoz: {before}% → {after}% — {name}"
