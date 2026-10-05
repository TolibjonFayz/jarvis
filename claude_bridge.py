"""Claude Code ko'prigi: Telegram'dan kod vazifasi -> kompyuterda `claude -p` -> natija.

Xavfsizlik (egasi bilan kelishilgan, 2026-10-05):
- Faqat TASDIQ tugmasidan keyin boshlanadi (bot.on_button, kind="code_task").
- Faqat TOZA loyihada (commit qilinmagan o'zgarish bo'lsa — rad): egasining ishi
  Claude o'zgarishlari bilan aralashmasin, «Bekor qilish» faqat Claude'nikini oladi.
- Claude'ga faqat Read/Edit/Write/Glob/Grep (--tools): terminal, git push, internet YO'Q.
- Natija: xulosa + o'zgargan fayllar + [Commit] [Diff] [Bekor qilish]. Bekor qilish =
  git stash (o'chirmaydi — `git stash pop` bilan qaytadi). Push qilinmaydi.
- Bir vaqtda bitta vazifa, 20 daqiqa chegara. Obuna limitidan sarflanadi.
"""
import glob
import json
import os
import re
import subprocess
import threading
import time

TIMEOUT = 20 * 60
MAX_TURNS = 40
TOOLS = "Read,Edit,Write,Glob,Grep"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_PKG = os.path.expandvars(
    r"%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude-code"
)
_ROAMING = os.path.expandvars(r"%APPDATA%\Claude\claude-code")

_busy = threading.Lock()
RESULTS = {}  # tid -> {repo, path, task}
_seq = iter(range(1, 10**9))

_PROMPT = (
    "Sen egasining loyihasida kichik va aniq o'zgarish qilasan.\n"
    "Vazifa: {task}\n\n"
    "Qoidalar: faqat shu loyiha papkasida ishla; vazifaga kerakli minimal o'zgarish; "
    "mavjud uslubga moslash; terminal buyruqlarini ishlata olmaysan (testlarni ham). "
    "Vazifa noaniq bo'lsa yoki xavfli tuyulsa — hech narsani o'zgartirma, nimani "
    "aniqlashtirish kerakligini yoz.\n"
    "Oxirida O'ZBEK tilida qisqa xulosa yoz (5 qatorgacha): nima o'zgardi va qaysi "
    "fayllarda, nima tekshirilmadi."
)


def find_cli():
    """Eng yangi claude.exe. Bot MSIX tashqarisida ishlaydi -> Packages\\...\\LocalCache yo'li
    (versiya/hash papkalari yangilanishda o'zgaradi — har safar qidiriladi)."""
    if os.environ.get("CLAUDE_CLI") and os.path.exists(os.environ["CLAUDE_CLI"]):
        return os.environ["CLAUDE_CLI"]

    def ver(p):
        v = os.path.basename(os.path.dirname(os.path.dirname(p)))
        return tuple(int(x) for x in re.findall(r"\d+", v))

    for base in (_PKG, _ROAMING):
        found = glob.glob(os.path.join(base, "*", "*", "claude.exe"))
        if found:
            return max(found, key=ver)
    return None


def _git(path, *args, timeout=30):
    r = subprocess.run(["git", "-C", path, *args], capture_output=True, timeout=timeout,
                       creationflags=_NO_WINDOW)
    # Faqat oxiridan kesamiz: `git status --porcelain` qatori bo'sh joy bilan boshlanadi
    # (" M app.txt") — strip() birinchi fayl nomidan harf yeb qo'yardi ("pp.txt").
    return r.returncode, (r.stdout or b"").decode("utf-8", "replace").rstrip()


def preflight(path):
    """None — tayyor; aks holda nima uchun boshlab bo'lmasligi."""
    if not find_cli():
        return "Claude Code CLI topilmadi (desktop ilova o'rnatilganmi?)."
    if not os.path.isdir(os.path.join(path, ".git")):
        return "Bu papka git repo emas — Claude o'zgarishlarini qaytarib bo'lmaydi."
    code, status = _git(path, "status", "--porcelain")
    if code != 0:
        return "git status ishlamadi."
    if status:
        n = len(status.splitlines())
        return (f"Loyihada {n} ta commit qilinmagan o'zgarish bor — avval commit qil "
                "(sening ishing Claude'niki bilan aralashmasin).")
    if _busy.locked():
        return "Hozir boshqa Claude vazifasi ishlayapti — tugashini kut."
    return None


