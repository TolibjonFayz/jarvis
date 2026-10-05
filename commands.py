"""Ruxsat berilgan buyruqlar: build/test/git pull va dev serverlar — Telegram'dan.

Xavfsizlik:
- FAQAT data/commands.json dagi buyruqlar, identifikator bo'yicha. Model buyruq matnini
  yoki argument bera olmaydi (tool sxemasida enum).
- Prod bazaga yozadigan skriptlar (db:migrate, *:import, media:upload), fayllarni jim
  o'zgartiradiganlar (lint --fix, format) va prod'ga ulanadigan backend dev serverlar
  ATAYLAB ro'yxatda yo'q (egasi bilan kelishilgan, 2026-10-05).
- git pull --ff-only: merge qilmaydi, lokal o'zgarishlarni buzmaydi.

Turlar: "run" — tugashini kutadi, xulosa qaytaradi; "serve" — fonda ishlaydi
(log: data/proc/<id>.log, pid fayl bot qayta yoqilsa ham to'xtatish uchun).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

import config

CONFIG = os.path.join(config.DATA_DIR, "commands.json")
PROC_DIR = os.path.join(config.DATA_DIR, "proc")
RUN_TIMEOUT = 600
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?::\d+)?[^\s\"'<>]*")

_P = r"D:\Tolibjon\Programming"
_C = r"D:\Tolibjon\Claude"
FLUTTER = r"D:\dev\flutter\bin\flutter.bat"


def _npm(*a):
    return ["npm", "run", *a]


def default_commands():
    """2026-10-05 da egasi tasdiqlagan ro'yxat (faol loyihalar)."""
    erp_f = rf"{_P}\Climavent\erp_climavent_frontend"
    admin = rf"{_P}\Climavent\admin-climavent-front"
    nuxt = rf"{_P}\Climavent\Climavent_front_nuxt"
    erp_b = rf"{_P}\Climavent\erp_climavent_backend"
    cv_b = rf"{_P}\Climavent\climavent-backend"
    fit = rf"{_C}\fit-uz"
    block = rf"{_P}\block-combo"
    jarvis = rf"{_C}\jarvis"
    cmds = [
        ("erp-front-dev", "ERP frontend — dev server", erp_f, _npm("dev"), "serve"),
        ("erp-front-build", "ERP frontend — build", erp_f, _npm("build"), "run"),
        ("admin-dev", "Admin panel — dev server", admin, _npm("dev"), "serve"),
        ("admin-build", "Admin panel — build", admin, _npm("build"), "run"),
        ("nuxt-dev", "Climavent sayt (Nuxt) — dev server", nuxt, _npm("dev"), "serve"),
        ("nuxt-build", "Climavent sayt (Nuxt) — build", nuxt, _npm("build"), "run"),
        ("erp-back-build", "ERP backend — build", erp_b, _npm("build"), "run"),
        ("erp-back-test", "ERP backend — test", erp_b, ["npm", "test"], "run"),
        ("climavent-back-build", "Climavent backend — build", cv_b, _npm("build"), "run"),
        ("climavent-back-test", "Climavent backend — test", cv_b, ["npm", "test"], "run"),
        ("fit-foods-verify", "fit-uz — ovqatlar bazasini tekshirish", fit, _npm("foods:verify"), "run"),
        ("block-test", "block-combo — flutter test", block, [FLUTTER, "test"], "run"),
        ("block-analyze", "block-combo — flutter analyze", block, [FLUTTER, "analyze"], "run"),
        ("friday-test", "FRIDAY — o'z testlari (pytest)", jarvis, [sys.executable, "-m", "pytest"], "run"),
    ]
    for name, path in [("erp-front", erp_f), ("admin", admin), ("nuxt", nuxt), ("erp-back", erp_b),
                       ("climavent-back", cv_b), ("fit", fit), ("block", block), ("friday", jarvis)]:
        cmds.append((f"{name}-pull", f"{os.path.basename(path)} — git pull", path,
                     ["git", "pull", "--ff-only"], "run"))
    return [{"id": i, "name": n, "cwd": c, "cmd": cmd, "type": t} for i, n, c, cmd, t in cmds]


def load():
    """data/commands.json; yo'q bo'lsa — standart ro'yxat bilan yaratadi (egasi tahrirlay oladi)."""
    if not os.path.exists(CONFIG):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump({"commands": default_commands()}, f, ensure_ascii=False, indent=2)
    with open(CONFIG, encoding="utf-8") as f:
        return {c["id"]: c for c in json.load(f).get("commands", [])}


def ids():
    try:
        return sorted(load())
    except (OSError, ValueError):
        return []


