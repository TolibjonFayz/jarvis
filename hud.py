"""FRIDAY HUD — kompyuterdagi oyna (JARVIS / FRIDAY / EDITH rejimlari).

Alohida "ikkinchi FRIDAY" emas: bot jarayoni ichidagi kichik lokal server. Oyna — Edge'ning
--app rejimi (brauzer ramkasiz, alohida profil), ichida hud/index.html.

- Faqat 127.0.0.1 da tinglaydi; har /api so'rovi X-HUD-Token sarlavhasini talab qiladi
  (token data/hud_token da, yorliq URL'ida), Host ham tekshiriladi (DNS rebinding).
- /api/state tez qaytadi: sekin ma'lumotlar (ob-havo, kalendar, javobsizlar...) fon oqimida
  keshlanadi, tezlari (CPU/RAM, musiqa, ovoz holati) har so'rovda.
- Amallar QAT'IY ro'yxat (ACTIONS): quvvat (o'chirish/uxlatish) YO'Q — u Telegram tasdig'i bilan.
- Ctrl+Alt+F — oynani ochadi.
"""
import collections
import ctypes
import ctypes.wintypes
import datetime
import json
import logging
import os
import secrets
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config
import memory

log = logging.getLogger("jarvis")

PORT = int(os.getenv("HUD_PORT", "47830"))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hud")
TOKEN_PATH = os.path.join(config.DATA_DIR, "hud_token")
PROFILE_DIR = os.path.join(config.DATA_DIR, "hud_profile")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CITY = "Tashkent"

# Voqealar lentasi (ovozli savol-javob, miya, radar, chat) — HUD pastki qismi uchun
EVENTS = collections.deque(maxlen=80)
_event_id = [0]
_lock = threading.Lock()
_cache = {}
_hooks = {"respond": None}
_net_prev = {"t": 0.0, "sent": 0, "recv": 0}


_last_poll = [0.0]   # HUD oynasi oxirgi marta holat so'ragan vaqt (ochiqmi?)
_greeted = [0.0]


def hud_open():
    return time.time() - _last_poll[0] < 10


def speak_async(text):
    """Kompyuter karnayidan (fon oqimida) — ovoz moduli bo'lsa."""
    def run():
        try:
            import voice_pc
            voice_pc.say(text)
        except Exception as e:
            log.info("HUD: ovoz chiqmadi: %s", str(e)[:80])
    threading.Thread(target=run, name="hud-say", daemon=True).start()


def push(kind, text, who="friday"):
    """kind: chat | voice | mind | radar | system. Radar/miya ogohlantirishi HUD ochiq
    bo'lsa ovoz chiqarib ham aytiladi (Jarvis kabi: "Diqqat, ...")."""
    with _lock:
        _event_id[0] += 1
        EVENTS.append({"id": _event_id[0], "ts": time.time(), "kind": kind,
                       "who": who, "text": (text or "")[:1500]})
    if kind in ("radar", "mind") and hud_open():
        # Matn o'zbekcha (ekranda), ovoz inglizcha — umumiy ibora aytiladi
        speak_async("Heads up, boss. The ERP radar picked something up. Details are on your screen."
                    if kind == "radar" else
                    "Boss, there's something you should know. I've put it on your screen.")


def _part_of_day(h):
    return ("Good morning" if 5 <= h < 12 else "Good afternoon" if h < 17
            else "Good evening" if h < 23 else "Working late, I see")


def greeting(now=None):
    """Oyna ochilganda aytiladigan qisqa holat (AI'siz, keshdan) — inglizcha, Ryan ovozi uchun."""
    now = now or datetime.datetime.now()
    parts = [f"{_part_of_day(now.hour)}, boss. It's {now:%H:%M}."]
    w = _cache.get("weather")
    if w:
        parts.append(f"{w['temp']} degrees in Tashkent.")
    today = now.date().isoformat()
    ag = [a for a in (_cache.get("agenda") or []) if a["day"] == today
          and (a["time"] == "kun bo'yi" or a["time"][:5] >= f"{now:%H:%M}")]
    if ag:
        n = len(ag)
        parts.append(f"You have {n} more {'thing' if n == 1 else 'things'} today, "
                     f"first at {ag[0]['time'][:5]}: {ag[0]['title']}.")
    else:
        parts.append("Nothing else on the schedule today.")
    un = _cache.get("unanswered") or []
    if un:
        parts.append(f"{un[0]['name']} is waiting for your reply"
                     + (f", along with {len(un) - 1} others." if len(un) > 1 else "."))
    r = _cache.get("radar") or {}
    if r.get("configured"):
        n = len(r.get("problems") or [])
        parts.append(f"The ERP radar shows {n} {'issue' if n == 1 else 'issues'}." if n
                     else "All ERP systems are green.")
    return " ".join(parts)


