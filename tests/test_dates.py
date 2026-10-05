"""Yillik sanalar (tug'ilgan kunlar): bir kun oldin + o'sha kuni, har yili."""
import datetime as dt

import pytest

import agent
import memory
import tools
from conftest import CHAT, reply

FINAL = tools.FINAL


def test_next_occurrence_rolls_to_next_year():
    today = dt.date(2026, 10, 20)
    assert memory.next_occurrence(10, 15, today) == dt.date(2027, 10, 15)
    assert memory.next_occurrence(10, 20, today) == today
    assert memory.next_occurrence(2, 29, dt.date(2026, 1, 1)) == dt.date(2026, 2, 28)
    assert memory.next_occurrence(2, 29, dt.date(2027, 3, 1)) == dt.date(2028, 2, 29)


def test_add_date_tool_and_list():
    out = tools.execute_tool("add_date", {"text": "Akamning tug'ilgan kuni", "month": 10, "day": 15,
                                          "year": None}, CHAT)
    assert out.startswith(FINAL) and "Akamning tug'ilgan kuni" in out and "15-oktyabr" in out
    tools.execute_tool("add_date", {"text": "Onamning tug'ilgan kuni", "month": 3, "day": 8,
                                    "year": 1970}, CHAT)
    text = tools.dates_text(CHAT, dt.date(2026, 10, 5))
    lines = text.splitlines()
    assert "Akam" in lines[1] and "10 kundan keyin" in lines[1]     # eng yaqini birinchi
    assert "Onam" in lines[2] and "57 yosh" in lines[2]


def test_invalid_date_rejected():
    assert "Bunday sana yo'q" in tools.execute_tool(
        "add_date", {"text": "x", "month": 2, "day": 31}, CHAT)
    assert memory.list_dates(CHAT) == []


def test_due_dates_day_before_and_day_of_once():
    memory.add_date(CHAT, "Akamning tug'ilgan kuni", 10, 15, 1995)
    early = dt.datetime(2026, 10, 14, 8, 0)
    assert memory.due_dates(early) == []                               # soat 9 dan oldin emas
    eve = memory.due_dates(dt.datetime(2026, 10, 14, 9, 30))
    assert [(t, is_today) for _c, t, _y, _o, is_today in eve] == [("Akamning tug'ilgan kuni", False)]
    assert memory.due_dates(dt.datetime(2026, 10, 14, 18, 0)) == []     # kuniga bir marta
    day = memory.due_dates(dt.datetime(2026, 10, 15, 11, 0))           # PC kech yoqilsa ham
    assert day and day[0][4] is True
    assert "31 yosh" in tools.date_alert_text(*day[0][1:])
    assert memory.due_dates(dt.datetime(2026, 10, 16, 10, 0)) == []
    assert memory.due_dates(dt.datetime(2027, 10, 14, 10, 0))          # kelasi yil yana


def test_delete_date():
    memory.add_date(CHAT, "A", 1, 1)
    memory.add_date(CHAT, "B", 12, 31)
    names = [r[1] for r in memory.list_dates(CHAT)]
    assert memory.delete_date(CHAT, 1) == names[0]
    assert [r[1] for r in memory.list_dates(CHAT)] == names[1:]
    assert memory.delete_date(CHAT, 5) is None


def test_weekly_report_mentions_upcoming(monkeypatch):
    import gcal
    monkeypatch.setattr(gcal, "available", lambda: False)
    memory.add_date(CHAT, "Akamning tug'ilgan kuni", 10, 15)
    text = tools.weekly_report_text(CHAT, today=dt.date(2026, 10, 12))
    assert "Yaqin sanalar" in text and "Akamning" in text


@pytest.mark.parametrize("text,cats", [
    ("Eslab qol: akamning tug'ilgan kuni 15-oktyabr", ["esl"]),   # endi yillik sana
    ("onamning tug‘ilgan kuni qachon?", ["esl"]),
    ("har yili 8-martda eslat", ["esl"]),
    ("eslab qol: men qahvani shakarsiz ichaman", ["xot"]),
])
def test_birthday_routes(text, cats):
    assert agent.forced_categories(text) == cats


def test_birthday_flow_uses_add_date(llm):
    llm(reply(calls=[("add_date", {"text": "Akamning tug'ilgan kuni", "month": 10, "day": 15})]))
    out = agent.respond(CHAT, "akamning tug'ilgan kuni 15-oktyabr, eslatib tur")
    assert "Yillik sana qo'shildi" in out
    assert [r[1] for r in memory.list_dates(CHAT)] == ["Akamning tug'ilgan kuni"]
    assert memory.list_pending_reminders(CHAT) == []
