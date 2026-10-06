"""Telefon -> kompyuter saqlash, katta fayllar (userbot, foiz), takrorlashga majbur qilgan
xatolar: tanlash raqami, yuborish qayta urinishi, Gemini 503. Telegram/Telethon soxta."""
import asyncio
import os
import time
from types import SimpleNamespace as NS

import pytest

import agent
import bot
import bridge
import tools
import userbot
import vision
from conftest import CHAT


def _touch(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


@pytest.fixture
def pc(tmp_path, monkeypatch):
    home = tmp_path / "home"
    folders = {k: str(home / k.capitalize()) for k in ("downloads", "desktop", "documents", "screenshots")}
    for p in folders.values():
        os.makedirs(p)
    monkeypatch.setattr(bridge, "FOLDERS", folders)
    monkeypatch.setattr(bridge, "READ_ROOT", str(tmp_path / "projects"))
    monkeypatch.setattr(bridge, "SAVE_DIR", str(home / "Downloads" / "FRIDAY"))
    monkeypatch.setattr(bridge, "_SECRET_DIRS", bridge._SECRET_DIRS - {"appdata"})
    tools.PENDING_FILES.clear()
    tools.LAST_CANDIDATES.clear()
    yield NS(f=folders)
    tools.PENDING_FILES.clear()
    tools.LAST_CANDIDATES.clear()


class Status:
    """Soxta Telegram xabari: edit_text tarixini yozadi."""

    def __init__(self, text=""):
        self.texts = [text]

    async def edit_text(self, text):
        self.texts.append(text)


class Reply:
    def __init__(self):
        self.chat_id, self.statuses, self.docs = CHAT, [], []

    async def reply_text(self, text):
        st = Status(text)
        self.statuses.append(st)
        return st

    async def reply_document(self, fh, **kw):
        self.docs.append(kw)


# --- bot: telefondan kelgan fayl -> kompyuter ---

def test_save_regex_and_media_detection():
    assert bot._SAVE_RE.search("kompyuterga saqla") and bot._SAVE_RE.search("save")
    assert not bot._SAVE_RE.search("bu rasmda nima bor?")
    assert bot._COPY_REPLY_RE.match("kompyuterga nusxala") and bot._COPY_REPLY_RE.match("nusxala bro")
    assert not bot._COPY_REPLY_RE.match("nusxalab nima qilay")
    m = NS(document=None, photo=[NS(file_id="small", file_size=1), NS(file_id="big", file_size=9)],
           video=None, audio=None, voice=None, animation=None, video_note=None)
    fid, name, size, orig = bot._media_of(m)
    assert fid == "big" and name.startswith("rasm_") and name.endswith(".jpg") and orig is None
    doc = NS(document=NS(file_id="d", file_name="shartnoma.docx", file_size=5), photo=None)
    assert bot._media_of(doc)[1] == "shartnoma.docx" and bot._media_of(doc)[3] == "shartnoma.docx"


def test_save_small_file_via_bot_api(pc, monkeypatch):
    sent = []

    class File:
        async def download_to_drive(self, path, **kw):
            _touch(path, b"hello")

    async def get_file(fid, **kw):
        return File()

    async def send_md(b, chat, text, reply_to=None):
        sent.append(text)
    monkeypatch.setattr(bot, "_send_md", send_md)
    doc = NS(document=NS(file_id="d", file_name="shartnoma.docx", file_size=5), photo=None)
    asyncio.run(bot._save_to_pc(NS(bot=NS(get_file=get_file)), Reply(), doc))
    saved = os.path.join(bridge.SAVE_DIR, "shartnoma.docx")
    assert os.path.exists(saved) and "Kompyuterga saqlandi" in sent[0]


def test_save_big_file_via_userbot_with_progress(pc, monkeypatch):
    size = 300 * 1024 * 1024
    calls = {}

    def fake_download(bot_username, sz, orig, dest, progress=None):
        calls.update(user=bot_username, size=sz, orig=orig)
        for done in (size // 4, size // 2, size):
            progress(done, size)
        _touch(dest, b"film")
        return dest
    monkeypatch.setattr(userbot, "download_from_bot_chat", fake_download)
    monkeypatch.setattr(bot, "_userbot_ready", lambda: True)
    monkeypatch.setattr(bot._Progress, "__call__", _progress_no_throttle)
    reply = Reply()
    big = NS(document=NS(file_id="d", file_name="film.mkv", file_size=size), photo=None)

    async def run():
        await bot._save_to_pc(NS(bot=NS(username="friday_bot")), reply, big)
        await asyncio.gather(*bot._BG_TASKS)     # fon vazifasi tugashini kutamiz
        await asyncio.sleep(0)
    asyncio.run(run())
    st = reply.statuses[0]
    assert calls == {"user": "friday_bot", "size": size, "orig": "film.mkv"}
    assert any("50%" in t for t in st.texts)
    assert "Kompyuterga saqlandi" in st.texts[-1] and os.path.exists(os.path.join(bridge.SAVE_DIR, "film.mkv"))


def _progress_no_throttle(self, cur, total):
    asyncio.run_coroutine_threadsafe(self._edit(self.text(cur, total)), self.loop)


def test_save_big_file_needs_userbot_and_2gb_cap(pc, monkeypatch):
    monkeypatch.setattr(bot, "_userbot_ready", lambda: False)
    reply = Reply()
    big = NS(document=NS(file_id="d", file_name="film.mkv", file_size=25 * 1024 * 1024), photo=None)
    asyncio.run(bot._save_to_pc(NS(bot=None), reply, big))
    assert "userbot kerak" in reply.statuses[0].texts[0]
    huge = NS(document=NS(file_id="d", file_name="x.iso", file_size=3 * 1024 ** 3), photo=None)
    asyncio.run(bot._save_to_pc(NS(bot=None), reply, huge))
    assert "2 GB" in reply.statuses[1].texts[0]


# --- kompyuter -> telefon: katta fayl userbot orqali ---

def test_big_file_goes_to_saved_messages_with_progress(pc, monkeypatch):
    path = _touch(os.path.join(pc.f["downloads"], "Moon.Knight.mkv"))
    monkeypatch.setattr(os.path, "getsize", lambda p: 861 * 1024 * 1024)
    out = tools.execute_tool("pc_send_file", {"query": "moon knight"}, CHAT)
    assert "Saqlangan xabarlar" in out and tools.PENDING_FILES[0]["path"] == path

    def fake_send(p, caption="", progress=None):
        progress(100, 400)
        progress(400, 400)
        return True
    monkeypatch.setattr(userbot, "send_to_saved", fake_send)
    monkeypatch.setattr(bot._Progress, "__call__", _progress_no_throttle)
    reply = Reply()
    update = NS(effective_message=reply, effective_chat=NS(send_action=None))

    async def run():
        await bot._show_pending_sends(update, CHAT)
        await asyncio.gather(*bot._BG_TASKS)
        await asyncio.sleep(0)
    asyncio.run(run())
    st = reply.statuses[0]
    assert any("25%" in t for t in st.texts) and "yuborildi" in st.texts[-1]
    assert reply.docs == []                                   # bot API'ga urinmadi


def test_small_file_sent_by_bot_with_long_timeout(pc):
    path = _touch(os.path.join(pc.f["downloads"], "cv.pdf"))
    tools.PENDING_FILES.append({"chat_id": CHAT, "path": path, "caption": "cv.pdf",
                                "kind": "document", "temp": False})
    reply = Reply()

    async def send_action(a):
        pass
    update = NS(effective_message=reply, effective_chat=NS(send_action=send_action))
    asyncio.run(bot._show_pending_sends(update, CHAT))
    assert reply.docs[0]["write_timeout"] >= 300 and os.path.exists(path)   # asl fayl o'chmaydi


def test_progress_text():
    p = bot._Progress(None, "📤 film.mkv", None)
    p.start = time.time() - 10
    text = p.text(50 * 1024 * 1024, 200 * 1024 * 1024)
    assert "25%" in text and "▓▓░" in text and "MB/s" in text and "qoldi" in text


# --- "qaysi biri?" — raqam bilan tanlash, aniq moslik ---

def test_best_match_prefers_name_starting_with_query():
    cands = [r"C:\d\'City_of_Stars'_Duet_ft_Ryan_Gosling.mp3", r"C:\d\Ryan_Gosling_by_Gage_Skidmore.jpg"]
    assert bridge.best_match("Ryan Gosling", cands) == cands[1]
    assert bridge.best_match("moon", [r"C:\a\moon-pose.webp", r"C:\a\Moonlight.mp3"]) is None


def test_pick_by_number_after_list(pc):
    a = _touch(os.path.join(pc.f["downloads"], "report-2025.pdf"))
    b = _touch(os.path.join(pc.f["documents"], "report-2026.pdf"))
    out = tools.execute_tool("pc_send_file", {"query": "report"}, CHAT)
    assert "qaysi biri" in out
    order = tools.LAST_CANDIDATES[CHAT][1]
    assert agent.quick_bridge("2-sini yubor", CHAT) == ("pc_send_file", {"pick": 2})
    assert agent.quick_bridge("ikkinchisini", CHAT) == ("pc_send_file", {"pick": 2})
    assert agent.quick_bridge("oxirgisini yubor", CHAT) == ("pc_send_file", {"pick": 2})
    assert agent.quick_bridge("2", None) is None                  # chat noma'lum — tanlov yo'q
    tools.execute_tool("pc_send_file", {"pick": 2}, CHAT)
    assert tools.PENDING_FILES[-1]["path"] == order[1] and {a, b} == set(order)
    assert CHAT not in tools.LAST_CANDIDATES                       # tanlangach ro'yxat yopiladi
    assert agent.quick_bridge("2", CHAT) is None


def test_pick_expires(pc):
    tools.LAST_CANDIDATES[CHAT] = (time.time() - tools.PICK_TTL - 1, ["x"])
    assert agent.quick_bridge("1", CHAT) is None
    assert "ro'yxat yo'q" in tools.execute_tool("pc_send_file", {"pick": 1}, CHAT)


# --- javob yo'qolmasin: yuborishni qayta urinish ---

def test_send_md_retries_on_timeout(monkeypatch):
    from telegram.error import TimedOut
    calls = []

    class Bot:
        async def send_message(self, *a, **kw):
            calls.append(1)
            if len(calls) < 3:
                raise TimedOut()

    async def nosleep(_):
        pass
    monkeypatch.setattr(bot.asyncio, "sleep", nosleep)
    asyncio.run(bot._send_md(Bot(), CHAT, "salom"))
    assert len(calls) == 3


def test_send_md_bad_request_not_retried_forever(monkeypatch):
    from telegram.error import BadRequest
    calls = []

    class Bot:
        async def send_message(self, *a, **kw):
            calls.append(kw.get("parse_mode"))
            if kw.get("parse_mode"):
                raise BadRequest("can't parse entities")
    asyncio.run(bot._send_md(Bot(), CHAT, "*buzuq"))
    assert calls == ["HTML", None]                                  # HTML -> oddiy matn, tamom


# --- Gemini 503: o'zi qayta urinadi ---

def test_vision_retries_transient_503(monkeypatch):
    results = iter([(None, "m: HTTP 503", True), ("Rasmda ot bor", "", True)])
    monkeypatch.setattr(vision, "_try_models", lambda body: next(results))
    monkeypatch.setattr(vision, "available", lambda: True)
    monkeypatch.setattr(vision.time, "sleep", lambda s: None)
    assert vision.describe(b"img") == "Rasmda ot bor"


def test_vision_does_not_wait_on_quota(monkeypatch):
    calls = []
    monkeypatch.setattr(vision, "_try_models", lambda body: calls.append(1) or (None, "m: HTTP 429", False))
    monkeypatch.setattr(vision, "available", lambda: True)
    monkeypatch.setattr(vision.time, "sleep", lambda s: None)
    with pytest.raises(vision.VisionError):
        vision.describe(b"img")
    assert len(calls) == 1
