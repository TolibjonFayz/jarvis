"""Windows'da JARVIS'ni fonda doimiy ishlatuvchi nazoratchi (supervisor).

- Oynasiz ishlaydi (.pyw -> pythonw.exe).
- bot.py yiqilsa 10 soniyadan keyin qayta ishga tushiradi.
- Ishlab turganda kompyuterni avtomatik uyquga ketishdan to'xtatadi
  (SetThreadExecutionState — video pleerlar ishlatadigan usul; ekran
  baribir o'chishi mumkin, faqat tizim uxlamaydi). Bu tizim sozlamasini
  o'zgartirmaydi: nazoratchi to'xtasa, odatiy uyqu qaytadi.
- Faqat bitta nusxa ishlaydi (ikki bot bitta token bilan Conflict beradi).
- Chiqish data/bot.log ga yoziladi (5 MB dan oshsa bot.log.1 ga suriladi).

Task Scheduler "kirishda" (At logon) ishga tushiradi — setup_autostart.ps1.
"""
import ctypes
import os
import socket
import subprocess
import sys
import time
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
LOG = os.path.join(DATA, "bot.log")
LOG_MAX = 5 * 1024 * 1024
RESTART_DELAY = 10
# Bitta nusxa qulfi: shu portni faqat bitta jarayon band qila oladi.
LOCK_PORT = 47823

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [supervisor] {msg}\n")


def _rotate():
    if os.path.exists(LOG) and os.path.getsize(LOG) > LOG_MAX:
        os.replace(LOG, LOG + ".1")


def _python():
    # pythonw.exe o'rniga python.exe — bot stdout/stderr'ga yozadi.
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[:-len("pythonw.exe")] + "python.exe"
    return exe


def main():
    os.makedirs(DATA, exist_ok=True)
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        return  # boshqa nusxa allaqachon ishlayapti

    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)

    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    while True:
        _rotate()
        _log("bot.py ishga tushirilmoqda")
        with open(LOG, "a", encoding="utf-8") as out:
            code = subprocess.call(
                [_python(), "bot.py"],
                cwd=BASE,
                env=env,
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        _log(f"bot.py to'xtadi (kod {code}), {RESTART_DELAY}s dan keyin qayta")
        time.sleep(RESTART_DELAY)


if __name__ == "__main__":
    main()
