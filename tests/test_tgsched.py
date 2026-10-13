"""Relay (Cloudflare) — PC o'chiq bo'lsa ham bot nomidan eslatma. Tarmoq soxta."""
import datetime as dt

import pytest

import config
import football
import memory
import tgsched
import tools
from conftest import CHAT

NOW = dt.datetime(2026, 10, 13, 10, 0).timestamp()


class FakeRelay:
    """relay/src/index.js ning soddalashtirilgan nusxasi: navbat + yuborilganlar."""

    def __init__(self):
        self.items, self.sent, self.puts = [], {}, 0

    def __call__(self, method, path, body=None, timeout=15):
        if method == "PUT" and path == "/alerts":
            self.puts += 1
            self.items = [i for i in body["items"] if i["key"] not in self.sent]
            return {"ok": True, "items": len(self.items)}
        if method == "GET" and path == "/sent":
            return {"sent": self.sent}
        raise AssertionError(path)

    def run_due(self, now):
        """Cron: vaqti kelganlarni 'yuboradi'."""
        out = [i for i in self.items if i["due"] <= now]
        for i in out:
            self.sent[i["key"]] = now
        self.items = [i for i in self.items if i["key"] not in self.sent]
        return [i["text"] for i in out]

    def texts(self):
        return [i["text"] for i in self.items]


@pytest.fixture
def relay(monkeypatch):
    fake = FakeRelay()
    monkeypatch.setattr(tgsched, "_request", fake)
    monkeypatch.setattr(config, "RELAY_URL", "https://relay.test")
    monkeypatch.setattr(config, "RELAY_KEY", "k")
    monkeypatch.setattr(config, "OWNER_ID", CHAT)
    monkeypatch.setattr(tools, "_prayer_times", lambda city, d: {
        "Fajr": "05:20", "Dhuhr": "12:10", "Asr": "15:25", "Maghrib": "17:55", "Isha": "19:15"})
    tgsched._prayer_cache.clear()
    tgsched._sent_cache.update(ts=0.0, keys=set())
    return fake


def _rem(text, at):
    memory.add_reminder(CHAT, text, at)
    return memory.pending_reminders_with_id(CHAT)[-1][0]


def test_evening_reminder_queued_as_html_and_cancel_removes(relay, monkeypatch):
    monkeypatch.setattr(memory.time, "time", lambda: NOW)
    _rem("Dori ichish", NOW + 11 * 3600)                     # 21:00 — PC o'chiq bo'ladi
    _rem("Tez orada", NOW + 120)                               # 2 daqiqa — bot o'zi
    assert tgsched.sync(CHAT, NOW) == 1
    assert relay.texts() == ["⏰ Eslatma: Dori ichish"]
    assert tgsched.sync(CHAT, NOW + 60) is None and relay.puts == 1   # o'zgarmadi — yuborilmaydi
    memory.cancel_reminder(CHAT, all_=True)
    tgsched.sync(CHAT, NOW + 120)
    assert relay.items == []


def test_items_within_handoff_are_left_to_the_bot(relay, monkeypatch):
    monkeypatch.setattr(memory.time, "time", lambda: NOW)
    _rem("Qo'ng'iroq", NOW + 3600)
    tgsched.sync(CHAT, NOW)
    assert len(relay.items) == 1
    tgsched.sync(CHAT, NOW + 3600 - 150)                       # 2.5 daq qoldi — bot o'zi yuboradi
    assert relay.items == []
    assert relay.run_due(NOW + 3600) == []                     # relay yubormaydi — takror yo'q


def test_pc_off_relay_sends_and_bot_skips_later(relay, monkeypatch):
    monkeypatch.setattr(memory.time, "time", lambda: NOW)
    rid = _rem("Kechki eslatma", NOW + 5 * 3600)
    tgsched.sync(CHAT, NOW)
    # PC o'chdi: sync boshqa ishlamaydi, relay o'z vaqtida yuboradi
    assert relay.run_due(NOW + 5 * 3600) == ["⏰ Eslatma: Kechki eslatma"]
    # Ertasi kuni PC yondi — bot "o'tib ketgan" eslatmani qayta yubormasligi kerak
    tgsched.refresh_sent(force=True)
    assert tgsched.claim(CHAT, f"rem:{rid}") is True
    assert tgsched.claim(CHAT, "rem:999") is False


