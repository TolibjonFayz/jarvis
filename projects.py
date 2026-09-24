"""Loyihalar yordamchisi: READ_ROOT ichidagi git repolar holati va o'zgarishlari.

FAQAT o'qish: git status/log/rev-list/stash list. fetch/pull/push YO'Q —
tarmoqqa chiqmaydi va hech narsani o'zgartirmaydi. Repo nomi foydalanuvchidan
kelsa ham faqat topilgan repolar ro'yxatidan tanlanadi (buyruqqa qo'shilmaydi).
"""
import datetime
import os
import re
import subprocess
import time

from config import READ_ROOT

_SKIP_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".dart_tool", "build", "dist",
    ".next", ".nuxt", ".output", "vendor", ".idea", ".vscode", "Library",
}
_MAX_DEPTH = 5
_CACHE_SEC = 600
_cache = {"at": 0, "repos": []}

PERIODS = ["bugun", "kecha", "hafta", "oy"]
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # fonda konsol oynasi chiqmasin


def _git(repo, *args, timeout=15):
    try:
        r = subprocess.run(
            ["git", "-c", "i18n.logOutputEncoding=utf-8", "-C", repo, *args],
            capture_output=True, timeout=timeout, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="replace").strip()


def repos():
    """[{name, path}] — kesh 10 daqiqa."""
    if time.time() - _cache["at"] < _CACHE_SEC and _cache["repos"]:
        return _cache["repos"]
    found = []
    root_depth = READ_ROOT.rstrip("\\/").count(os.sep)
    for dirpath, dirnames, _files in os.walk(READ_ROOT):
        if ".git" in dirnames:
            found.append({"name": os.path.basename(dirpath), "path": dirpath})
            dirnames[:] = []  # repo ichiga kirmaymiz
            continue
        if dirpath.count(os.sep) - root_depth >= _MAX_DEPTH:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
    _cache.update(at=time.time(), repos=found)
    return found


def _norm(s):
    return re.sub(r"[\s_\-.']+", " ", s.lower()).strip()


_GENERIC = {
    "front", "frontend", "backend", "nuxt", "website", "bot", "zakaz", "new", "old",
    "informations", "site", "app", "lms", "admin", "passports", "rishotka", "invitaion",
    "invitation", "jobs",
}
_CHANGE_RE = re.compile(r"o.?zgar|holat|status|nima qil|push|ishla", re.IGNORECASE)


def mentioned(text):
    """Xabarda loyiha nomi + o'zgarish/holat so'zi bormi ("ERPda nima o'zgardi")."""
    if not _CHANGE_RE.search(text or ""):
        return False
    words = set(re.findall(r"[a-z0-9]+", (text or "").lower()))
    tokens = set(ALIASES) - {"bot"}
    for r in repos():
        tokens |= {t for t in re.split(r"[^a-z0-9]+", r["name"].lower()) if len(t) >= 3}
    tokens -= _GENERIC
    return any(w.startswith(t) for w in words for t in tokens)


# Papka nomi boshqacha bo'lgan loyihalar: aytiladigan nom -> papka nomi.
ALIASES = {"friday": "jarvis", "bot": "jarvis"}


def match(query):
    """Nomga mos repolar. Aniq mos kelsa — faqat o'sha."""
    q = _norm(query or "")
    q = ALIASES.get(q, q)
    if not q:
        return []
    all_repos = repos()
    exact = [r for r in all_repos if _norm(r["name"]) == q]
    if exact:
        return exact
    words = q.split()
    return [r for r in all_repos if all(w in _norm(r["name"]) for w in words)]


def _ago(ts):
    sec = int(time.time() - ts)
    if sec < 3600:
        return f"{max(sec // 60, 1)} daqiqa oldin"
    if sec < 86400:
        return f"{sec // 3600} soat oldin"
    days = sec // 86400
    return "kecha" if days == 1 else f"{days} kun oldin"


def _summary(repo):
    last = _git(repo["path"], "log", "-1", "--format=%ct|%s")
    if last is None:
        return None
    ts, _, subj = last.partition("|") if last else ("0", "", "")
    status = _git(repo["path"], "status", "--porcelain") or ""
    return {
        **repo,
        "ts": int(ts or 0),
        "subject": subj,
        "branch": _git(repo["path"], "rev-parse", "--abbrev-ref", "HEAD") or "?",
        "dirty": len([l for l in status.splitlines() if l.strip()]),
    }


def list_text(limit=15):
    items = [s for s in (_summary(r) for r in repos()) if s]
    if not items:
        return f"{READ_ROOT} ichida git loyiha topilmadi."
    items.sort(key=lambda s: -s["ts"])
    out = [f"💻 **Loyihalar** ({len(items)}) — oxirgi faollik bo'yicha"]
    for s in items[:limit]:
        dirty = f" · ✏️ {s['dirty']}" if s["dirty"] else ""
        when = _ago(s["ts"]) if s["ts"] else "commit yo'q"
        out.append(f"• **{s['name']}** — {when} · `{s['branch']}`{dirty}")
    if len(items) > limit:
        out.append(f"…va yana {len(items) - limit} ta eskiroq loyiha")
    out.append("\n✏️ = commit qilinmagan o'zgarishlar")
    return "\n".join(out)


