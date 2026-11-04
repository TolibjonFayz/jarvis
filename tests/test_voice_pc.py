"""Kompyuter ovozi: gap boshlanishi/tugashini aniqlash (mikrofonsiz, sintetik signal)."""
import numpy as np

import voice_pc
from voice_pc import CHUNK, SR, Utterance


def quiet(sec, level=50):
    n = int(sec * SR / CHUNK)
    return [np.full(CHUNK, level, np.int16) for _ in range(n)]


def loud(sec, level=3000):
    t = np.arange(CHUNK) / SR
    wave = (np.sin(2 * np.pi * 220 * t) * level).astype(np.int16)
    return [wave.copy() for _ in range(int(sec * SR / CHUNK))]


def run(chunks, noise=50):
    u = Utterance(noise)
    for c in chunks:
        state = u.feed(c)
        if state != "more":
            return state, u
    return "more", u


def test_speech_then_silence_ends():
    state, u = run(quiet(0.3) + loud(1.5) + quiet(1.5))
    assert state == "done"
    assert 1.5 < u.t < 3.4          # jimlikdan ~1 s keyin to'xtaydi, oxirigacha kutmaydi


def test_nothing_said_is_empty():
    state, _ = run(quiet(6))
    assert state == "empty"


def test_short_pause_inside_sentence_does_not_cut():
    state, u = run(loud(1) + quiet(0.5) + loud(1) + quiet(1.2))
    assert state == "done" and u.t > 3.0


def test_max_length_cap():
    state, u = run(loud(20))
    assert state == "done" and u.t <= voice_pc.MAX_UTTER + 0.1


def test_noisy_room_raises_threshold():
    # Shovqin 400 bo'lsa 600 lik "gap" signal emas — shovqin ostida qoladi
    state, _ = run(loud(6, level=600), noise=400)
    assert state == "empty"


def test_status_text_mentions_hotkey(monkeypatch):
    assert "Ctrl+Alt+J" in voice_pc.status_text(777)


import pytest  # noqa: E402

import agent  # noqa: E402
import pc  # noqa: E402

APPS = [("Telegram", "Telegram.TelegramDesktop"), ("Google Chrome", "Chrome"),
        ("Visual Studio Code", "Microsoft.VisualStudioCode"), ("Calculator", "calc!App"),
        ("Excel", "excel"), ("Reset Settings to Default", "x"), ("Settings", "settings!App")]


@pytest.mark.parametrize("raw,expected", [
    ("Hei Jarvis", ("", "wake_only")),                      # 2026-11-03 agentga ketgan edi
    ("Hey Jarvis, soat nechi bo'ldi?", ("soat nechi bo'ldi?", "ok")),
    ("Jarvis.", ("", "wake_only")),
    ("Thank you.", ("", "noise")),                          # Whisper gallyutsinatsiyasi
    ("Продолжение следует...", ("", "noise")),
    ("  ", ("", "noise")),
    ("Open Telegram", ("Open Telegram", "ok")),
    ("Rahmat, zo'r bo'ldi", ("Rahmat, zo'r bo'ldi", "ok")),
])
def test_clean_text(raw, expected):
    assert voice_pc.clean_text(raw) == expected


@pytest.mark.parametrize("name,app", [
    ("telegram", "Telegram"), ("chrome", "Google Chrome"), ("xrom", "Google Chrome"),
    ("vs code", "Visual Studio Code"), ("kalkulyator", "Calculator"), ("sozlamalar", "Settings"),
    ("Telegramdan Aziz chatini", None), ("ab", None), ("photoshop", None),
])
def test_find_app(name, app):
    found = pc.find_app(name, APPS)
    assert (found[0] if found else None) == app


@pytest.mark.parametrize("text,ok", [
    ("Open Telegram", True), ("telegramni och", True), ("Chrome'ni ochib ber", True),
    ("Telegramdan Aziz chatini och", False), ("eshikni och", False), ("salom bro", False),
])
def test_quick_open_app(monkeypatch, text, ok):
    monkeypatch.setattr(pc, "start_apps", lambda: APPS)
    assert bool(agent.quick_open_app(text)) == ok


def test_follow_up_window_is_shorter():
    u = Utterance(50, start_timeout=voice_pc.FOLLOW_TIMEOUT)
    states = [u.feed(c) for c in quiet(4.2)]
    assert states[-1] == "empty"
