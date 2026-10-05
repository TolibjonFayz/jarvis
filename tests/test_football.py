"""Man City kuzatuvi — ESPN javoblari soxta (internetga chiqilmaydi)."""
import datetime as dt
import json
from types import SimpleNamespace as NS

import pytest

import agent
import football as fb
import memory
import tools
from conftest import CHAT, reply

TZ = fb.TZ


def _event(eid, when_local, home, away, slug="eng.1", status="STATUS_SCHEDULED", hs=None, as_=None):
    def team(name, tid):
        return {"id": tid, "displayName": name, "shortDisplayName": name}
    ids = {"Man City": "382"}
    return {
        "id": eid, "date": when_local.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "league": {"slug": slug},
        "competitions": [{
            "status": {"type": {"name": status}},
            "venue": {"fullName": "Etihad Stadium"},
            "competitors": [
                {"homeAway": "home", "team": team(home, ids.get(home, "1")), "score": {"displayValue": hs}},
                {"homeAway": "away", "team": team(away, ids.get(away, "2")), "score": {"displayValue": as_}},
            ],
        }],
    }


NOW = dt.datetime(2026, 10, 11, 9, 0, tzinfo=TZ)


@pytest.fixture
def espn(monkeypatch):
    data = {
        "fixtures": [
            _event("e1", dt.datetime(2026, 10, 11, 20, 30, tzinfo=TZ), "Liverpool", "Man City"),
            _event("e2", dt.datetime(2026, 10, 15, 0, 0, tzinfo=TZ), "Man City", "PSG", slug="uefa.champions"),
            _event("e9", dt.datetime(2026, 10, 12, 18, 0, tzinfo=TZ), "Man City", "X",
                   status="STATUS_POSTPONED"),
        ],
        "results": [
            _event("r1", dt.datetime(2026, 10, 10, 19, 0, tzinfo=TZ), "Man City", "Sunderland",
                   status="STATUS_FULL_TIME", hs="5", as_="3"),
            _event("r0", dt.datetime(2026, 10, 1, 19, 0, tzinfo=TZ), "Arsenal", "Man City",
                   status="STATUS_FULL_TIME", hs="1", as_="1"),
        ],
        "summary": {"keyEvents": [
            {"scoringPlay": True, "type": {"type": "goal"}, "clock": {"displayValue": "43'"},
             "team": {"displayName": "Manchester City"}, "participants": [{"athlete": {"displayName": "Semenyo"}}]},
            {"scoringPlay": True, "type": {"type": "goal"}, "clock": {"displayValue": "57'"},
             "team": {"displayName": "Manchester City"}, "participants": [{"athlete": {"displayName": "Semenyo"}}]},
            {"scoringPlay": True, "type": {"type": "penalty---scored"}, "clock": {"displayValue": "81'"},
             "team": {"displayName": "Manchester City"}, "participants": [{"athlete": {"displayName": "Haaland"}}]},
            {"scoringPlay": False, "type": {"type": "red-card"}, "clock": {"displayValue": "70'"},
             "team": {"displayName": "Sunderland"}, "participants": [{"athlete": {"displayName": "Brobbey"}}]},
        ]},
        "standings": {"children": [{"standings": {"entries": [{"team": {"id": "382"}, "stats": [
            {"name": n, "displayValue": v} for n, v in
            [("rank", "1"), ("points", "15"), ("gamesPlayed", "5"), ("wins", "5"), ("ties", "0"),
             ("losses", "0"), ("deductions", "0")]]}]}}]},
        "news": {"articles": []},
    }

    def get(url, ttl=0):
        if "fixture=true" in url:
            return {"events": data["fixtures"]}
        if "/schedule" in url:
            return {"events": data["results"]}
        if "summary" in url:
            return data["summary"]
        if "standings" in url:
            return data["standings"]
        if "news" in url:
            return data["news"]
        raise AssertionError(url)
    monkeypatch.setattr(fb, "_get", get)
    return data


def test_fixtures_text_skips_postponed_and_labels_night_games(espn):
    text = fb.fixtures_text(now=NOW)
    assert "bugun 20:30 — Liverpool (mehmonda) · APL" in text
    assert "Chorshanba kechasi 00:00 (15.10) — PSG (uyda) · Chempionlar ligasi" in text
    assert "X (uyda)" not in text and "1-o'rin, 15 ochko" in text


def test_result_text_groups_goals(espn):
    text = fb.result_text(fb.results()[0])
    assert text.startswith("✅ **Man City 5–3 Sunderland**")
    assert "Semenyo 43', 57'" in text and "Haaland (pen.) 81'" in text
    assert "🟥 70' Brobbey (Sunderland)" in text and "📊 APL" in text
    assert "➖" in fb.results_text()   # Arsenal 1-1


