"""Deterministik qismlar: sanalar, pul, budjet, eslatmalar, kun tartibi, formatlash."""
import datetime
import json
import os
import sqlite3
import time
import zipfile
from types import SimpleNamespace as NS

import pytest

import backup
import fmt
import gcal
import memory
import tools
import userbot
from conftest import CHAT

WED = datetime.date(2026, 9, 23)  # chorshanba


def run(name, args=None):
    return tools.execute_tool(name, args or {}, CHAT).replace(tools.FINAL, "")


# --- Sanalar (model "juma"ni yakshanba deb hisoblagan edi) ---

@pytest.mark.parametrize("text,expected", [
    ("bugun", WED), ("ertaga", datetime.date(2026, 9, 24)), ("indinga", datetime.date(2026, 9, 25)),
    ("juma", datetime.date(2026, 9, 25)), ("juma kuni", datetime.date(2026, 9, 25)),
    ("kelasi juma", datetime.date(2026, 10, 2)), ("shanba", datetime.date(2026, 9, 26)),
    ("yakshanba", datetime.date(2026, 9, 27)), ("dushanba", datetime.date(2026, 9, 28)),
    ("chorshanba", WED), ("2026-12-31", datetime.date(2026, 12, 31)),
])
def test_resolve_date(text, expected):
    assert gcal.resolve_date(text, today=WED) == expected


def test_resolve_date_rejects_garbage():
    with pytest.raises(ValueError):
        gcal.resolve_date("qachondir", today=WED)


def test_calendar_add_rolls_past_date_to_next_year(monkeypatch):
    inserted = []

    class Ev:
        def insert(self, calendarId, body):
            inserted.append(body)
            return NS(execute=lambda: {})

    monkeypatch.setattr(gcal, "_svc", lambda: NS(events=lambda: Ev()))
    monkeypatch.setattr(gcal, "available", lambda: True)
    out = gcal.add_event("Onamning tug'ilgan kuni", "2020-03-12")
    assert "keyingi yilga" in out
    assert inserted[0]["start"]["date"] > datetime.date.today().isoformat()


@pytest.mark.parametrize("period,start,end", [
    ("bugun", WED, WED), ("kecha", datetime.date(2026, 9, 22), datetime.date(2026, 9, 22)),
    ("hafta", datetime.date(2026, 9, 21), WED),
    ("otgan_hafta", datetime.date(2026, 9, 14), datetime.date(2026, 9, 20)),
    ("oy", datetime.date(2026, 9, 1), WED),
    ("otgan_oy", datetime.date(2026, 8, 1), datetime.date(2026, 8, 31)),
])
def test_period_range(period, start, end):
    assert tools._period_range(period, WED) == (start, end)


# --- Xarajat va budjet ---

def test_add_expense_multiple_items_and_total():
    out = run("add_expense", {"items": [
        {"amount": 25000, "category": "transport", "note": "taksi"},
        {"amount": 45000.0, "category": "yo'q_kategoriya", "note": "obed"},
    ]})
    assert "70 000 so'm" in out
    assert "boshqa" in out  # noma'lum kategoriya -> boshqa


def test_negative_amount_rejected():
    assert "musbat" in run("add_expense", {"items": [{"amount": -5, "category": "ovqat"}]})


def test_budget_alerts_fire_once_per_level():
    run("set_budget", {"category": "ovqat", "amount": 500000})
    first = run("add_expense", {"items": [{"amount": 420000, "category": "ovqat"}]})
    assert "84%" in first
    again = run("add_expense", {"items": [{"amount": 10000, "category": "ovqat"}]})
    assert "ishlatildi" not in again  # 80% qayta aytilmaydi
    over = run("add_expense", {"items": [{"amount": 100000, "category": "ovqat"}]})
    assert "tugadi" in over


def test_budget_status_bar():
    run("set_budget", {"category": "jami", "amount": 1000000})
    run("add_expense", {"items": [{"amount": 250000, "category": "uy"}]})
    out = run("budget_status")
    assert "25%" in out and "▓▓" in out


# --- Eslatmalar va vazifalar ---