def token():
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH, encoding="utf-8") as f:
            t = f.read().strip()
        if t:
            return t
    t = secrets.token_urlsafe(24)
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        f.write(t)
    return t


def url():
    return f"http://127.0.0.1:{PORT}/#t={token()}"


# --- Ma'lumot yig'uvchilar ---

def _weather():
    import net
    net.prefer_ipv4()
    raw = urllib.request.urlopen(f"https://wttr.in/{CITY}?format=j1&lang=en", timeout=15).read()
    d = json.loads(raw.decode("utf-8"))
    cur = d["current_condition"][0]
    days = [{"date": w["date"], "min": int(w["mintempC"]), "max": int(w["maxtempC"]),
             "desc": w["hourly"][4]["weatherDesc"][0]["value"]} for w in d["weather"][:3]]
    return {"temp": int(cur["temp_C"]), "feels": int(cur["FeelsLikeC"]),
            "desc": cur["weatherDesc"][0]["value"], "humidity": int(cur["humidity"]),
            "wind": int(cur["windspeedKmph"]), "days": days}


def _prayer():
    import tools
    now = datetime.datetime.now()
    out = []
    for d in (now.date(), now.date() + datetime.timedelta(days=1)):
        t = tools._prayer_times(CITY, d)
        for eng, uz in tools.PRAYERS:
            h, m = map(int, t[eng].split()[0].split(":"))
            out.append({"name": uz, "at": datetime.datetime.combine(d, datetime.time(h, m)).timestamp()})
    return out


def _agenda():
    import gcal
    owner = config.OWNER_ID
    items = []
    if gcal.available():
        for e in gcal.events_between(datetime.date.today(), 2):
            items.append({"kind": "event", "day": e["day"].isoformat(), "time": e["time"],
                          "title": e["title"]})
    for text, due in memory.list_pending_reminders(owner):
        if due - time.time() < 2 * 86400 and "namozi vaqti" not in text:
            dt = datetime.datetime.fromtimestamp(due)
            items.append({"kind": "reminder", "day": dt.date().isoformat(),
                          "time": f"{dt:%H:%M}", "title": text})
    items.sort(key=lambda x: (x["day"], x["time"]))
    return items


def _todos():
    return [t for _id, t in memory.list_todos(config.OWNER_ID)][:12]


def _money():
    import tools
    owner = config.OWNER_ID
    spent = tools._month_spent(owner)
    budgets = memory.list_budgets(owner)
    return {"spent": spent.get("jami", 0),
            "budgets": [{"cat": c, "limit": lim, "spent": spent.get(c, 0)} for c, lim in budgets.items()]}


def _football():
    if memory.get_setting(config.OWNER_ID, "football", "0") != "1":
        return None
    import football
    ms = football.fixtures()
    if not ms:
        return None
    m = ms[0]
    return {"title": football.match_title(m), "at": m["kickoff"].timestamp()}


def _unanswered():
    import userbot
    items = userbot.unanswered(min_minutes=60, max_days=3) or []
    return [{"name": u["name"], "minutes": u["minutes"], "unread": u["unread"]} for u in items[:8]]


def _radar():
    import radar
    if not radar.configured():
        return {"configured": False}
    try:
        state = json.loads(memory.get_setting(config.OWNER_ID, "radar_state", "{}") or "{}")
    except ValueError:
        state = {}
    return {"configured": True, "on": memory.get_setting(config.OWNER_ID, "radar_on", "1") == "1",
            "problems": [s.get("text", k) for k, s in state.items() if s.get("alerted")]}


