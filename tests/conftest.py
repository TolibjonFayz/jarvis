"""Offline testlar: Groq/Telegram/Google chaqirilmaydi, token sarflanmaydi.

Har test o'z vaqtinchalik bazasida ishlaydi (haqiqiy data/jarvis.db ga tegmaydi).
LLM o'rniga `llm` fixture — oldindan yozilgan javoblarni navbat bilan qaytaradi.
Ishga tushirish:  python -m pytest -q
"""
import json
import os
import sys
import tempfile
from types import SimpleNamespace as NS

# Loyiha modullari import qilinishidan OLDIN: config DATA_DIR ni shu yerdan oladi.
_TMP = tempfile.mkdtemp(prefix="friday-tests-")
os.environ["DATA_DIR"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import agent  # noqa: E402
import brain  # noqa: E402
import memory  # noqa: E402
import projects  # noqa: E402

CHAT = 777


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Har testga toza baza; fon xotirasi (Groq chaqiradi) o'chiq."""
    monkeypatch.setattr(memory, "DB_PATH", str(tmp_path / "test.db"))
    memory.init_db()
    monkeypatch.setattr(brain, "after_turn", lambda *a, **k: None)
    monkeypatch.setattr(projects, "repos", lambda: [
        {"name": "erp_climavent_frontend", "path": "x"},
        {"name": "erp_climavent_backend", "path": "x"},
        {"name": "climavent-backend", "path": "x"},
        {"name": "bilim-manba-backend", "path": "x"},
        {"name": "jarvis", "path": "x"},
    ])
    yield


def reply(content="", calls=()):
    """Soxta LLM javobi. calls: [(tool_nomi, {args})]."""
    tcs = [
        NS(id=f"call{i}", function=NS(name=name, arguments=json.dumps(args)))
        for i, (name, args) in enumerate(calls)
    ]
    msg = NS(content=content, tool_calls=tcs or None)
    return NS(choices=[NS(message=msg)], usage=NS(total_tokens=10))


class ToolUseFailed(Exception):
    """Groq 400 tool_use_failed ga o'xshash xato (failed_generation bilan)."""

    def __init__(self, name, args):
        self.body = {"error": {
            "code": "tool_use_failed",
            "failed_generation": json.dumps({"name": name, "arguments": args}),
        }}
        super().__init__(f"Error code: 400 - tool_use_failed {self.body}")


class Script:
    """Navbatdagi javobni qaytaradi (Exception bo'lsa — ko'taradi). So'rovlarni yozib boradi."""

    def __init__(self, *items):
        self.items = list(items)
        self.requests = []

    def __call__(self, **kwargs):
        self.requests.append(kwargs)
        if not self.items:
            raise AssertionError("LLM kutilganidan ko'p chaqirildi")
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def llm(monkeypatch):
    """llm(*javoblar) -> Script; agent._create shu skript bilan almashtiriladi."""
    def install(*items):
        script = Script(*items)
        monkeypatch.setattr(agent, "_create", script)
        return script
    return install
