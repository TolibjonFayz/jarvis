"""Telegram rejalashtirish — userbot soxta (haqiqiy akkauntga hech narsa yuborilmaydi)."""
import datetime as dt
import time

import pytest

import config
import football
import memory
import tgsched
import tools
import userbot
from conftest import CHAT

NOW = dt.datetime(2026, 10, 13, 10, 0).timestamp()


class FakeTG:
    def __init__(self):
        self.scheduled, self.next_id, self.deleted = {}, 100, []

    def schedule(self, text, when):
        self.next_id += 1
        self.scheduled[self.next_id] = (when, text)
        return self.next_id

    def delete(self, ids):
        for i in ids:
            self.deleted.append(i)
            self.scheduled.pop(i, None)
        return True

    def texts(self):
        return sorted(t for _w, t in self.scheduled.values())


@pytest.fixture
def tg(monkeypatch):
    fake = FakeTG()
    monkeypatch.setattr(userbot, "schedule_saved", fake.schedule)
    monkeypatch.setattr(userbot, "delete_scheduled", fake.delete)
    monkeypatch.setattr(config, "TG_API_ID", 1)
    monkeypatch.setattr(config, "TG_API_HASH", "x")
    monkeypatch.setattr(tools, "_prayer_times", lambda city, d: {
        "Fajr": "05:20", "Dhuhr": "12:10", "Asr": "15:25", "Maghrib": "17:55", "Isha": "19:15"})
    tgsched._prayer_cache.clear()
    tgsched._pending_delete.clear()
    return fake


def _rem(text, at):
    memory.add_reminder(CHAT, text, at)
    return memory.pending_reminders_with_id(CHAT)[-1][0]


def test_evening_reminder_scheduled_and_cancel_removes_it(tg, monkeypatch):
    monkeypatch.setattr(memory.time, "time", lambda: NOW)
    rid = _rem("Dori ichish", NOW + 11 * 3600)               # 21:00 — PC o'chiq bo'ladi
    _rem("Tez orada", NOW + 120)                               # 2 daqiqa — bot o'zi
    assert tgsched.sync(CHAT, NOW) == (1, 0)
    assert tg.texts() == ["⏰ Eslatma: Dori ichish"]
    assert tgsched.sync(CHAT, NOW + 60) == (0, 0)              # takror rejalashtirilmaydi
    memory.cancel_reminder(CHAT, all_=True)
    assert tgsched.sync(CHAT, NOW + 120)[1] == 1 and tg.scheduled == {}


def test_prayers_dates_recurring_scheduled(tg):
    memory.set_setting(CHAT, "auto_prayer", "1")
    memory.add_recurring(CHAT, "Yig'ilish", 18, 0, None)
    memory.add_date(CHAT, "Akamning tug'ilgan kuni", 10, 15)
    tgsched.sync(CHAT, NOW)
    texts = tg.texts()
    assert sum("Xufton namozi" in t for t in texts) == 3          # 3 kunlik
    assert any("Ertaga: Akamning" in t for t in texts) and any("Bugun: Akamning" in t for t in texts)
    assert sum("Yig'ilish" in t for t in texts) == 3
    whens = sorted(w for w, _t in tg.scheduled.values())
    assert whens[0] > NOW + tgsched.LEAD_SEC                     # o'tganlari yo'q (bugungi bomdod)


def test_max_items_cap(tg, monkeypatch):
    monkeypatch.setattr(memory.time, "time", lambda: NOW)
    for i in range(120):
        _rem(f"r{i}", NOW + 3600 + i * 60)
    tgsched.sync(CHAT, NOW)
    assert len(tg.scheduled) == tgsched.MAX_ITEMS


def test_handoff_when_bot_online(tg, monkeypatch):
    monkeypatch.setattr(memory.time, "time", lambda: NOW)
    rid = _rem("Qo'ng'iroq", NOW + 3600)
    tgsched.sync(CHAT, NOW)
    assert tgsched.handoff(CHAT, NOW + 3600 - 600) == 0          # hali erta
    assert tgsched.handoff(CHAT, NOW + 3600 - 120) == 1          # 2 daq qoldi — Telegram'dan olinadi
    assert tg.scheduled == {}
    assert tgsched.claim(CHAT, f"rem:{rid}", NOW + 3601) is False  # bot o'zi yuboradi
    assert tgsched.sync(CHAT, NOW + 3600 - 60) == (0, 0)          # qayta rejalashtirilmaydi (LEAD)


