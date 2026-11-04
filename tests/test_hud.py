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
    assert code == 200 and b"FRIDAY HUD" in body
    assert req(server, "GET", "/../config.py", token=False)[0] == 404
