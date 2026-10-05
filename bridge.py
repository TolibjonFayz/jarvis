"""Telefon <-> kompyuter ko'prigi: fayl yuborish/saqlash va clipboard.

- find_files / latest_file: kompyuterdan fayl topish (Desktop, Downloads, Documents,
  Screenshots va READ_ROOT). Maxfiy fayllar (.env, *.session, kalitlar, token/credential
  json, parol bazalari, FRIDAY'ning data papkasi) HECH QACHON berilmaydi.
- save_incoming: Telegram'dan kelgan fayl -> Downloads\\FRIDAY (ustiga yozmaydi).
- clipboard_set / clipboard_get: matn, rasm (Win+Shift+S) va Explorer'da nusxalangan fayllar.

Telegram cheklovlari: bot 50MB gacha yubora oladi, lekin faqat 20MB gacha yuklab oladi.
"""
import ctypes
import datetime
import fnmatch
import os
import re
import tempfile
import time
from ctypes import wintypes

from config import BASE_DIR, READ_ROOT

SEND_MAX = 50 * 1024 * 1024
RECV_MAX = 20 * 1024 * 1024
HOME = os.path.expanduser("~")
SAVE_DIR = os.path.join(HOME, "Downloads", "FRIDAY")

FOLDERS = {
    "downloads": os.path.join(HOME, "Downloads"),
    "desktop": os.path.join(HOME, "Desktop"),
    "documents": os.path.join(HOME, "Documents"),
    "screenshots": os.path.join(HOME, "Pictures", "Screenshots"),
}
# OneDrive yoqilgan bo'lsa Desktop/Documents u yerda bo'ladi
for _k, _sub in (("desktop", "Desktop"), ("documents", "Documents")):
    _od = os.path.join(HOME, "OneDrive", _sub)
    if not os.path.isdir(FOLDERS[_k]) and os.path.isdir(_od):
        FOLDERS[_k] = _od

_SECRET_NAMES = (
    ".env", ".env.*", "*.env", "*.session", "*.session-journal", "*.pem", "*.key", "*.pfx", "*.p12",
    "id_rsa*", "id_ed25519*", "*.kdbx", "*.keystore", "*.jks", "google_token.json",
    "google_client.json", "credentials*.json", "*secret*", "*password*", "*parol*",
    "token.json", "*.ovpn", "wallet.dat",
)
_SECRET_DIRS = {".ssh", ".gnupg", ".aws", ".git", "appdata"}
_SKIP_DIRS = {"node_modules", ".git", "venv", ".venv", "__pycache__", "build", "dist", ".dart_tool",
              ".gradle", ".idea", ".next", ".nuxt", ".output", "coverage", "vendor", "target", "bin", "obj"}
_FRIDAY_DATA = os.path.normcase(os.path.abspath(os.path.join(BASE_DIR, "data")))


def is_secret(path):
    full = os.path.normcase(os.path.abspath(path))
    if full == _FRIDAY_DATA or full.startswith(_FRIDAY_DATA + os.sep):
        return True
    parts = {p.lower() for p in full.split(os.sep)}
    if parts & _SECRET_DIRS:
        return True
    name = os.path.basename(full).lower()
    return any(fnmatch.fnmatch(name, pat) for pat in _SECRET_NAMES)


def _allowed_roots():
    roots = [p for p in FOLDERS.values() if os.path.isdir(p)]
    if os.path.isdir(READ_ROOT):
        roots.append(READ_ROOT)
    return roots


def allowed(path):
    full = os.path.normcase(os.path.abspath(path))
    ok = any(full == os.path.normcase(r) or full.startswith(os.path.normcase(r) + os.sep)
             for r in _allowed_roots())
    return ok and not is_secret(path)


def size_text(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _walk(root, depth):
    root_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath.count(os.sep) - root_depth >= depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIRS and not d.startswith(".")]
        for f in filenames:
            yield os.path.join(dirpath, f)


