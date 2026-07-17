"""Guruh xavfsizligi: CAS spamer bazasi + xavfli link tekshiruvi."""
import os
import re
import json
import ipaddress
import urllib.request
import urllib.parse

from config import DATA_DIR

BLOCKLIST_FILE = os.path.join(DATA_DIR, "blocklist.txt")


# --- CAS: Combot Anti-Spam (bepul, kalitsiz) ---
# Minglab guruhlar bo'ylab ma'lum spamerlar bazasi.

def is_cas_banned(user_id):
    """Foydalanuvchi CAS spamer bazasida bormi? Xato bo'lsa False (guruh to'xtamasin)."""
    try:
        url = f"https://api.cas.chat/check?user_id={int(user_id)}"
        data = json.loads(urllib.request.urlopen(url, timeout=10).read().decode("utf-8"))
        return bool(data.get("ok"))
    except Exception:
        return False


# --- Xavfli link tekshiruvi ---

_URL_RE = re.compile(r"(https?://[^\s]+|www\.[^\s]+)", re.IGNORECASE)

# Ko'p suiiste'mol qilinadigan bepul domenlar (URL host bo'yicha).
_BAD_TLD_RE = re.compile(r"\.(tk|ml|ga|cf|gq)(/|$|\?|#)", re.IGNORECASE)

# Scam iboralari — LINK bilan birga kelsa xavfli (yolg'iz matnда emas).
_SCAM_TEXT_RE = re.compile(
    r"free.?(nft|crypto|bitcoin|ton|usdt)"
    r"|telegram.?premium.?(free|bepul)"
    r"|claim.?(your)?.?(reward|gift|airdrop|prize)"
    r"|double.?your.?(money|crypto|deposit)"
    r"|(bepul|tekin).?(pul|kripto|bitcoin)",
    re.IGNORECASE,
)

_blocklist_cache = None


def _blocklist():
    """data/blocklist.txt dan domenlar (bir qatorda bittadan). Keshlaydi."""
    global _blocklist_cache
    if _blocklist_cache is None:
        _blocklist_cache = set()
        try:
            with open(BLOCKLIST_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    d = line.strip().lower().lstrip("*.")
                    if d and not d.startswith("#"):
                        _blocklist_cache.add(d)
        except FileNotFoundError:
            pass
    return _blocklist_cache


def _host(url):
    if not url.lower().startswith("http"):
        url = "http://" + url
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _is_ip(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def find_dangerous_links(text):
    """Matndan xavfli linklarni topadi. (bor_yoqmi, sabab)."""
    if not text:
        return False, ""
    blocklist = _blocklist()
    urls = [m.group(0).rstrip(".,!?)") for m in _URL_RE.finditer(text)]
    for url in urls:
        host = _host(url)
        if not host:
            continue
        # 1) IP-manzilli link — chatда deyarli har doim xavfli
        if _is_ip(host):
            return True, "xavfli link (IP-manzil)"
        # 2) Qora ro'yxatdagi domen
        if any(host == b or host.endswith("." + b) for b in blocklist):
            return True, "xavfli link (qora ro'yxat)"
        # 3) Suiiste'mol qilinadigan bepul domen
        if _BAD_TLD_RE.search(url):
            return True, "shubhali link (xavfli domen)"
    # 4) Scam iboralari + link birga bo'lsa
    if urls and _SCAM_TEXT_RE.search(text):
        return True, "shubhali/scam link"
    return False, ""