def _argv(cmd):
    exe = shutil.which(cmd[0]) or cmd[0]  # npm -> npm.CMD (Windows)
    return [exe, *cmd[1:]]


def _tail(text, n=15):
    lines = [l.rstrip() for l in _ANSI.sub("", text or "").splitlines() if l.strip()]
    return "\n".join(lines[-n:])


def run(cid):
    """'run' turidagi buyruq: tugashini kutadi. Natija (Markdown)."""
    c = load().get(cid)
    if not c:
        return f"'{cid}' ro'yxatda yo'q."
    if c["type"] == "serve":
        return start(cid)
    if not os.path.isdir(c["cwd"]):
        return f"❌ Papka topilmadi: {c['cwd']}"
    t = time.time()
    try:
        r = subprocess.run(
            _argv(c["cmd"]), cwd=c["cwd"], capture_output=True, timeout=RUN_TIMEOUT,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return f"⏱ **{c['name']}** {RUN_TIMEOUT // 60} daqiqada tugamadi — to'xtatildi."
    except OSError as e:
        return f"❌ **{c['name']}** ishga tushmadi: {e}"
    dt = time.time() - t
    out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    head = "✅" if r.returncode == 0 else f"❌ (kod {r.returncode})"
    return f"{head} **{c['name']}** — {dt:.0f}s\n```\n{_tail(out) or '(chiqish yo‘q)'}\n```"


# --- Dev serverlar ---

def _pid_file(cid):
    return os.path.join(PROC_DIR, f"{cid}.pid")


def _alive(pid):
    import psutil
    try:
        return psutil.Process(pid).is_running()
    except psutil.Error:
        return False


def _running_pid(cid):
    try:
        pid = int(open(_pid_file(cid)).read().strip())
    except (OSError, ValueError):
        return None
    return pid if _alive(pid) else None


def start(cid, wait=20):
    c = load().get(cid)
    if not c:
        return f"'{cid}' ro'yxatda yo'q."
    if c["type"] != "serve":
        return run(cid)
    pid = _running_pid(cid)
    if pid:
        return f"🟢 **{c['name']}** allaqachon ishlayapti (pid {pid}). To'xtatish: «{cid}ni to'xtat»."
    os.makedirs(PROC_DIR, exist_ok=True)
    log_path = os.path.join(PROC_DIR, f"{cid}.log")
    log = open(log_path, "wb")
    p = subprocess.Popen(
        _argv(c["cmd"]), cwd=c["cwd"], stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
    )
    with open(_pid_file(cid), "w") as f:
        f.write(str(p.pid))
    # Manzil chiqquncha kutamiz (Vite/Nuxt "Local: http://localhost:5173")
    url, deadline = None, time.time() + wait
    while time.time() < deadline and p.poll() is None:
        time.sleep(1)
        text = _ANSI.sub("", open(log_path, encoding="utf-8", errors="replace").read())
        m = _URL.search(text)
        if m:
            url = m.group(0).rstrip(".,/") + "/"
            break
    if p.poll() is not None:
        return f"❌ **{c['name']}** darrov to'xtadi (kod {p.returncode}):\n```\n{_tail(open(log_path, encoding='utf-8', errors='replace').read())}\n```"
    return f"🟢 **{c['name']}** ishga tushdi (pid {p.pid})" + (f" — {url}" if url else " (manzil hali chiqmadi, log: data/proc)")


def stop(cid):
    import psutil
    c = load().get(cid, {"name": cid})
    pid = _running_pid(cid)
    if not pid:
        return f"**{c['name']}** ishlamayapti."
    proc = psutil.Process(pid)
    kids = proc.children(recursive=True)  # npm -> node: butun daraxtni to'xtatamiz
    for p in kids + [proc]:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _gone, alive = psutil.wait_procs(kids + [proc], timeout=5)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    try:
        os.remove(_pid_file(cid))
    except OSError:
        pass
    return f"⏹ **{c['name']}** to'xtatildi."


def list_text():
    cmds = load()
    servers = [c for c in cmds.values() if c["type"] == "serve"]
    runs = [c for c in cmds.values() if c["type"] == "run"]
    out = ["🛠 **Ruxsat berilgan buyruqlar**", "\n**Dev serverlar**"]
    for c in servers:
        pid = _running_pid(c["id"])
        out.append(f"{'🟢' if pid else '⚪'} `{c['id']}` — {c['name']}")
    out.append("\n**Bir martalik**")
    out += [f"• `{c['id']}` — {c['name']}" for c in runs]
    out.append(f"\nRo'yxatni o'zgartirish: `{CONFIG}`")
    return "\n".join(out)