def find_files(query, limit=5, time_budget=6.0):
    """Nomida so'rovdagi hamma so'z bor fayllar — eng yangisi birinchi.
    To'liq yo'l berilsa — o'sha fayl (ruxsat bo'lsa)."""
    q = (query or "").strip().strip('"\'')
    if os.path.isabs(q):
        return [q] if os.path.isfile(q) and allowed(q) else []
    words = [w for w in re.split(r"[\s_\-]+", q.lower()) if w]
    if not words:
        return []
    start, found = time.time(), []
    # Kundalik papkalar chuqurroq emas, loyihalar papkasi (READ_ROOT) chuqurroq
    plan = [(p, 3) for p in FOLDERS.values() if os.path.isdir(p)]
    if os.path.isdir(READ_ROOT):
        plan.append((READ_ROOT, 5))
    seen = set()
    for root, depth in plan:
        for path in _walk(root, depth):
            if time.time() - start > time_budget:
                break
            name = os.path.basename(path).lower()
            if all(w in name for w in words):
                key = os.path.normcase(path)
                if key not in seen and not is_secret(path):
                    seen.add(key)
                    found.append(path)
    exact = [p for p in found if os.path.basename(p).lower() == q.lower()]
    found.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
    return (exact + [p for p in found if p not in exact])[:limit]


def latest_file(folder="downloads"):
    root = FOLDERS.get(folder)
    if not root or not os.path.isdir(root):
        return None
    files = [os.path.join(root, f) for f in os.listdir(root)]
    files = [f for f in files if os.path.isfile(f) and not is_secret(f)
             and not f.lower().endswith((".crdownload", ".part", ".tmp", "desktop.ini"))]
    return max(files, key=os.path.getmtime) if files else None


def describe(path):
    st = os.stat(path)
    when = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%d.%m %H:%M")
    return f"{os.path.basename(path)} ({size_text(st.st_size)}, {when})"


# --- Kelgan fayllarni saqlash ---

def _safe_name(name):
    name = os.path.basename(name or "").strip() or "fayl"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    return name[:150]


def save_path(name):
    """Downloads\\FRIDAY\\<nom> — bor bo'lsa '(2)' qo'shiladi (ustiga yozilmaydi)."""
    os.makedirs(SAVE_DIR, exist_ok=True)
    base, ext = os.path.splitext(_safe_name(name))
    path, n = os.path.join(SAVE_DIR, base + ext), 2
    while os.path.exists(path):
        path, n = os.path.join(SAVE_DIR, f"{base} ({n}){ext}"), n + 1
    return path


# --- Clipboard (Windows, ctypes) ---

CF_UNICODETEXT = 13
_u32 = ctypes.windll.user32 if os.name == "nt" else None
_k32 = ctypes.windll.kernel32 if os.name == "nt" else None
if _u32:
    _k32.GlobalAlloc.restype = wintypes.HGLOBAL
    _k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _k32.GlobalLock.restype = ctypes.c_void_p
    _k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _u32.OpenClipboard.argtypes = [wintypes.HWND]
    _u32.SetClipboardData.restype = wintypes.HANDLE
    _u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _u32.GetClipboardData.restype = wintypes.HANDLE
    _u32.GetClipboardData.argtypes = [wintypes.UINT]
    _u32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]


def _open_clipboard():
    for _ in range(20):  # boshqa dastur band qilib turgan bo'lishi mumkin
        if _u32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise RuntimeError("clipboard band (boshqa dastur ushlab turibdi)")


def clipboard_set(text):
    data = text.encode("utf-16-le") + b"\x00\x00"
    _open_clipboard()
    try:
        _u32.EmptyClipboard()
        h = _k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        p = _k32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        _k32.GlobalUnlock(h)
        if not _u32.SetClipboardData(CF_UNICODETEXT, h):
            raise RuntimeError("clipboard'ga yozib bo'lmadi")
    finally:
        _u32.CloseClipboard()


def _clipboard_text():
    if not _u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None
    _open_clipboard()
    try:
        h = _u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = _k32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p)
        finally:
            _k32.GlobalUnlock(h)
    finally:
        _u32.CloseClipboard()


def clipboard_get():
    """("files", [yo'llar]) | ("image", png_yo'l) | ("text", matn) | (None, None).
    Explorer'da nusxalangan fayllar va Win+Shift+S rasmi matndan oldin tekshiriladi."""
    try:
        from PIL import ImageGrab
        content = ImageGrab.grabclipboard()
    except Exception:
        content = None
    if isinstance(content, list) and content:
        files = [f for f in content if os.path.isfile(f)]
        if files:
            return "files", files
    if content is not None and hasattr(content, "save"):
        path = os.path.join(tempfile.gettempdir(), f"friday_clip_{int(time.time())}.png")
        content.save(path, "PNG")
        return "image", path
    text = _clipboard_text()
    if text:
        return "text", text
    return None, None