def _ambiguous(query, found):
    if not found:
        names = ", ".join(r["name"] for r in repos()[:40])
        return f"'{query}' nomli loyiha topilmadi. Bor loyihalar: {names}"
    return (
        f"'{query}' ga {len(found)} ta loyiha mos keldi, aniqroq ayt: "
        + ", ".join(r["name"] for r in found)
    )


def status_text(query):
    found = match(query)
    if not found or len(found) > 3:
        return _ambiguous(query, found)
    blocks = []
    for r in found:
        s = _summary(r)
        if not s:
            blocks.append(f"**{r['name']}** — git o'qib bo'lmadi")
            continue
        lines = [f"📁 **{s['name']}** · `{s['branch']}`"]
        ab = _git(r["path"], "rev-list", "--left-right", "--count", "@{u}...HEAD")
        if ab:
            behind, ahead = (int(x) for x in ab.split())
            sync = []
            if ahead:
                sync.append(f"⬆️ {ahead} ta push qilinmagan commit")
            if behind:
                sync.append(f"⬇️ {behind} ta tortilmagan (oxirgi fetch bo'yicha)")
            lines.append(" · ".join(sync) if sync else "✅ remote bilan bir xil (oxirgi fetch bo'yicha)")
        else:
            lines.append("remote kuzatilmaydi")
        status = [l for l in (_git(r["path"], "status", "--porcelain") or "").splitlines() if l.strip()]
        if status:
            lines.append(f"\n✏️ **Commit qilinmagan: {len(status)} ta fayl**")
            lines += [f"`{l.strip()}`" for l in status[:10]]
            if len(status) > 10:
                lines.append(f"…va yana {len(status) - 10} ta")
        else:
            lines.append("Ishchi papka toza")
        stash = _git(r["path"], "stash", "list")
        if stash:
            lines.append(f"📦 Stash: {len(stash.splitlines())} ta")
        log = _git(r["path"], "log", "-5", "--format=%ct|%h|%s")
        if log:
            lines.append("\n**Oxirgi commitlar**")
            for row in log.splitlines():
                ts, h, subj = row.split("|", 2)
                lines.append(f"• `{h}` {subj[:80]} — {_ago(int(ts))}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _period_bounds(period):
    today = datetime.date.today()
    if period == "kecha":
        start = today - datetime.timedelta(days=1)
        return start, today
    if period == "hafta":
        return today - datetime.timedelta(days=today.weekday()), None
    if period == "otgan_hafta":
        monday = today - datetime.timedelta(days=today.weekday())
        return monday - datetime.timedelta(days=7), monday
    if period == "oy":
        return today.replace(day=1), None
    return today, None


_SHORTSTAT_RE = re.compile(r"(\d+) insertion|(\d+) deletion")


def _commits(repo, period):
    since, until = _period_bounds(period)
    args = ["log", f"--since={since} 00:00", "--shortstat", "--format=@@%ct|%h|%s"]
    if until:
        args.insert(2, f"--until={until} 00:00")
    raw = _git(repo["path"], *args)
    if not raw:
        return []
    commits = []
    for line in raw.splitlines():
        if line.startswith("@@"):
            ts, h, subj = line[2:].split("|", 2)
            commits.append({"ts": int(ts), "hash": h, "subject": subj, "add": 0, "del": 0})
        elif commits and "changed" in line:
            for a, d in _SHORTSTAT_RE.findall(line):
                commits[-1]["add"] += int(a or 0)
                commits[-1]["del"] += int(d or 0)
    return commits


def changes_text(query=None, period="bugun"):
    """Davrdagi commitlar: bitta loyiha (query) yoki hammasi."""
    period = period if period in PERIODS else "bugun"
    label = {"bugun": "Bugun", "kecha": "Kecha", "hafta": "Shu hafta", "oy": "Shu oy"}[period]
    if query:
        targets = match(query)
        if not targets or len(targets) > 4:
            return _ambiguous(query, targets)
    else:
        targets = repos()

    blocks, total = [], 0
    for r in targets:
        commits = _commits(r, period)
        if not commits:
            continue
        total += len(commits)
        add, rem = sum(c["add"] for c in commits), sum(c["del"] for c in commits)
        lines = [f"📁 **{r['name']}** — {len(commits)} ta commit · +{add} / −{rem} qator"]
        for c in commits[:8]:
            lines.append(f"• {c['subject'][:90]}")
        if len(commits) > 8:
            lines.append(f"…va yana {len(commits) - 8} ta")
        blocks.append("\n".join(lines))

    scope = f" ({', '.join(r['name'] for r in targets)})" if query else ""
    if not blocks:
        return f"💻 {label}{scope}: commit yo'q."
    head = f"💻 **{label}** — {total} ta commit, {len(blocks)} ta loyihada{scope}"
    tail = []
    if query:
        for r in targets:
            s = _summary(r)
            if s and s["dirty"]:
                tail.append(f"✏️ {r['name']}: {s['dirty']} ta fayl hali commit qilinmagan")
    return "\n\n".join([head] + blocks + (["\n".join(tail)] if tail else []))


def brief_line():
    """Brifing: kechagi faollik (bo'lmasa bo'sh)."""
    active, total = 0, 0
    for r in repos():
        n = len(_commits(r, "kecha"))
        if n:
            active += 1
            total += n
    return f"💻 Kecha: {active} ta loyihada {total} ta commit" if total else ""
