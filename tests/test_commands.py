"""Ruxsat berilgan buyruqlar — haqiqiy jarayon ishga tushmaydi (subprocess soxta)."""
import json
import os
from types import SimpleNamespace as NS

import pytest

import agent
import commands
import tools
from conftest import CHAT


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "commands.json"
    monkeypatch.setattr(commands, "CONFIG", str(path))
    monkeypatch.setattr(commands, "PROC_DIR", str(tmp_path / "proc"))
    work = tmp_path / "proj"
    work.mkdir()
    path.write_text(json.dumps({"commands": [
        {"id": "app-build", "name": "App build", "cwd": str(work), "cmd": ["npm", "run", "build"], "type": "run"},
        {"id": "app-dev", "name": "App dev", "cwd": str(work), "cmd": ["npm", "run", "dev"], "type": "serve"},
    ]}), encoding="utf-8")
    return work


def test_default_list_excludes_dangerous_scripts():
    cmds = commands.default_commands()
    text = json.dumps(cmds)
    for bad in ("db:migrate", "foods:import", "repdb:import", "media:upload", "lint", "format", "start:dev"):
        assert bad not in text, bad
    pulls = [c for c in cmds if c["id"].endswith("-pull")]
    assert pulls and all(c["cmd"] == ["git", "pull", "--ff-only"] for c in pulls)


def test_run_success_and_failure(cfg, monkeypatch):
    results = [NS(returncode=0, stdout=b"\x1b[32mbuilt in 3s\x1b[0m\n", stderr=b""),
               NS(returncode=1, stdout=b"", stderr=b"Error: TS2345 bad type\n")]
    seen = []
    monkeypatch.setattr(commands.subprocess, "run", lambda argv, **kw: seen.append((argv, kw["cwd"])) or results.pop(0))
    ok = commands.run("app-build")
    assert ok.startswith("✅") and "built in 3s" in ok and "\x1b" not in ok
    bad = commands.run("app-build")
    assert bad.startswith("❌ (kod 1)") and "TS2345" in bad
    assert seen[0][1] == str(cfg)


def test_unknown_id_is_refused(cfg):
    assert "ro'yxatda yo'q" in commands.run("rm -rf /")
    out = tools.execute_tool("cmd_run", {"id": "rm -rf /"}, CHAT)
    assert "ro'yxatda yo'q" in out


def test_serve_reports_url_and_refuses_double_start(cfg, monkeypatch):
    class FakeProc:
        pid = 4242
        returncode = None

        def __init__(self, argv, stdout, **kw):
            stdout.write(b"  VITE v5  ready\n  \x1b[1mLocal:\x1b[0m   http://localhost:5173/\n")
            stdout.flush()

        def poll(self):
            return None

    monkeypatch.setattr(commands.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(commands.time, "sleep", lambda s: None)
    monkeypatch.setattr(commands, "_alive", lambda pid: pid == 4242)
    out = commands.start("app-dev", wait=3)
    assert "ishga tushdi" in out and "http://localhost:5173/" in out
    assert "allaqachon ishlayapti" in commands.start("app-dev")
    assert "🟢 `app-dev`" in commands.list_text()


def test_stop_when_not_running(cfg):
    assert "ishlamayapti" in commands.stop("app-dev")


def test_tool_schema_uses_enum_of_ids():
    spec = next(t for t in tools.TOOLS if t["name"] == "cmd_run")
    ids = spec["input_schema"]["properties"]["id"]["enum"]
    assert "friday-test" in ids and all(" " not in i for i in ids)


@pytest.mark.parametrize("text,cats", [
    ("ERP frontendni ishga tushir", ["buyruq"]),
    ("fit-uz da git pull qil", ["buyruq"]),           # "git" loyihaga ketmasin
    ("FRIDAY testlarini ishga tushir", ["buyruq"]),
    ("ERP serverni to'xtat", ["buyruq"]),
    ("ERP da shu oy nima o'zgardi?", ["loyiha"]),
])
def test_command_routes(text, cats):
    assert agent.forced_categories(text) == cats
