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