def _mind():
    import proactive
    today = datetime.date.today()
    rows = [r for r in proactive._log_rows(days=1)
            if "key" in r and datetime.datetime.fromtimestamp(r["ts"]).date() == today]
    return {"sent": sum(1 for r in rows if r["sent"]), "thought": len(rows),
            "last": [r["text"] for r in rows if r["sent"]][-2:]}


def _usage():
    used = sum(memory.usage_since(24).values())
    return {"tokens": used, "limit": 200_000}


PING_HOSTS = [("Telegram", "api.telegram.org"), ("Groq", "api.groq.com"),
              ("ERP", "erpclimaventbackend-production.up.railway.app")]


def _ping():
    """TCP ulanish vaqti (ms) — haqiqiy ICMP emas, lekin xizmatgacha yo'lni ko'rsatadi."""
    import socket
    out = []
    for name, host in PING_HOSTS:
        t = time.time()
        try:
            socket.create_connection((host, 443), timeout=5).close()
            out.append({"name": name, "ms": int((time.time() - t) * 1000)})
        except OSError:
            out.append({"name": name, "ms": None})
    return out


SLOW = {  # nom: (funksiya, yangilash oralig'i, soniya)
    "weather": (_weather, 1800), "prayer": (_prayer, 3 * 3600), "agenda": (_agenda, 300),
    "todos": (_todos, 60), "money": (_money, 300), "football": (_football, 1800),
    "unanswered": (_unanswered, 600), "radar": (_radar, 60), "mind": (_mind, 120),
    "usage": (_usage, 120), "ping": (_ping, 30),
}


def _refresh_loop():
    due = {k: 0.0 for k in SLOW}
    while True:
        for name, (fn, every) in SLOW.items():
            if time.time() < due[name]:
                continue
            due[name] = time.time() + every
            try:
                _cache[name] = fn()
            except Exception as e:
                due[name] = time.time() + min(every, 120)  # xato bo'lsa tezroq qayta
                log.info("HUD: %s olinmadi: %s", name, str(e)[:80])
        time.sleep(5)


_cpu = [0.0]
_procs = [[]]


