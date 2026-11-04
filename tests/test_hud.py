"""HUD lokal server: token, Host himoyasi, holat, chat, amallar ro'yxati."""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

import hud


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setattr(hud, "TOKEN_PATH", str(tmp_path / "tok"))
    monkeypatch.setattr(hud, "_music", lambda: None)
    hud._cache.clear()
    hud._cache.update(weather={"temp": 12}, todos=["KP yuborish"])
    hud._hooks["respond"] = lambda text: f"javob: {text}"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), hud.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def req(port, method, path, body=None, token=True, host="127.0.0.1"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": host, "Content-Type": "application/json"}
    if token:
        headers["X-HUD-Token"] = hud.token()
    c.request(method, path, json.dumps(body) if body is not None else None, headers)
    r = c.getresponse()
    data = r.read()
    try:
        return r.status, json.loads(data)
    except ValueError:
        return r.status, data


def test_api_needs_token(server):
    assert req(server, "GET", "/api/state", token=False)[0] == 401
    assert req(server, "POST", "/api/chat", {"text": "salom"}, token=False)[0] == 401


def test_foreign_host_rejected(server):
    # DNS rebinding: boshqa domen nomi bilan kelgan so'rov (token bo'lsa ham)
    assert req(server, "GET", "/api/state", host="evil.example")[0] == 403


def test_state_has_system_and_cache(server):
    code, s = req(server, "GET", "/api/state")
    assert code == 200
    assert 0 <= s["system"]["cpu"] <= 100 and s["weather"]["temp"] == 12
    assert s["todos"] == ["KP yuborish"] and "voice" in s


def test_chat_and_events(server):
    since = hud._event_id[0]
    code, r = req(server, "POST", "/api/chat", {"text": "ertaga nima bor"})
    assert code == 200 and r["reply"] == "javob: ertaga nima bor"
    _, evs = req(server, "GET", f"/api/events?since={since}")
    assert [(e["who"], e["text"]) for e in evs] == [("you", "ertaga nima bor"), ("friday", "javob: ertaga nima bor")]


def test_unknown_action_and_no_power(server):
    assert req(server, "POST", "/api/action", {"name": "power", "arg": "shutdown"})[0] == 400
    assert req(server, "POST", "/api/action", {"name": "media", "arg": "rm -rf"})[0] == 400
    assert "power" not in hud.ACTIONS


def test_static_index_and_no_traversal(server):
    code, body = req(server, "GET", "/", token=False)
    assert code == 200 and b"<title>FRIDAY</title>" in body
    assert req(server, "GET", "/../config.py", token=False)[0] == 404


import datetime  # noqa: E402


def test_greeting_from_cache(monkeypatch):
    hud._cache.clear()
    hud._cache.update(
        weather={"temp": 18},
        agenda=[{"kind": "event", "day": "2026-11-04", "time": "21:00–22:00", "title": "Meeting"}],
        unanswered=[{"name": "Sardor aka", "minutes": 3000, "unread": 1}],
        radar={"configured": True, "on": True, "problems": []},
    )
    text = hud.greeting(datetime.datetime(2026, 11, 4, 10, 30))
    assert text.startswith("Xayrli tong, bro. Soat 10:30.")
    assert "18 daraja" in text and "21:00 da: Meeting" in text
    assert "Sardor aka javob kutyapti" in text and "ERP joyida" in text


def test_greet_once_per_20_min(monkeypatch, server):
    said = []
    monkeypatch.setattr(hud, "speak_async", said.append)
    hud._greeted[0] = 0
    assert req(server, "POST", "/api/greet", {})[1]["text"]
    assert req(server, "POST", "/api/greet", {})[1]["text"] is None   # takrorlamaydi
    assert len(said) == 1


def test_chat_speaks_only_when_asked(monkeypatch, server):
    said = []
    monkeypatch.setattr(hud, "speak_async", said.append)
    req(server, "POST", "/api/chat", {"text": "salom"})
    req(server, "POST", "/api/chat", {"text": "salom", "speak": True})
    assert said == ["javob: salom"]


def test_alerts_spoken_only_while_hud_open(monkeypatch):
    said = []
    monkeypatch.setattr(hud, "speak_async", said.append)
    hud._last_poll[0] = 0
    hud.push("radar", "prod API javob bermayapti")
    hud._last_poll[0] = __import__("time").time()
    hud.push("radar", "prod API javob bermayapti")
    hud.push("chat", "oddiy javob")                       # chat ovozsiz
    assert said == ["Diqqat. prod API javob bermayapti"]