def test_list_reminders_shows_both_kinds():
    # Avval faqat bir martaliklar ko'rinib, 8 ta takroriy bo'lsa ham "yo'q" derdi.
    memory.add_recurring(CHAT, "tabletka", 9, 0)
    assert "tabletka" in run("list_reminders")


def test_bulk_cancel():
    memory.add_recurring(CHAT, "a", 9, 0)
    memory.add_recurring(CHAT, "b", 10, 0)
    memory.add_reminder(CHAT, "c", time.time() + 600)
    memory.add_todo(CHAT, "d")
    assert "2 ta" in run("cancel_recurring", {"all": True})
    assert "1 ta" in run("cancel_reminder", {"all": True})
    assert "1 ta" in run("complete_todo", {"all": True})
    assert "yo'q" in run("list_reminders")


def test_agenda_combines_sources():
    memory.add_recurring(CHAT, "tabletka", 9, 0)
    memory.add_todo(CHAT, "non olish")
    out = run("agenda", {"period": "bugun"})
    assert "tabletka" in out and "non olish" in out


def test_agenda_empty():
    assert "hech narsa" in run("agenda", {"period": "ertaga"})


# --- Formatlash ---

def test_markdown_to_html():
    html = fmt.to_html("## Sarlavha\n- **qalin** va `a < b`\n```py\nx = '**not bold**'\n```")
    assert "<b>Sarlavha</b>" in html and "• <b>qalin</b>" in html
    assert "<code>a &lt; b</code>" in html
    assert "**not bold**" in html  # kod ichi formatlanmaydi


def test_table_flattened():
    assert fmt.to_html("| a | b |\n|---|---|\n| 1 | 2 |") == "a — b\n1 — 2"


def test_split_long_text():
    chunks = fmt.split("abc\n\n" * 2000, limit=3500)
    assert len(chunks) > 1 and all(len(c) <= 3500 for c in chunks)


# --- Zaxira nusxa ---

def test_backup_rotation_and_integrity(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path / "b"))
    monkeypatch.setattr(backup.config, "DB_PATH", memory.DB_PATH)
    for i in range(10):
        backup.daily(datetime.date(2026, 9, 1) + datetime.timedelta(days=i))
    files = sorted(os.listdir(tmp_path / "b"))
    assert len(files) == backup.KEEP_DAYS and files[-1] == "jarvis-2026-09-10.db"
    assert backup.integrity_ok(str(tmp_path / "b" / files[-1]))
    z = backup.weekly_zip(datetime.date(2026, 9, 10))
    assert zipfile.ZipFile(z).namelist() == ["jarvis.db"]


# --- Token hisobi ---

def test_usage_window():
    memory.add_usage("m", 100)
    with sqlite3.connect(memory.DB_PATH) as c:
        c.execute("INSERT INTO usage VALUES (?,?,?)", (time.time() - 25 * 3600, "m", 999))
    assert memory.usage_since(24) == {"m": 100}


# --- Javobsiz xabarlar filtri ---

def _msg(text="", **media):
    return NS(text=text, sticker=None, gif=None, voice=None, video_note=None,
              photo=None, video=None, document=None, file=None, **{**{}, **media}) \
        if not media else NS(**{**dict(text=text, sticker=None, gif=None, voice=None,
                                     video_note=None, photo=None, video=None,
                                     document=None, file=None), **media})


@pytest.mark.parametrize("text,no_reply", [
    ("Rahmat aytganiz kelsin", True), ("Xaa", True), ("ok", True), ("👍", True),
    ("xabar yubordim, ko'rdingmi?", False), ("xafa bo'ldim", False),
    ("ertaga kelasanmi?", False), ("Salom, ishlar qalay", False),
])
def test_needs_no_reply(text, no_reply):
    assert userbot._needs_no_reply(_msg(text)) == no_reply


def test_sticker_counts_and_preview():
    m = _msg(sticker=True, file=NS(emoji="😃"))
    assert userbot._needs_no_reply(m) is False  # stikerlar endi hisoblanadi
    assert userbot._preview(m) == "(stiker 😃)"