def _top_procs(n=3):
    """Eng ko'p CPU yeyayotgan dasturlar (nom bo'yicha jamlangan). process_iter Process
    obyektlarini keshlaydi — cpu_percent ikkinchi chaqiruvdan to'g'ri ishlaydi."""
    import psutil
    agg = {}
    cores = psutil.cpu_count() or 1
    for p in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
        info = p.info
        name = (info.get("name") or "?").removesuffix(".exe")
        if name in ("System Idle Process", "Idle", "System"):
            continue
        a = agg.setdefault(name, {"name": name, "cpu": 0.0, "mem": 0})
        a["cpu"] += (info.get("cpu_percent") or 0) / cores
        a["mem"] += getattr(info.get("memory_info"), "rss", 0) or 0
    top = sorted(agg.values(), key=lambda a: (a["cpu"], a["mem"]), reverse=True)[:n]
    return [{"name": a["name"], "cpu": round(a["cpu"], 1), "mem_mb": a["mem"] // 2**20} for a in top]


def _cpu_loop():
    """cpu_percent(interval=None) bir necha oqimdan chaqirilganda doim 0 qaytardi —
    alohida oqimda 1 s oraliqda o'lchaymiz (har 3-sida jarayonlar ham)."""
    import psutil
    i = 0
    while True:
        try:
            _cpu[0] = psutil.cpu_percent(interval=1)
            i += 1
            if i % 3 == 0 and hud_open():
                _procs[0] = _top_procs()
        except Exception:
            time.sleep(5)


def _system():
    import psutil
    now = time.time()
    io = psutil.net_io_counters()
    dt = now - _net_prev["t"] if _net_prev["t"] else 0
    up = (io.bytes_sent - _net_prev["sent"]) / dt if dt else 0
    down = (io.bytes_recv - _net_prev["recv"]) / dt if dt else 0
    _net_prev.update(t=now, sent=io.bytes_sent, recv=io.bytes_recv)
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("C:\\")
    bat = psutil.sensors_battery()
    return {"cpu": _cpu[0], "ram": vm.percent,
            "ram_used": round(vm.used / 2**30, 1), "ram_total": round(vm.total / 2**30, 1),
            "disk": disk.percent, "disk_free": round(disk.free / 2**30),
            "net_up": int(up), "net_down": int(down),
            "uptime": int(now - psutil.boot_time()),
            "battery": bat.percent if bat else None, "procs": _procs[0]}


def _music():
    try:
        import nowplaying
        np_ = nowplaying.now_playing()
    except Exception:
        return None
    if not np_:
        return None
    return {"title": np_["title"], "artist": np_["artist"], "app": np_["app"],
            "playing": int(np_["status"]) == 4, "position": np_["position"], "duration": np_["duration"]}


def _voice():
    try:
        import voice_pc
        return {"state": voice_pc.STATE, "level": round(voice_pc.LEVEL, 2),
                "ready": bool(voice_pc._instance and voice_pc._instance.running)}
    except Exception:
        return {"state": "off", "ready": False}


def state():
    return {"now": time.time(), "system": _system(), "music": _music(), "voice": _voice(),
            **{k: _cache.get(k) for k in SLOW}}


# --- Amallar (qat'iy ro'yxat) ---

def _act_media(arg):
    import pc
    return pc.media({"play": "play_pause", "next": "next", "prev": "prev",
                     "up": "volume_up", "down": "volume_down", "mute": "mute"}[arg])


def _act_lock(_arg):
    import pc
    pc.lock()
    return "🔒 Ekran qulflandi"


def _act_open(arg):
    import pc
    return pc.open_app(arg)


def _act_mind(_arg):
    import proactive
    alerts = proactive.run(config.OWNER_ID, None, True)
    for a in alerts:
        push("mind", a["text"])
    return f"🧠 {len(alerts)} ta muhim narsa" if alerts else "🧠 Hozircha aytishga arziydigan narsa yo'q"


def _act_radar(_arg):
    import radar
    problems = radar.check()
    _cache["radar"] = _radar()
    return "🛰 " + ("; ".join(problems.values()) if problems else "ERP: hammasi joyida")


def _act_listen(_arg):
    import voice_pc
    inst = voice_pc._instance
    if not inst or not inst.running:
        raise ValueError("kompyuter ovozi ishga tushmagan")
    if inst.busy:
        return "🎙 allaqachon tinglayapman"
    inst.trigger.set()
    return "🎙 Gapiring"


ACTIONS = {"media": _act_media, "lock": _act_lock, "open": _act_open,
           "mind": _act_mind, "radar": _act_radar, "listen": _act_listen}


def run_action(name, arg=""):
    fn = ACTIONS.get(name)
    if not fn:
        raise ValueError(f"noma'lum amal: {name}")
    return fn(arg)


def chat(text, speak=False):
    text = (text or "").strip()[:2000]
    if not text:
        raise ValueError("bo'sh xabar")
    push("chat", text, who="you")
    reply = _hooks["respond"](text) if _hooks["respond"] else "FRIDAY hali ulanmagan"
    push("chat", reply)
    if speak:
        speak_async(reply)
    return reply


def greet(force=False):
    """Oyna ochilganda bir marta (20 daqiqada ko'pi bilan) — ovoz chiqarib salomlashadi."""
    if not force and time.time() - _greeted[0] < 20 * 60:
        return None
    _greeted[0] = time.time()
    text = greeting()
    push("system", text)
    speak_async(text)
    return text


# --- HTTP server ---

_TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".ico": "image/x-icon",
          ".png": "image/png"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _allowed(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _authed(self):
        return self._allowed() and secrets.compare_digest(
            self.headers.get("X-HUD-Token", ""), token())

    def do_GET(self):
        if not self._allowed():
            return self._send(403, {"error": "forbidden"})
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            if not self._authed():
                return self._send(401, {"error": "token"})
            if path == "/api/state":
                _last_poll[0] = time.time()
                return self._send(200, state())
            if path == "/api/events":
                try:
                    since = int(self.path.split("since=")[1]) if "since=" in self.path else 0
                except ValueError:
                    since = 0
                with _lock:
                    return self._send(200, [e for e in EVENTS if e["id"] > since])
            return self._send(404, {"error": "not found"})
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC_DIR, name))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        with open(full, "rb") as f:
            self._send(200, f.read(), _TYPES.get(os.path.splitext(full)[1], "application/octet-stream"))

    def do_POST(self):
        if not self._authed():
            return self._send(401, {"error": "token"})
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 20000)
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/chat":
                return self._send(200, {"reply": chat(body.get("text", ""), bool(body.get("speak")))})
            if self.path == "/api/greet":
                return self._send(200, {"text": greet(bool(body.get("force")))})
            if self.path == "/api/action":
                msg = run_action(body.get("name", ""), body.get("arg", ""))
                push("system", msg)
                return self._send(200, {"ok": True, "message": msg})
            return self._send(404, {"error": "not found"})
        except (ValueError, KeyError) as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            log.warning("HUD so'rov xatosi: %s", str(e)[:150])
            return self._send(500, {"error": "ichki xato"})


