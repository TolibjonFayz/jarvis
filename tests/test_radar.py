"""ERP radar: qoidalar (evaluate) va xabar holati (step) — tarmoq/baza'siz."""
import datetime

import radar
from conftest import CHAT

TUE_NOON = datetime.datetime(2026, 11, 3, 12, 0)   # seshanba
T = TUE_NOON.timestamp()
OK_API = (True, "")


def data(hik_age_min=10, amo=None, err_n=0):
    return {
        "hik_last": T - hik_age_min * 60 if hik_age_min is not None else None,
        "amo": amo if amo is not None else [{"entity": "leads", "last": T - 300, "status": "ok", "error": None}],
        "err_n": err_n, "err_path": "/api/kp/create",
    }


def test_all_good():
    assert radar.evaluate(TUE_NOON, OK_API, data()) == {}


def test_hik_stale_only_in_work_hours():
    assert "hik" in radar.evaluate(TUE_NOON, OK_API, data(hik_age_min=150))
    assert radar.evaluate(TUE_NOON, OK_API, data(hik_age_min=75)) == {}      # normal tanaffus
    sunday = datetime.datetime(2026, 11, 1, 12, 0)
    assert "hik" not in radar.evaluate(sunday, OK_API, data(hik_age_min=2000))
    morning = datetime.datetime(2026, 11, 3, 9, 0)                          # hali kelishmagan
    assert "hik" not in radar.evaluate(morning, OK_API, data(hik_age_min=900))


def test_amo_error_and_stale():
    bad = [{"entity": "leads", "last": T - 60, "status": "error", "error": "401 token"},
           {"entity": "calls_leads", "last": T - 3600, "status": "ok", "error": None}]
    p = radar.evaluate(TUE_NOON, OK_API, data(amo=bad))
    assert "401 token" in p["amo:leads"] and "1 soat" in p["amo:calls_leads"]


def test_5xx_threshold():
    assert "5xx" not in radar.evaluate(TUE_NOON, OK_API, data(err_n=2))
    assert "5xx" in radar.evaluate(TUE_NOON, OK_API, data(err_n=3))


def test_db_down():
    p = radar.evaluate(TUE_NOON, (False, "timed out"), None, "could not connect")
    assert set(p) == {"api", "db"}


def test_api_needs_two_failures_then_recovers_once():
    p = {"api": "prod API javob bermayapti"}
    assert radar.step(CHAT, p, TUE_NOON) == []                              # 1-marta: jim
    msgs = radar.step(CHAT, p, TUE_NOON + datetime.timedelta(minutes=5))
    assert len(msgs) == 1 and "javob bermayapti" in msgs[0]
    assert radar.step(CHAT, p, TUE_NOON + datetime.timedelta(minutes=10)) == []  # takrorlanmaydi
    back = radar.step(CHAT, {}, TUE_NOON + datetime.timedelta(minutes=30))
    assert len(back) == 1 and "tiklandi" in back[0] and "30 daq" in back[0]


def test_single_blip_is_silent_both_ways():
    radar.step(CHAT, {"api": "x"}, TUE_NOON)
    assert radar.step(CHAT, {}, TUE_NOON + datetime.timedelta(minutes=5)) == []


def test_hik_alerts_immediately():
    msgs = radar.step(CHAT, {"hik": "terminal jim"}, TUE_NOON)
    assert msgs and "terminal jim" in msgs[0]


def test_db_blind_does_not_fake_recovery():
    radar.step(CHAT, {"hik": "terminal jim"}, TUE_NOON)
    msgs = radar.step(CHAT, {"db": "ulanmadi"}, TUE_NOON + datetime.timedelta(minutes=5))
    assert not any("tiklandi" in m for m in msgs)


def test_daily_full_reconcile_is_not_stale():
    amo = [{"entity": "leads_full", "last": T - 21 * 3600, "status": "ok", "error": None}]
    assert radar.evaluate(TUE_NOON, OK_API, data(amo=amo)) == {}
    amo[0]["last"] = T - 27 * 3600
    assert "amo:leads_full" in radar.evaluate(TUE_NOON, OK_API, data(amo=amo))
