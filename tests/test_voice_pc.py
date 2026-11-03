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