# --- Oyna va hotkey ---

def open_window():
    os.makedirs(PROFILE_DIR, exist_ok=True)
    subprocess.Popen([EDGE, f"--app={url()}", f"--user-data-dir={PROFILE_DIR}",
                      "--window-size=1500,920", "--no-first-run", "--no-default-browser-check",
                      "--autoplay-policy=no-user-gesture-required"])  # ochilish tovushi uchun


ICON_PATH = os.path.join(config.DATA_DIR, "friday.ico")


def make_icon():
    """Arc reactor ikonkasi (yorliq uchun .ico)."""
    from PIL import Image, ImageDraw
    s = 256
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=56, fill=(3, 7, 13, 255))
    d.ellipse((28, 28, s - 28, s - 28), outline=(56, 214, 255, 130), width=6)
    for i in range(12):  # tishli halqa
        d.arc((60, 60, s - 60, s - 60), i * 30, i * 30 + 20, fill=(56, 214, 255, 255), width=16)
    d.ellipse((96, 96, s - 96, s - 96), fill=(191, 243, 255, 255))
    im.save(ICON_PATH, sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
    return ICON_PATH


def make_shortcut():
    """Ish stolida FRIDAY.lnk (Edge --app oynasi). Yo'l qaytaradi."""
    if not os.path.exists(ICON_PATH):
        make_icon()
    os.makedirs(PROFILE_DIR, exist_ok=True)
    ps = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'FRIDAY.lnk'));"
        f"$s.TargetPath='{EDGE}';"
        f"$s.Arguments='--app={url()} --user-data-dir=\"{PROFILE_DIR}\" --window-size=1500,920 "
        "--autoplay-policy=no-user-gesture-required';"
        f"$s.IconLocation='{ICON_PATH},0';"
        "$s.Description='FRIDAY HUD (Ctrl+Alt+F)';$s.Save();Join-Path $d 'FRIDAY.lnk'"
    )
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                         timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if out.returncode:
        raise OSError(out.stderr.strip()[:200])
    return out.stdout.strip()


def _hotkey_loop():
    user32 = ctypes.windll.user32
    if not user32.RegisterHotKey(None, 2, 0x1 | 0x2 | 0x4000, 0x46):  # Ctrl+Alt+F
        log.warning("HUD: Ctrl+Alt+F band — oynani yorliq orqali oching")
        return
    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == 0x0312:
            try:
                open_window()
            except Exception as e:
                log.warning("HUD oynasi ochilmadi: %s", e)


def start(respond):
    """Bot ishga tushganda: server + fon keshi + hotkey."""
    _hooks["respond"] = respond
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        log.warning("HUD o'chiq: port %s band (%s)", PORT, e)
        return None
    threading.Thread(target=server.serve_forever, name="hud-http", daemon=True).start()
    threading.Thread(target=_refresh_loop, name="hud-cache", daemon=True).start()
    threading.Thread(target=_cpu_loop, name="hud-cpu", daemon=True).start()
    if os.name == "nt":
        threading.Thread(target=_hotkey_loop, name="hud-hotkey", daemon=True).start()
    log.info("HUD: http://127.0.0.1:%s (Ctrl+Alt+F)", PORT)
    push("system", "Barcha tizimlar onlayn.")
    return server
