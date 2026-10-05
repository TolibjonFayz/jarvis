"""Hozir nima o'ynayapti + loop — Windows media sessiyasi soxtasi bilan (haqiqiy pleerga tegmaydi)."""
import datetime as dt
from types import SimpleNamespace as NS

import pytest

import agent
import memory
import nowplaying as npl
import tools
from conftest import CHAT

FINAL = tools.FINAL


class FakeSession:
    def __init__(self, title="Yolg'izim", artist="Ummon", pos=30.0, dur=240.0, status=npl.PLAYING,
                 seek=True, app="www.youtube.com-54E21B02!App"):
        self.title, self.artist, self.pos, self.dur, self.status = title, artist, pos, dur, status
        self.seek, self.source_app_user_model_id, self.seeks = seek, app, []

    async def try_get_media_properties_async(self):
        return NS(title=self.title, artist=self.artist)

    def get_playback_info(self):
        return NS(playback_status=self.status, controls=NS(is_playback_position_enabled=self.seek))

    def get_timeline_properties(self):
        # last_updated_time = hozir: o'tgan vaqt qo'shilmasin (test aniq bo'lsin)
        return NS(position=dt.timedelta(seconds=self.pos), end_time=dt.timedelta(seconds=self.dur),
                  last_updated_time=dt.datetime.now(dt.timezone.utc))

    async def try_change_playback_position_async(self, ticks):
        self.seeks.append(ticks)
        self.pos = ticks / 10_000_000
        return True


@pytest.fixture
def player(monkeypatch):
    holder = {"s": FakeSession()}

    async def pick():
        return holder["s"]
    monkeypatch.setattr(npl, "_pick_session", pick)
    npl.LOOP.clear()
    yield holder
    npl.LOOP.clear()


def test_now_playing_text(player):
    text = npl.now_playing_text()
    assert "Yolg'izim" in text and "Ummon" in text and "0:30 / 4:00" in text and "YouTube" in text


def test_nothing_playing(player):
    player["s"] = None
    assert "hech narsa o'ynamayapti" in npl.now_playing_text()


def test_loop_restarts_near_end(player):
    s = player["s"]
    assert "Takrorlash yoqildi" in npl.set_loop(True, CHAT)
    assert npl.loop_tick() is None and s.seeks == []          # hali o'rtasida
    s.pos = 237.5                                              # 2.5 s qoldi
    assert npl.loop_tick() is None and s.seeks == [0]
    assert npl.LOOP["count"] == 1 and "takrorlanyapti" in npl.now_playing_text()


def test_loop_stops_when_song_changes(player):
    npl.set_loop(True, CHAT)
    player["s"].title = "Boshqa qo'shiq"
    chat, msg = npl.loop_tick()
    assert chat == CHAT and "boshqa qo'shiq qo'yildi" in msg and "Yolg'izim" in msg
    assert npl.LOOP == {}


def test_loop_ignores_blank_title_while_loading(player):
    npl.set_loop(True, CHAT)
    player["s"].title = ""
    assert npl.loop_tick() is None and npl.LOOP


def test_loop_refused_when_cannot_seek_or_live(player):
    player["s"].seek = False
    assert "takrorlab bo'lmaydi" in npl.set_loop(True, CHAT) and not npl.LOOP
    player["s"] = FakeSession(dur=0)
    assert "uzunligi noma'lum" in npl.set_loop(True, CHAT) and not npl.LOOP


def test_loop_off(player):
    assert "yoqilmagan" in npl.set_loop(False)
    npl.set_loop(True, CHAT)
    assert "o'chirildi" in npl.set_loop(False) and not npl.LOOP


def test_tool_actions(player):
    out = tools.execute_tool("pc_media", {"action": "now_playing"}, CHAT)
    assert out.startswith(FINAL) and "Yolg'izim" in out
    assert "yoqildi" in tools.execute_tool("pc_media", {"action": "loop_on"}, CHAT)
    assert npl.LOOP["chat_id"] == CHAT


# Haqiqiy suhbatdan (2026-10-05): "What music is playing now on my pc" -> "ma'lumotim yo'q",
# "Put this music on loop" -> "loop funksiyasi yo'q".
@pytest.mark.parametrize("text,action", [
    ("What music is playing now on my pc", "now_playing"), ("What music is playing noe", "now_playing"),
    ("hozir qaysi qo'shiq o'ynayapti", "now_playing"), ("bu qaysi qo'shiq", "now_playing"),
    ("Put this music on loop", "loop_on"), ("shu qo'shiqni takrorla", "loop_on"),
    ("put it on repeat", "loop_on"), ("loopni o'chir", "loop_off"), ("stop the loop", "loop_off"),
])
def test_player_quick_paths(text, action, player):
    assert agent.quick_media(text, CHAT) == (action, None)


@pytest.mark.parametrize("text", [
    "python for loop nima", "takroriy eslatmalarni o'chir", "takroriylarni o'chir", "so'zni takrorla",
    "what song should I listen to", "hozir nima gap ketyapti", "qanaqa qo'shiq qo'yay", "loop qil",
])
def test_player_quick_paths_dont_steal(text, player):
    assert agent.quick_media(text, CHAT) is None


def test_short_loop_words_need_music_context(player):
    import time
    memory.set_setting(CHAT, "music_ts", time.time())
    assert agent.quick_media("loop qil", CHAT) == ("loop_on", None)
    assert agent.quick_media("takrorlashni o'chir", CHAT) is None      # loop yoqilmagan
    npl.set_loop(True, CHAT)
    assert agent.quick_media("takrorlashni o'chir", CHAT) == ("loop_off", None)


def test_now_playing_skips_model(player, llm):
    script = llm()
    out = agent.respond(CHAT, "What music is playing now on my pc")
    assert "Yolg'izim" in out and script.requests == []
