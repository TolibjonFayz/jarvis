"""Kompyuter boshqaruvi — haqiqiy shutdown/uyqu/qulf CHAQIRILMAYDI (soxtalari bilan)."""
import os
from types import SimpleNamespace as NS

import pytest

import agent
import pc
import tools
from conftest import CHAT


@pytest.fixture
def calls(monkeypatch):
    rec = []
    monkeypatch.setattr(pc.subprocess, "run", lambda args, **kw: rec.append(args) or NS(returncode=0))
    monkeypatch.setattr(pc.threading, "Timer", lambda sec, fn: NS(start=lambda: rec.append(("timer", sec))))
    monkeypatch.setattr(pc.os, "startfile", lambda url: rec.append(("open", url)), raising=False)
    return rec


def test_shutdown_has_delay_and_can_be_cancelled(calls):
    out = pc.power("shutdown")
    assert calls[0][:4] == ["shutdown", "/s", "/t", str(pc.POWER_DELAY)]
    assert "Bekor" in out
    assert "Bekor qilindi" in pc.cancel_power()
    assert calls[-1] == ["shutdown", "/a"]


def test_restart_flag(calls):
    pc.power("restart")
    assert calls[0][1] == "/r"


def test_sleep_is_delayed_so_reply_gets_out(calls):
    pc.power("sleep")
    assert calls == [("timer", 5)]


def test_unknown_power_action(calls):
    with pytest.raises(ValueError):
        pc.power("format_c")
    assert calls == []


@pytest.mark.parametrize("url", ["file:///C:/Windows/system32/cmd.exe", "javascript:alert(1)",
                                 "C:\\Windows\\notepad.exe", "ftp://x.uz", "https://"])
def test_open_url_rejects_non_web(calls, url):
    with pytest.raises(ValueError):
        pc.open_url(url)
    assert calls == []


def test_open_url_ok(calls):
    assert "ochildi" in pc.open_url("https://kun.uz")
    assert calls == [("open", "https://kun.uz")]


# --- Tool'lar ---

def test_pc_power_tool_only_prepares_confirmation(calls):
    tools.PENDING_SENDS.clear()
    out = tools.execute_tool("pc_power", {"action": "shutdown"}, CHAT)
    assert "tasdiqlang" in out
    assert calls == []  # hech narsa bajarilmadi
    (p,) = tools.PENDING_SENDS.values()
    assert p["kind"] == "pc_power" and p["to_id"] == "shutdown"
    assert "pc_power".startswith(agent._MUTATING)
    tools.PENDING_SENDS.clear()


def test_pc_screenshot_tool_queues_file(monkeypatch, tmp_path):
    f = tmp_path / "s.jpg"
    f.write_bytes(b"jpg")
    monkeypatch.setattr(pc, "screenshot", lambda: (str(f), False))
    tools.PENDING_FILES.clear()
    tools.execute_tool("pc_screenshot", {}, CHAT)
    assert tools.PENDING_FILES == [{"chat_id": CHAT, "path": str(f), "caption": "🖥 Kompyuter ekrani"}]
    tools.PENDING_FILES.clear()


def test_black_screen_not_sent(monkeypatch, tmp_path):
    f = tmp_path / "s.jpg"
    f.write_bytes(b"jpg")
    monkeypatch.setattr(pc, "screenshot", lambda: (str(f), True))
    tools.PENDING_FILES.clear()
    out = tools.execute_tool("pc_screenshot", {}, CHAT)
    assert "qulflangan" in out and tools.PENDING_FILES == [] and not os.path.exists(f)


@pytest.mark.parametrize("text,cats", [
    ("kompyuter ekranini ko'rsat", ["pc"]),
    ("kompyuterni o'chir", ["pc"]),
    ("noutbukni qulfla", ["pc"]),
    ("bugun kompyuterda nima qildim?", ["loyiha"]),  # loyiha marshruti oldin turadi
])
def test_pc_routes(text, cats):
    assert agent.forced_categories(text) == cats


def test_pc_word_commands():
    import bot
    assert bot.WORD_COMMANDS["pc"] is bot.cmd_pc and bot.WORD_COMMANDS["ekran"] is bot.cmd_screen


# --- Musiqa va media (2026-10-05: "qo'shiq qo'y" -> "qila olmayman" degan edi) ---

def test_play_music_opens_first_video(monkeypatch, calls):
    monkeypatch.setattr(pc, "find_youtube", lambda q: (f"https://www.youtube.com/watch?v=X_{q}", True))
    assert "qo'yildi: Ummon" in pc.play_music("Ummon")
    assert calls == [("open", "https://www.youtube.com/watch?v=X_Ummon")]


def test_play_music_default_query(monkeypatch, calls):
    seen = []
    monkeypatch.setattr(pc, "find_youtube", lambda q: seen.append(q) or ("https://y", True))
    pc.play_music("")
    assert seen == [pc.DEFAULT_MUSIC]


def test_media_keys(monkeypatch):
    pressed = []
    monkeypatch.setattr(pc.ctypes, "windll", NS(user32=NS(keybd_event=lambda vk, s, f, e: pressed.append((vk, f)))))
    assert "Pauza" in pc.media("play_pause")
    assert pressed == [(0xB3, 0), (0xB3, 2)]
    pressed.clear()
    pc.media("volume_up")
    assert len(pressed) == 10  # 5 bosish (~10%)
    with pytest.raises(ValueError):
        pc.media("format")


@pytest.mark.parametrize("text", ["Qo'shiq qo'y", "musiqani to'xtat", "youtube'da Ummon qo'y", "ovozni balandlat"])
def test_music_routes(text):
    assert agent.forced_categories(text) == ["pc"]


def test_required_tool_but_model_asks_question(llm):
    # Model savol bermoqchi edi -> Groq "required" ni rad etdi -> tool'siz qayta so'ralib,
    # "kompyuteringizni boshqara olmayman" deyardi. Endi modelning o'z savoli qaytadi.
    class AskInstead(Exception):
        body = {"error": {"code": "tool_use_failed", "failed_generation": "Qaysi qo'shiqni qo'yay?"}}

        def __str__(self):
            return "Error code: 400 - tool_use_failed"

    llm(AskInstead())
    out = agent._tool_loop(CHAT, [], "qo'shiq qo'y", ["pc"], require=True)
    assert out == "Qaysi qo'shiqni qo'yay?"


@pytest.mark.parametrize("text,quick", [
    ("Qo'shiq qo'y", True), ("musiqa och", True), ("bir qo'shiq qo'yib ber", True),
    ("qo'shiq qo'y bro", True), ("Ummon qo'shig'ini qo'y", False), ("qo'shiq yoz", False),
])
def test_quick_music(text, quick):
    assert bool(agent._QUICK_MUSIC_RE.fullmatch(text)) == quick


def test_quick_music_skips_model(monkeypatch, llm):
    script = llm()  # model chaqirilsa — AssertionError
    monkeypatch.setattr(pc, "play_music", lambda q="": "🎵 qo'yildi")
    assert agent.respond(CHAT, "Qo'shiq qo'y") == "🎵 qo'yildi"
    assert script.requests == []


def test_song_name_form_routes_to_pc():
    assert agent.forced_categories("Ummon guruhining Yolg'izim qo'shig'ini qo'y") == ["pc"]