def test_match_alerts_morning_pre_and_result_once(espn):
    early = fb.match_alerts(CHAT, NOW.replace(hour=7))
    assert len(early) == 1 and "Sunderland" in early[0]          # natija; 8 dan oldin "bugun" yo'q
    morning = fb.match_alerts(CHAT, NOW)
    assert morning == [m for m in morning if "Bugun o'yin" in m] and "20:30" in morning[0]
    assert fb.match_alerts(CHAT, NOW.replace(hour=12)) == []      # takror yo'q
    pre = fb.match_alerts(CHAT, NOW.replace(hour=19, minute=35))
    assert len(pre) == 1 and "55 daqiqadan keyin" in pre[0]
    assert fb.match_alerts(CHAT, NOW.replace(hour=19, minute=50)) == []


def test_night_cl_game_announced_previous_morning(espn):
    wed = dt.datetime(2026, 10, 14, 9, 0, tzinfo=TZ)
    out = fb.match_alerts(CHAT, wed)
    assert any("PSG" in m and "bugun kechasi soat 00:00 (15.10)" in m for m in out)


def test_old_result_not_sent(espn):
    out = fb.match_alerts(CHAT, dt.datetime(2026, 10, 12, 9, 0, tzinfo=TZ))  # 38 soat o'tgan
    assert not any("Sunderland" in m for m in out)


def _art(aid, headline, published, teams=("Manchester City",)):
    return {"id": aid, "headline": headline, "description": headline, "published": published,
            "links": {"web": {"href": f"https://espn.test/{aid}"}},
            "categories": [{"type": "team", "description": t} for t in teams]}


def test_serious_news_links_by_headline_not_number(espn, llm):
    espn["news"]["articles"] = [
        _art(1, "Erling Haaland injury fear, asked to be substituted for Norway", "2026-10-05T06:38Z"),
        _art(2, "Transfer rumors, news: Haaland wants LaLiga move", "2026-10-05T05:00Z"),
        _art(3, "Man City appeal guilty verdict", "2026-10-05T04:00Z"),
        _art(4, "Klopp not preparing for more titles", "2026-10-05T03:00Z", teams=("Liverpool",)),
    ]
    # Model raqamlarni o'zicha 1,2 deb beradi — sarlavha bo'yicha bog'lanishi kerak
    content = json.dumps({"items": [
        {"headline": "Erling Haaland injury fear, asked to be substituted for Norway", "uz": "Haaland jarohat."},
        {"headline": "Man City appeal guilty verdict", "uz": "City apellyatsiya berdi."},
    ]})
    script = llm(reply(content))
    now = dt.datetime(2026, 10, 5, 9, 0, tzinfo=dt.timezone.utc)
    out = fb.serious_news(CHAT, now)
    assert len(out) == 2
    assert "Haaland jarohat." in out[0] and "espn.test/1" in out[0]
    assert "apellyatsiya" in out[1] and "espn.test/3" in out[1]
    sent = script.requests[0]["messages"][1]["content"]
    assert "Klopp" not in sent                                   # boshqa klub maqolasi
    # Ikkinchi tekshiruv: yangi maqola yo'q — model chaqirilmaydi, takror yo'q
    assert fb.serious_news(CHAT, now) == []


def test_serious_news_first_run_only_last_24h(espn, llm):
    espn["news"]["articles"] = [_art(1, "Old verdict story", "2026-10-01T06:00Z")]
    llm()  # model chaqirilmasligi kerak
    assert fb.serious_news(CHAT, dt.datetime(2026, 10, 5, 9, 0, tzinfo=dt.timezone.utc)) == []


def test_tools_and_alert_toggle(espn):
    assert "Liverpool" in tools.execute_tool("city_fixtures", {}, CHAT)
    assert "Semenyo" in tools.execute_tool("city_results", {"last_detail": True}, CHAT)
    assert "YOQILDI" in tools.execute_tool("set_football_alerts", {"on": True}, CHAT)
    assert memory.get_setting(CHAT, "football") == "1"


def test_weekly_report_has_city_when_enabled(espn, monkeypatch):
    import gcal
    monkeypatch.setattr(gcal, "available", lambda: False)
    memory.set_setting(CHAT, "football", "1")
    text = tools.weekly_report_text(CHAT, today=dt.date(2026, 10, 11))
    assert "⚽ **Man City**" in text and "Liverpool" in text


@pytest.mark.parametrize("text,cats", [
    ("Man City keyingi o'yini qachon?", ["futbol"]),
    ("manchester city kecha qanday o'ynadi", ["futbol"]),
    ("Siti bugun o'ynaydimi", ["futbol"]),
    ("city o'yini nechida", ["futbol"]),
    ("Tashkent city mall qayerda", None),
])
def test_city_routes(text, cats):
    assert agent.forced_categories(text) == cats
