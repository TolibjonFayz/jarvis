"""Proaktiv miya: slotlar, filtrlar (mute/takror/chegara/sinov rejimi), JSON tahlili."""
import datetime
import json

import pytest

import memory
import proactive
from conftest import CHAT, reply

NOW = datetime.datetime(2026, 11, 4, 10, 5)
SIGNALS = {"javobsiz": ["Aziz: 20 soat javob kutyapti"], "kalendar": ["ertaga 10:00–11:00: Aziz bilan KP"]}


@pytest.fixture(autouse=True)
def tmp_log(tmp_path, monkeypatch):
    monkeypatch.setattr(proactive, "LOG_PATH", str(tmp_path / "proactive.jsonl"))
    monkeypatch.setattr(proactive, "gather", lambda chat_id, now=None: SIGNALS)


def alerts(*items):
    return reply(json.dumps({"alerts": list(items)}))


def a(key, imp=3, kind="javobsiz", text="Bro, Aziz ertangi uchrashuvdan oldin javob kutyapti"):
    return {"kind": kind, "key": key, "importance": imp, "text": text}


def test_slot_fires_once_and_respects_grace():
    assert proactive.due_slot(CHAT, NOW) == "2026-11-04 10:00"
    assert proactive.due_slot(CHAT, NOW + datetime.timedelta(minutes=5)) is None
    assert proactive.due_slot(CHAT, datetime.datetime(2026, 11, 4, 9, 30)) is None
    # 13:00 slot, kompyuter 14:30 da yondi — hali kech emas; 18:00 dan 3 soat keyin — kech
    assert proactive.due_slot(CHAT, datetime.datetime(2026, 11, 4, 14, 30)) == "2026-11-04 13:00"
    assert proactive.due_slot(CHAT, datetime.datetime(2026, 11, 4, 21, 0)) is None


def test_off_switch():
    memory.set_setting(CHAT, "proactive_on", "0")
    assert proactive.due_slot(CHAT, NOW) is None


def test_sends_important_and_logs_everything(llm):
    llm(alerts(a("javobsiz:Aziz", 3), a("loyiha:erp", 2, "loyiha", "ERP'da 3 kun commit yo'q")))
    out = proactive.run(CHAT, NOW)
    assert [x["key"] for x in out] == ["javobsiz:Aziz"]       # sinov rejimi: faqat 3
    rows = proactive._log_rows()
    assert {r["key"]: r["why"] for r in rows} == {"javobsiz:Aziz": "", "loyiha:erp": "sinov_rejimi"}


def test_no_repeat_of_sent_key(llm):
    llm(alerts(a("javobsiz:Aziz")), alerts(a("javobsiz:Aziz")))
    assert proactive.run(CHAT, NOW)
    assert proactive.run(CHAT, NOW + datetime.timedelta(hours=3)) == []


def test_daily_cap_and_force(llm):
    memory.set_setting(CHAT, "proactive_since", "1")  # sinov rejimi tugagan
    llm(alerts(a("k1", 2), a("k2", 2)), alerts(a("k3", 2), a("k4", 2)), alerts(a("k5", 2)))
    assert len(proactive.run(CHAT, NOW)) == 2
    assert len(proactive.run(CHAT, NOW)) == 1                 # 3 dan oshmaydi
    assert len(proactive.run(CHAT, NOW, force=True)) == 1     # /miya hozir chegarasiz


def test_muted_kind_is_dropped(llm):
    proactive.mute(CHAT, "javobsiz")
    llm(alerts(a("javobsiz:Aziz")))
    assert proactive.run(CHAT, NOW) == []
    proactive.unmute(CHAT)
    assert proactive.muted(CHAT) == []


def test_bad_model_output_is_silent(llm):
    llm(reply("Hmm, menimcha hech narsa yo'q"), reply('{"alerts": [{"kind": "xyz", "text": "  "}]}'))
    assert proactive.run(CHAT, NOW) == []
    assert proactive.run(CHAT, NOW) == []


def test_unknown_kind_and_importance_clamped(llm):
    llm(reply('<think>x</think>{"alerts": [{"kind": "yangi", "key": "z", "importance": 9, "text": "Salom"}]}'))
    out = proactive.run(CHAT, NOW)
    assert out[0]["kind"] == "boshqa" and out[0]["importance"] == 3


def test_no_signals_no_llm_call(llm, monkeypatch):
    monkeypatch.setattr(proactive, "gather", lambda chat_id, now=None: {})
    script = llm()
    assert proactive.run(CHAT, NOW) == []
    assert script.requests == []


def test_feedback_mute_via_row(llm):
    llm(alerts(a("javobsiz:Aziz")))
    row = proactive.run(CHAT, NOW)[0]
    assert proactive.find(row["id"])["kind"] == "javobsiz"
    proactive.like(CHAT, "javobsiz")
    assert proactive.liked(CHAT) == ["javobsiz"]


def test_prompt_has_no_message_text_for_unanswered(monkeypatch):
    import userbot
    monkeypatch.setattr(userbot, "unanswered", lambda **k: [
        {"id": 1, "name": "Aziz", "minutes": 1500, "unread": 2, "preview": "MAXFIY matn"}])
    lines = proactive._unanswered()
    assert lines == ["Aziz: 1 kun javob kutyapti, 2 o'qilmagan"]


def test_local_signals_from_db():
    today = NOW.date()
    memory.add_todo(CHAT, "KP yuborish")
    memory.set_budget(CHAT, "ovqat", 2_000_000)
    memory.add_expense(CHAT, 1_700_000, "ovqat", "bozor", today.isoformat())
    assert proactive._todos(CHAT, NOW)[0].startswith("KP yuborish")
    money = proactive._money(CHAT, NOW)
    assert any("ovqat" in m and "85%" in m for m in money)
    assert any("oxirgi 7 kun" in m for m in money)
