"""Bazaning zaxira nusxasi.

- Har kuni: data/backups/jarvis-YYYY-MM-DD.db (oxirgi KEEP_DAYS tasi qoladi).
  SQLite "online backup" — bot yozayotgan paytda ham nusxa izchil bo'ladi.
- Har hafta: siqilgan baza egasining FRIDAY chatiga fayl bo'lib yuboriladi
  (kompyuter/disk buzilsa ham ma'lumot qoladi) — bot.py backup_job.

FAQAT jarvis.db. userbot.session va google_token.json ATAYLAB kirmaydi —
ular akkauntlarga to'liq kirish kalitlari, chatda turishi xavfli.

Tiklash: botni to'xtat -> data/jarvis.db ni zaxira nusxa bilan almashtir
(zip bo'lsa ichidagi jarvis.db) -> botni yoq.
"""
import datetime
import glob
import os
import sqlite3
import zipfile

import config

BACKUP_DIR = os.path.join(config.DATA_DIR, "backups")
KEEP_DAYS = 7


def _snapshot(dest):
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def daily(today=None):
    """Bugungi nusxa bo'lmasa — yaratadi, eskilarini tozalaydi. Yo'lini qaytaradi."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    day = (today or datetime.date.today()).isoformat()
    path = os.path.join(BACKUP_DIR, f"jarvis-{day}.db")
    if not os.path.exists(path):
        tmp = path + ".tmp"
        _snapshot(tmp)
        os.replace(tmp, path)  # yarim yozilgan nusxa "bugungi" bo'lib qolmasin
    for old in sorted(glob.glob(os.path.join(BACKUP_DIR, "jarvis-*.db")))[:-KEEP_DAYS]:
        os.remove(old)
    return path


def weekly_zip(today=None):
    """Chatga yuborish uchun siqilgan nusxa (vaqtinchalik fayl yo'li)."""
    src = daily(today)
    day = (today or datetime.date.today()).isoformat()
    zpath = os.path.join(BACKUP_DIR, f"friday-backup-{day}.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(src, "jarvis.db")
    return zpath


def integrity_ok(path):
    """Nusxa ochiladimi va buzilmaganmi."""
    try:
        c = sqlite3.connect(path)
        ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        c.close()
        return ok
    except sqlite3.Error:
        return False
