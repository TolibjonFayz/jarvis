"""Claude Code ko'prigi — haqiqiy Claude chaqirilmaydi (subprocess soxta), git haqiqiy (temp repo)."""
import json
import subprocess
from types import SimpleNamespace as NS

import pytest

import agent
import claude_bridge as cb
import projects
import tools
from conftest import CHAT


def _git(path, *a):
    return subprocess.run(["git", "-C", str(path), *a], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "demo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "app.txt").write_text("v1\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "init")
    monkeypatch.setattr(cb, "find_cli", lambda: "claude.exe")
    return r


def _fake_claude(repo_path, edit=True, result="Tugmani ko'k qildim (app.txt).", is_error=False):
    real_run = subprocess.run

    def run(cmd, **kw):
        if cmd and cmd[0] == "claude.exe":
            assert "--tools" in cmd and cmd[cmd.index("--tools") + 1] == cb.TOOLS   # terminal yo'q
            assert cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
            if edit:
                (repo_path / "app.txt").write_text("v2\n", encoding="utf-8")
                (repo_path / "new.txt").write_text("yangi\n", encoding="utf-8")
            out = json.dumps({"type": "result", "result": result, "is_error": is_error,
                              "num_turns": 3, "total_cost_usd": 0.42, "permission_denials": []})
            return NS(returncode=0, stdout=out.encode(), stderr=b"")
        return real_run(cmd, **kw)
    return run


def test_preflight_refuses_dirty_repo(repo):
    assert cb.preflight(str(repo)) is None
    (repo / "app.txt").write_text("egasining ishi\n", encoding="utf-8")
    assert "commit qilinmagan" in cb.preflight(str(repo))


def test_preflight_refuses_non_git(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "find_cli", lambda: "claude.exe")
    assert "git repo emas" in cb.preflight(str(tmp_path))


def test_run_task_reports_changes(repo, monkeypatch):
    monkeypatch.setattr(cb.subprocess, "run", _fake_claude(repo))
    res = cb.run_task(str(repo), "tugmani ko'k qil")
    assert res["ok"] and res["turns"] == 3 and res["cost"] == 0.42
    assert sorted(res["files"]) == ["app.txt", "new.txt"]
    text = cb.result_text("demo", "tugmani ko'k qil", res)
    assert "Claude tugatdi" in text and "`app.txt`" in text and "~$0.42" in text


def test_revert_stashes_not_deletes(repo, monkeypatch):
    monkeypatch.setattr(cb.subprocess, "run", _fake_claude(repo))
    cb.run_task(str(repo), "x")
    out = cb.revert(str(repo))
    assert "stash" in out
    assert (repo / "app.txt").read_text() == "v1\n" and not (repo / "new.txt").exists()
    assert "friday-claude" in _git(repo, "stash", "list")       # qaytarib olsa bo'ladi


def test_commit(repo, monkeypatch):
    monkeypatch.setattr(cb.subprocess, "run", _fake_claude(repo))
    cb.run_task(str(repo), "tugmani ko'k qil")
    assert "Commit qilindi" in cb.commit(str(repo), "tugmani ko'k qil")
    assert "tugmani ko'k qil" in _git(repo, "log", "-1", "--format=%s")
    assert _git(repo, "status", "--porcelain") == ""


def test_diff_includes_new_files(repo, monkeypatch):
    monkeypatch.setattr(cb.subprocess, "run", _fake_claude(repo))
    cb.run_task(str(repo), "x")
    d = cb.diff_text(str(repo))
    assert "-v1" in d and "+v2" in d and "new.txt" in d


def test_one_task_at_a_time(repo):
    cb._busy.acquire()
    try:
        assert "boshqa Claude vazifasi" in cb.preflight(str(repo))
        assert cb.run_task(str(repo), "x")["ok"] is False
    finally:
        cb._busy.release()


def test_code_task_tool_prepares_confirmation(repo, monkeypatch):
    monkeypatch.setattr(projects, "repos", lambda: [{"name": "demo", "path": str(repo)}])
    tools.PENDING_SENDS.clear()
    out = tools.execute_tool("code_task", {"project": "demo", "task": "tugmani ko'k qil"}, CHAT)
    assert "Tasdiqlang" in out
    (p,) = tools.PENDING_SENDS.values()
    assert p["kind"] == "code_task" and p["to_id"] == str(repo)
    tools.PENDING_SENDS.clear()
    (repo / "app.txt").write_text("iflos\n", encoding="utf-8")
    assert "Boshlab bo'lmaydi" in tools.execute_tool("code_task", {"project": "demo", "task": "x qil"}, CHAT)
    assert tools.PENDING_SENDS == {}


@pytest.mark.parametrize("text,cats", [
    ("Claude, fit-uz da login tugmasini ko'k qil", ["kod"]),
    ("[kod] fit-uz login tugmasi", ["kod"]),
    ("claude nima?", None),                           # oddiy savol — kod vazifasi emas
])
def test_code_routes(text, cats):
    assert agent.forced_categories(text) == cats