def test_claim_after_pc_was_off(tg, monkeypatch):
    monkeypatch.setattr(memory.time, "time", lambda: NOW)
    rid = _rem("Kechki eslatma", NOW + 5 * 3600)
    tgsched.sync(CHAT, NOW)
    # PC o'chdi; ertasi kuni yondi — Telegram yetkazgan
    assert tgsched.claim(CHAT, f"rem:{rid}", NOW + 20 * 3600) is True
    assert tgsched.claim(CHAT, f"rem:{rid}", NOW + 20 * 3600) is False   # bir martalik


def test_claim_future_queues_delete(tg):
    memory.set_setting(CHAT, "football", "1")
    tgsched._save(CHAT, {"fb:1:pre": {"id": 555, "due": NOW + 3600, "h": "x"}})
    assert tgsched.claim(CHAT, "fb:1:pre", NOW) is False
    tgsched.handoff(CHAT, NOW)
    assert 555 in tg.deleted


def test_football_fixtures_scheduled(tg, monkeypatch):
    memory.set_setting(CHAT, "football", "1")
    tz = football.TZ
    ko_night = dt.datetime(2026, 10, 15, 0, 0, tzinfo=tz)
    m = {"id": "e2", "kickoff": ko_night, "home": "Man City", "away": "PSG", "league": "Chempionlar ligasi",
         "venue": "Etihad Stadium", "is_home": True, "status": "STATUS_SCHEDULED", "slug": "uefa.champions",
         "home_score": None, "away_score": None}
    monkeypatch.setattr(football, "fixtures", lambda: [m])
    tgsched.sync(CHAT, NOW)
    items = sorted(tg.scheduled.values())
    (day_at, day_txt), (pre_at, pre_txt) = items
    assert dt.datetime.fromtimestamp(day_at, tz).strftime("%d.%m %H:%M") == "14.10 08:00"   # oldingi kun
    assert "bugun kechasi soat 00:00 (15.10)" in day_txt
    assert pre_at == ko_night.timestamp() - 3600 and "60 daqiqadan keyin" in pre_txt


def test_owner_own_scheduled_messages_untouched(tg, monkeypatch):
    tg.scheduled[7] = (NOW + 9999, "egasining o'z eslatmasi")
    monkeypatch.setattr(memory.time, "time", lambda: NOW)
    _rem("x", NOW + 7200)
    tgsched.sync(CHAT, NOW)
    memory.cancel_reminder(CHAT, all_=True)
    tgsched.sync(CHAT, NOW + 60)
    assert 7 in tg.scheduled and 7 not in tg.deleted


def test_disabled_without_userbot_or_setting(tg, monkeypatch):
    memory.set_setting(CHAT, "tg_sched_on", "0")
    assert tgsched.sync(CHAT, NOW) == (0, 0)
    memory.set_setting(CHAT, "tg_sched_on", "1")
    monkeypatch.setattr(config, "TG_API_ID", 0)
    assert not tgsched.enabled(CHAT)


def test_toggle_tool_removes_scheduled(tg, monkeypatch):
    monkeypatch.setattr(memory.time, "time", lambda: NOW)
    monkeypatch.setattr(tools.time, "time", lambda: NOW)
    _rem("x", NOW + 7200)
    tgsched.sync(CHAT, NOW)
    out = tools.execute_tool("set_telegram_schedule", {"on": False}, CHAT)
    assert "O'CHIQ" in out and tg.scheduled == {}
    assert "YOQIQ" in tools.execute_tool("set_telegram_schedule", {"on": True}, CHAT)


def test_network_failure_keeps_going_next_time(tg, monkeypatch):
    monkeypatch.setattr(memory.time, "time", lambda: NOW)
    _rem("a", NOW + 3600)
    _rem("b", NOW + 7200)

    def boom(text, when):
        raise ConnectionError("no wifi")
    monkeypatch.setattr(userbot, "schedule_saved", boom)
    assert tgsched.sync(CHAT, NOW) == (0, 0)
    monkeypatch.setattr(userbot, "schedule_saved", tg.schedule)
    assert tgsched.sync(CHAT, NOW + 120) == (2, 0)


def test_match_alerts_skip_what_telegram_delivered(monkeypatch):
    tz = football.TZ
    m = {"id": "e1", "kickoff": dt.datetime(2026, 10, 11, 20, 30, tzinfo=tz), "home": "Liverpool",
         "away": "Man City", "league": "APL", "venue": "", "is_home": False, "status": "STATUS_SCHEDULED",
         "slug": "eng.1", "home_score": None, "away_score": None}
    monkeypatch.setattr(football, "fixtures", lambda: [m])
    monkeypatch.setattr(football, "results", lambda: [])
    out = football.match_alerts(CHAT, dt.datetime(2026, 10, 11, 9, 0, tzinfo=tz), claim=lambda k: True)
    assert out == []                                            # Telegram yetkazgan — takror yo'q
    assert "day:e1" in football._sent(CHAT)