def test_prayers_dates_recurring_football(relay, monkeypatch):
    memory.set_setting(CHAT, "auto_prayer", "1")
    memory.set_setting(CHAT, "football", "1")
    memory.add_recurring(CHAT, "Yig'ilish", 18, 0, None)
    memory.add_date(CHAT, "Akamning tug'ilgan kuni", 10, 15)
    tz = football.TZ
    m = {"id": "e2", "kickoff": dt.datetime(2026, 10, 15, 0, 0, tzinfo=tz), "home": "Man City", "away": "PSG",
         "league": "Chempionlar ligasi", "venue": "Etihad Stadium", "is_home": True,
         "status": "STATUS_SCHEDULED", "slug": "uefa.champions", "home_score": None, "away_score": None}
    monkeypatch.setattr(football, "fixtures", lambda: [m])
    tgsched.sync(CHAT, NOW)
    keys = {i["key"]: i for i in relay.items}
    assert sum(k.startswith("pray:") and k.endswith(":Xufton") for k in keys) == 3
    assert sum(k.startswith("rec:") for k in keys) == 3
    assert any(k.endswith(":eve") for k in keys) and any(k.endswith(":day") and k.startswith("date:") for k in keys)
    day = keys["fb:e2:day"]
    assert dt.datetime.fromtimestamp(day["due"], tz).strftime("%d.%m %H:%M") == "14.10 08:00"
    assert "<b>" in day["text"] and "bugun kechasi soat 00:00 (15.10)" in day["text"]
    assert keys["fb:e2:pre"]["due"] == m["kickoff"].timestamp() - 3600
    assert min(i["due"] for i in relay.items) > NOW + tgsched.HANDOFF_SEC


def test_only_owner_and_only_when_configured(relay, monkeypatch):
    assert not tgsched.enabled(12345)                          # boshqa chat
    memory.set_setting(CHAT, "tg_sched_on", "0")
    assert tgsched.sync(CHAT, NOW) is None
    memory.set_setting(CHAT, "tg_sched_on", "1")
    monkeypatch.setattr(config, "RELAY_URL", "")
    assert not tgsched.enabled(CHAT)


def test_repush_after_interval_even_if_unchanged(relay, monkeypatch):
    monkeypatch.setattr(memory.time, "time", lambda: NOW)
    _rem("x", NOW + 86400)
    tgsched.sync(CHAT, NOW)
    tgsched.sync(CHAT, NOW + tgsched.REPUSH_SEC + 1)
    assert relay.puts == 2


def test_relay_down_does_not_break_claim(relay, monkeypatch):
    def down(*a, **k):
        raise ConnectionError("no wifi")
    monkeypatch.setattr(tgsched, "_request", down)
    tgsched.refresh_sent(force=True)
    assert tgsched.claim(CHAT, "rem:1") is False               # bilmasak — bot yuboradi


def test_toggle_tool(relay, monkeypatch):
    monkeypatch.setattr(memory.time, "time", lambda: NOW)
    _rem("x", NOW + 7200)
    tgsched.sync(CHAT, NOW)
    assert "O'CHIQ" in tools.execute_tool("set_telegram_schedule", {"on": False}, CHAT)
    assert relay.items == []
    assert "YOQIQ" in tools.execute_tool("set_telegram_schedule", {"on": True}, CHAT)
    tgsched.sync(CHAT, NOW + 60)
    assert len(relay.items) == 1


def test_toggle_tool_when_not_configured(monkeypatch):
    monkeypatch.setattr(config, "RELAY_URL", "")
    assert "sozlanmagan" in tools.execute_tool("set_telegram_schedule", {"on": True}, CHAT)


def test_match_alerts_skip_what_relay_sent(monkeypatch):
    tz = football.TZ
    m = {"id": "e1", "kickoff": dt.datetime(2026, 10, 11, 20, 30, tzinfo=tz), "home": "Liverpool",
         "away": "Man City", "league": "APL", "venue": "", "is_home": False, "status": "STATUS_SCHEDULED",
         "slug": "eng.1", "home_score": None, "away_score": None}
    monkeypatch.setattr(football, "fixtures", lambda: [m])
    monkeypatch.setattr(football, "results", lambda: [])
    out = football.match_alerts(CHAT, dt.datetime(2026, 10, 11, 9, 0, tzinfo=tz), claim=lambda k: True)
    assert out == [] and "day:e1" in football._sent(CHAT)
