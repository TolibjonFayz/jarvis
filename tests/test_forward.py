"""Forward -> tugma amallari va eslatma vaqtini kodda hisoblash."""
import datetime
from types import SimpleNamespace as NS

import pytest

import forward
import gcal
import memory
import tools
from conftest import CHAT, reply


@pytest.mark.parametrize("text,first", [
    ("Kecha taksiga 45 ming berdim", "pul"),
    ("Ertaga soat 15:00 da uchrashamiz, ofisga kel", "kal"),
    ("juma kuni Zoom'da yig'ilish bor", "kal"),
    ("Ertaga 9 da dorini ichishni unutma", "esl"),
    ("Non va sut olib kel", "todo"),
    ("Lorem ipsum " * 50, "xulosa"),
])
def test_suggest(text, first):
    order = forward.suggest(text)
    assert order[0] == first and sorted(order) == sorted(forward.ACTIONS)


def test_sender_name():
    assert forward.sender_name(NS(sender_user=NS(full_name="Aziz Karimov"))) == "Aziz Karimov"
    assert forward.sender_name(NS(sender_user=None, sender_user_name="Yashirin")) == "Yashirin"
    assert forward.sender_name(NS(sender_user=None, sender_user_name=None, chat=NS(title="Kun.uz"))) == "Kun.uz"
    assert forward.sender_name(None) == ""


def test_old_message_context_mentions_original_date():
    old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=2)
    sid = forward.add(CHAT, "ertaga kel", "Aziz", old)
    ctx = forward._context(forward.PENDING[sid])
    assert "Aziz" in ctx and "2 kun oldin" in ctx


def test_fresh_message_has_no_date_note():
    sid = forward.add(CHAT, "ertaga kel", "", datetime.datetime.now(datetime.timezone.utc))
    assert "kun oldin" not in forward._context(forward.PENDING[sid])


@pytest.fixture
def fake_calendar(monkeypatch):
    added = []

    class Ev:
        def insert(self, calendarId, body):
            added.append(body)
            return NS(execute=lambda: {"htmlLink": ""})

    monkeypatch.setattr(gcal, "_svc", lambda: NS(events=lambda: Ev()))
    monkeypatch.setattr(gcal, "available", lambda: True)
    return added


def test_run_calendar(llm, fake_calendar):
    sid = forward.add(CHAT, "Ertaga 15:00 da uchrashamiz", "Aziz", None)
    script = llm(reply("", [("calendar_add", {"title": "Aziz bilan uchrashuv", "date": "ertaga", "time": "15:00"})]))
    out = forward.run(sid, "kal")
    assert "Kalendarga qo'shildi" in out and fake_calendar[0]["summary"] == "Aziz bilan uchrashuv"
    assert script.requests[0]["tool_choice"] == "required"          # to'qib bo'lmaydi
    assert "Aziz" in script.requests[0]["messages"][-1]["content"]   # yuboruvchi berildi
    assert "kal" in forward.PENDING[sid]["done"]
    assert "[Forward" in memory.get_history(CHAT)[0]["content"]


def test_run_reminder_uses_code_for_time(llm):
    sid = forward.add(CHAT, "ertaga 9 da dori", "", None)
    llm(
        reply("", [("set_reminder", {"text": "Dori ichish", "date": "ertaga", "time": "09:00"})]),
        reply("Ertaga 09:00 da eslataman."),
    )
    forward.run(sid, "esl")
    (_id, text, ts), = memory.pending_reminders_with_id(CHAT)
    due = datetime.datetime.fromtimestamp(ts)
    assert text == "Dori ichish"
    assert due.date() == datetime.date.today() + datetime.timedelta(days=1) and due.hour == 9


def test_run_expense(llm):
    sid = forward.add(CHAT, "taksiga 45 ming", "", None)
    llm(reply("", [("add_expense", {"items": [{"amount": 45000, "category": "transport", "note": "taksi"}]})]))
    assert "45 000 so'm" in forward.run(sid, "pul")


def test_run_stale_forward():
    assert "eskirgan" in forward.run(99999, "kal")


# --- Eslatma vaqti: kod hisoblaydi ---

NOW = datetime.datetime(2026, 9, 23, 14, 0)  # chorshanba 14:00


def _due(**kw):
    return datetime.datetime.fromtimestamp(tools.reminder_due(now=NOW, **kw))


def test_reminder_date_and_time():
    assert _due(date="ertaga", time_="15:00") == datetime.datetime(2026, 9, 24, 15, 0)
    assert _due(date="juma", time_="9:30") == datetime.datetime(2026, 9, 25, 9, 30)


def test_reminder_time_already_passed_today_goes_to_tomorrow():
    assert _due(time_="07:00") == datetime.datetime(2026, 9, 24, 7, 0)
    assert _due(time_="18:00") == datetime.datetime(2026, 9, 23, 18, 0)


def test_reminder_explicit_past_date_rejected():
    with pytest.raises(ValueError):
        tools.reminder_due(date="2026-09-01", time_="10:00", now=NOW)


def test_reminder_minutes():
    assert _due(minutes=30) == NOW + datetime.timedelta(minutes=30)


def test_reminder_needs_some_time():
    with pytest.raises(ValueError):
        tools.reminder_due(now=NOW)