def run_task(path, task):
    """Bloklaydi (bot fon oqimida chaqiradi). Natija dict."""
    if not _busy.acquire(blocking=False):
        return {"ok": False, "error": "Hozir boshqa Claude vazifasi ishlayapti."}
    t = time.time()
    try:
        cmd = [find_cli(), "-p", _PROMPT.format(task=task), "--output-format", "json",
               "--permission-mode", "acceptEdits", "--tools", TOOLS, "--max-turns", str(MAX_TURNS)]
        if os.environ.get("CLAUDE_CODE_MODEL"):
            cmd += ["--model", os.environ["CLAUDE_CODE_MODEL"]]
        try:
            r = subprocess.run(cmd, cwd=path, capture_output=True, timeout=TIMEOUT,
                               stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"{TIMEOUT // 60} daqiqada tugamadi — to'xtatildi.",
                    **changes(path)}
        raw = (r.stdout or b"").decode("utf-8", "replace")
        try:
            data = json.loads(raw[raw.find("{"):])
        except ValueError:
            err = (r.stderr or b"").decode("utf-8", "replace")[-500:]
            return {"ok": False, "error": f"Claude javobini o'qib bo'lmadi: {err or raw[-300:]}",
                    **changes(path)}
        return {
            "ok": not data.get("is_error"),
            "summary": (data.get("result") or "").strip(),
            "turns": data.get("num_turns"),
            "cost": data.get("total_cost_usd"),
            "denied": len(data.get("permission_denials") or []),
            "sec": round(time.time() - t),
            **changes(path),
        }
    finally:
        _busy.release()


def changes(path):
    """O'zgargan fayllar (yangi fayllar ham) va +/- statistikasi."""
    _c, status = _git(path, "status", "--porcelain")
    files = [l[3:] for l in status.splitlines() if l.strip()]
    _c, stat = _git(path, "diff", "--shortstat")
    return {"files": files, "stat": stat}


def diff_text(path, limit=3500):
    _c, d = _git(path, "diff")
    _c, status = _git(path, "status", "--porcelain")
    new = [l[3:] for l in status.splitlines() if l.startswith("??")]
    if new:
        d += "\n\n# Yangi fayllar:\n" + "\n".join(new)
    return d if len(d) <= limit else d[:limit] + f"\n… (yana {len(d) - limit} belgi)"


def commit(path, task):
    _git(path, "add", "-A")
    msg = f"{task.strip().splitlines()[0][:70]}\n\nFRIDAY orqali Claude Code bajardi (Telegram)."
    code, out = _git(path, "commit", "-m", msg)
    if code != 0:
        return f"❌ Commit bo'lmadi: {out[-300:]}"
    _c, h = _git(path, "rev-parse", "--short", "HEAD")
    return f"✅ Commit qilindi: `{h}` (push qilinmadi)"


def revert(path):
    """O'chirmaydi — stash'ga saqlaydi."""
    code, out = _git(path, "stash", "push", "-u", "-m", f"friday-claude {time.strftime('%Y-%m-%d %H:%M')}")
    if code != 0:
        return f"❌ Bekor qilib bo'lmadi: {out[-300:]}"
    return "↩️ O'zgarishlar bekor qilindi va `git stash` ga saqlandi (qaytarish: `git stash pop`)."


def new_result(repo, path, task):
    tid = next(_seq)
    RESULTS[tid] = {"repo": repo, "path": path, "task": task}
    return tid


def result_text(repo, task, res):
    if not res.get("ok") and res.get("error"):
        head = f"❌ **Claude** ({repo}): {res['error']}"
    else:
        head = f"🤖 **Claude tugatdi** — {repo} · {res.get('sec', '?')}s, {res.get('turns', '?')} qadam"
    lines = [head]
    if res.get("summary"):
        lines.append("\n" + res["summary"][:1500])
    files = res.get("files") or []
    if files:
        lines.append(f"\n📝 **O'zgargan fayllar** ({len(files)}): " + ", ".join(f"`{f}`" for f in files[:10]))
        if res.get("stat"):
            lines.append(res["stat"])
    else:
        lines.append("\nFayllar o'zgarmadi.")
    if res.get("denied"):
        lines.append(f"⛔ {res['denied']} ta ruxsatsiz amal rad etildi (terminal/internet yopiq).")
    if res.get("cost") is not None:
        lines.append(f"💳 Obuna limitidan ~${res['cost']:.2f} ga teng sarflandi")
    return "\n".join(lines)
