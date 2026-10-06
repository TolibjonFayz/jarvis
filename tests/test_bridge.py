"""Telefon <-> kompyuter ko'prigi — vaqtinchalik papkalar, clipboard soxta."""
import asyncio
import os
import time
from types import SimpleNamespace as NS

import pytest

import agent
import bridge
import tools
from conftest import CHAT

FINAL = tools.FINAL


def _touch(path, data=b"x", age=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    t = time.time() - age
    os.utime(path, (t, t))
    return str(path)


@pytest.fixture
def pc(tmp_path, monkeypatch):
    home = tmp_path / "home"
    folders = {k: str(home / k.capitalize()) for k in ("downloads", "desktop", "documents", "screenshots")}
    for p in folders.values():
        os.makedirs(p)
    root = tmp_path / "projects"
    monkeypatch.setattr(bridge, "FOLDERS", folders)
    monkeypatch.setattr(bridge, "READ_ROOT", str(root))
    monkeypatch.setattr(bridge, "SAVE_DIR", str(home / "Downloads" / "FRIDAY"))
    # pytest vaqtinchalik papkasi AppData ichida — u yerda hamma narsa maxfiy hisoblanadi
    monkeypatch.setattr(bridge, "_SECRET_DIRS", bridge._SECRET_DIRS - {"appdata"})
    tools.PENDING_FILES.clear()
    yield NS(f=folders, root=root, home=home)
    tools.PENDING_FILES.clear()


def test_send_latest_download(pc):
    _touch(os.path.join(pc.f["downloads"], "old.zip"), age=100)
    new = _touch(os.path.join(pc.f["downloads"], "invoice.pdf"))
    _touch(os.path.join(pc.f["downloads"], "big.crdownload"))          # yuklanayotgan — emas
    out = tools.execute_tool("pc_send_file", {"folder": "downloads", "latest": True}, CHAT)
    assert out.startswith(FINAL) and "invoice.pdf" in out
    (item,) = tools.PENDING_FILES
    assert item["path"] == new and item["kind"] == "document" and item["temp"] is False


def test_send_by_name_single_and_ambiguous(pc):
    cv = _touch(os.path.join(pc.f["documents"], "Tolibjon_CV_2026.pdf"))
    assert "Tolibjon_CV_2026.pdf" in tools.execute_tool("pc_send_file", {"query": "cv pdf"}, CHAT)
    assert tools.PENDING_FILES[0]["path"] == cv
    tools.PENDING_FILES.clear()
    _touch(str(pc.root / "erp" / "README.md"))
    _touch(str(pc.root / "jarvis" / "README.md"), age=50)
    out = tools.execute_tool("pc_send_file", {"query": "readme"}, CHAT)
    assert "qaysi biri" in out and out.count("README.md") >= 2 and tools.PENDING_FILES == []
    # To'liq yo'l bilan — aniq o'sha fayl
    path = str(pc.root / "jarvis" / "README.md")
    tools.execute_tool("pc_send_file", {"query": path}, CHAT)
    assert tools.PENDING_FILES[0]["path"] == path


def test_secrets_never_sent(pc):
    _touch(str(pc.root / "app" / ".env"))
    _touch(str(pc.root / "app" / "flutter_native_integration.env"))
    _touch(str(pc.root / "app" / "google_token.json"))
    _touch(os.path.join(pc.f["downloads"], "id_rsa"))
    assert "topilmadi" in tools.execute_tool("pc_send_file", {"query": "env"}, CHAT)
    assert "topilmadi" in tools.execute_tool("pc_send_file", {"query": "google_token"}, CHAT)
    full = str(pc.root / "app" / ".env")
    assert "topilmadi" in tools.execute_tool("pc_send_file", {"query": full}, CHAT)
    # Eng oxirgi fayl maxfiy bo'lsa — u o'tkazib yuboriladi
    assert bridge.latest_file("downloads") is None
    assert tools.PENDING_FILES == []


def test_outside_allowed_roots_refused(pc, tmp_path):
    outside = _touch(str(tmp_path / "elsewhere" / "x.txt"))
    assert bridge.find_files(outside) == [] and not bridge.allowed(outside)


def test_friday_data_dir_is_secret():
    assert bridge.is_secret(os.path.join(bridge.BASE_DIR, "data", "jarvis.db"))
    assert bridge.is_secret(r"C:\Users\u\AppData\Roaming\Telegram Desktop\tdata\key_datas")
    assert not bridge.is_secret(r"D:\work\report.pdf")


def test_save_path_never_overwrites(pc):
    p1 = bridge.save_path("rasm.jpg")
    _touch(p1)
    p2 = bridge.save_path("rasm.jpg")
    assert p2.endswith("rasm (2).jpg") and os.path.dirname(p2) == bridge.SAVE_DIR
    assert os.path.basename(bridge.save_path('a/b\\c?:.txt')) == "c__.txt"


def test_clipboard_text_short_long_image_files(pc, monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "clipboard_get", lambda: ("text", "npm run dev ```x```"))
    out = tools.execute_tool("pc_clipboard_get", {}, CHAT)
    assert "```\nnpm run dev ʼʼʼxʼʼʼ\n```" in out
    monkeypatch.setattr(bridge, "clipboard_get", lambda: ("text", "a" * 5000))
    assert "fayl qilib" in tools.execute_tool("pc_clipboard_get", {}, CHAT)
    assert tools.PENDING_FILES[-1]["temp"] is True
    img = _touch(str(tmp_path / "clip.png"))
    monkeypatch.setattr(bridge, "clipboard_get", lambda: ("image", img))
    tools.execute_tool("pc_clipboard_get", {}, CHAT)
    assert tools.PENDING_FILES[-1]["kind"] == "photo"
    files = [_touch(str(tmp_path / "a.pdf")), _touch(str(tmp_path / ".env"))]
    monkeypatch.setattr(bridge, "clipboard_get", lambda: ("files", files))
    out = tools.execute_tool("pc_clipboard_get", {}, CHAT)
    assert "1 tasini" in out and tools.PENDING_FILES[-1]["path"] == files[0]
    monkeypatch.setattr(bridge, "clipboard_get", lambda: (None, None))
    assert "bo'sh" in tools.execute_tool("pc_clipboard_get", {}, CHAT)


def test_clipboard_set(monkeypatch):
    got = []
    monkeypatch.setattr(bridge, "clipboard_set", got.append)
    assert "Ctrl+V" in tools.execute_tool("pc_clipboard_set", {"text": "Salom\nqator"}, CHAT)
    assert got == ["Salom\nqator"]


@pytest.mark.parametrize("text,expected", [
    ("nusxala: https://github.com/TolibjonFayz/jarvis",
     ("pc_clipboard_set", {"text": "https://github.com/TolibjonFayz/jarvis"})),
    ("kompyuterga nusxala: Salom\nIkkinchi Qator", ("pc_clipboard_set", {"text": "Salom\nIkkinchi Qator"})),
    ("copy: npm run dev", ("pc_clipboard_set", {"text": "npm run dev"})),
    ("clipboardni yubor", ("pc_clipboard_get", {})),
    ("kompyuterdagi nusxani yubor", ("pc_clipboard_get", {})),
    ("qo'y: 5 ta olma", None), ("nusxala", None), ("salom", None),
])
def test_quick_bridge(text, expected):
    assert agent.quick_bridge(text) == expected


def test_clipboard_quick_path_skips_model(monkeypatch, llm):
    script = llm()
    got = []
    monkeypatch.setattr(bridge, "clipboard_set", got.append)
    out = agent.respond(CHAT, "nusxala: git push origin main")
    assert "Ctrl+V" in out and got == ["git push origin main"] and script.requests == []


@pytest.mark.parametrize("text", [
    "Downloads dagi oxirgi faylni yubor", "kompyuterdan CV ni yubor",
    "jarvis loyihasidagi README faylini yubor", "oxirgi skrinshotni yubor",
])
def test_file_routes(text):
    assert agent.forced_categories(text) == ["pc"]


# --- bot: telefondan kelgan fayl -> kompyuter ---

