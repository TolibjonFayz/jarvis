import os
import time
import asyncio
import logging


from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

import config
import fmt
import memory
import agent
import moderation
import nsfw
import security
import tools as jtools
import userbot
import vision
import voice

STARTED_AT = time.time()

# Kutilayotgan CAPTCHA'lar: (chat_id, user_id) -> {msg_id, job}
PENDING_CAPTCHAS = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("jarvis")

# Keraksiz shovqinni o'chiramiz — faqat FRIDAY log'lari va haqiqiy muammolar qolsin.
for _noisy in ("httpx", "httpcore", "apscheduler", "telethon", "telegram.ext.Application"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def _authorized(update: Update) -> bool:
    """Faqat egasi (OWNER_ID) bot bilan gaplasha oladi."""
    if config.OWNER_ID == 0:
        return True
    return bool(update.effective_user and update.effective_user.id == config.OWNER_ID)


async def _send_md(bot, chat_id, text, reply_to=None):
    """Model javobini (Markdown) Telegram HTML qilib yuboradi, uzunini bo'laklaydi.
    HTML'ni Telegram rad etsa — belgilarsiz oddiy matn."""
    for chunk in fmt.split(text) or ["(javob bo'sh chiqdi)"]:
        try:
            await bot.send_message(
                chat_id, fmt.to_html(chunk), parse_mode=ParseMode.HTML,
                reply_to_message_id=reply_to, disable_web_page_preview=True,
            )
        except BadRequest:
            await bot.send_message(chat_id, fmt.to_plain(chunk), reply_to_message_id=reply_to)


async def _respond(context, chat_id, *args):
    """agent.respond ni fonda ishlatadi va shu vaqt davomida "yozmoqda..." ni ushlab
    turadi (Telegram uni ~5s da o'chiradi; limitni kutish 20s gacha cho'zilishi mumkin)."""
    async def keep_typing():
        while True:
            try:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except Exception:
                pass
            await asyncio.sleep(4)

    typing = asyncio.create_task(keep_typing())
    try:
        return await asyncio.to_thread(agent.respond, chat_id, *args)
    finally:
        typing.cancel()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(
        "Salom bro! Men FRIDAY — shaxsiy AI yordamching.\n"
        "Kod yozaman, fikr aytaman, fayllar bilan ishlayman.\n"
        "/dayjest — kanallar xulosasi · /javobsiz — kim javob kutyapti · /hafta — haftalik hisobot\n"
        "/status — holat, tokenlar · /zaxira — baza nusxasi · /reset — suhbatni tozalash\n"
        "/pc — kompyuter holati va boshqaruvi · /ekran — ekran rasmi\n"
        "/xato — oxirgi javob noto'g'ri bo'lsa belgilash (masalan: /xato sanani adashtirdi)"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    up = int(time.time() - STARTED_AT)
    d, rem = divmod(up, 86400)
    h, m = divmod(rem // 60, 60)
    uptime = (f"{d} kun " if d else "") + f"{h} soat {m} daqiqa"

    lines = ["🤖 **FRIDAY holati**", f"⏱ Ishlayapti: {uptime}"]
    used = await asyncio.to_thread(memory.usage_since, 24)
    lines.append("\n**Tokenlar** (oxirgi 24 soat)")
    for mdl in agent.MODEL_CHAIN:
        t = used.get(mdl, 0)
        limit = agent.DAILY_TOKEN_LIMITS.get(mdl)
        short = mdl.split("/")[-1]
        rl = agent.STATS["rate_limited"].get(mdl, 0)
        extra = f" · limitga urildi {rl}×" if rl else ""
        if limit:
            pct = round(t * 100 / limit)
            lines.append(f"• `{short}` {t // 1000}K / {limit // 1000}K\n  {jtools._bar(pct)} {pct}%{extra}")
        else:
            lines.append(f"• `{short}` {t // 1000}K{extra}")
    gem = sum(v for k, v in used.items() if k.startswith("gemini:"))
    if gem:
        lines.append(f"• `gemini` (rasm) {gem // 1000}K")

    c = await asyncio.to_thread(memory.status_counts, chat_id)
    lines += [
        "\n**Ma'lumotlar**",
        f"🧠 Xotirada: {c['memories']} ta fakt",
        f"⏰ Kutilayotgan eslatma: {c['reminders']} · takroriy: {c['recurring']} · yillik sana: {c['dates']}",
        f"✅ Ochiq vazifa: {c['todos']}",
        f"💸 Bugun sarflandi: {jtools._som(c['spent_today'])}",
        f"👤 Userbot: {'ulangan' if config.TG_API_ID else 'sozlanmagan'}",
    ]
    await _send_md(context.bot, chat_id, "\n".join(lines))


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    memory.clear_history(update.effective_chat.id)
    await update.message.reply_text("Suhbat tozalandi. Toza varaqdan boshladik.")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        await update.message.reply_text("Kechirasiz, bu shaxsiy bot.")
        return

    chat_id = update.effective_chat.id
    text = update.message.text
    # "status" (slashsiz) model'ga borib, o'zidan aralash javob to'qirdi — buyruqqa bog'laymiz.
    alias = WORD_COMMANDS.get(text.strip().lower().strip("!?. "))
    if alias and update.message.forward_origin is None:
        await alias(update, context)
        return
    if update.message.forward_origin is not None:
        await _offer_forward_actions(update, chat_id, text)
        return
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        # agent.respond sinxron (tarmoq chaqiruvi) — event loop'ni bloklamaslik uchun
        # alohida oqimda ishga tushiramiz.
        reply = await _respond(context, chat_id, text)
    except Exception as e:
        log.exception("Javob berishda xato")
        s = str(e).lower()
        if "429" in s or "rate_limit" in s or "too many requests" in s:
            if "per day" in s:
                reply = (
                    "⏳ Groq'ning bugungi tekin limiti tugadi (hamma modellarda). "
                    "Ertalab (Toshkent ~05:00) tiklanadi."
                )
            else:
                reply = "⏳ Hamma modellar band edi (daqiqalik limit). ~1 daqiqadan keyin qayta yoz, bro."
        else:
            reply = f"Xato yuz berdi: {e}"

    await _send_md(context.bot, chat_id, reply)

    await _show_pending_sends(update, chat_id)


async def _show_pending_sends(update: Update, chat_id):
    """Tayyorlangan (hali yuborilmagan) Telegram xabarlar uchun tasdiq tugmalari
    va tool navbatga qo'ygan fayllar (ekran rasmi)."""
    for item in [f for f in jtools.PENDING_FILES if f["chat_id"] == chat_id]:
        jtools.PENDING_FILES.remove(item)
        try:
            with open(item["path"], "rb") as fh:
                await update.effective_message.reply_photo(fh, caption=item["caption"])
        finally:
            try:
                os.remove(item["path"])
            except OSError:
                pass
    for sid, p in list(jtools.PENDING_SENDS.items()):
        if p["chat_id"] != chat_id or p["shown"]:
            continue
        p["shown"] = True
        kind = p.get("kind", "send")
        yes_label, text = {
            "leave": ("🚪 Chiqish", f"🚪 {p['to_name']} — chiqilsinmi?"),
            "gcal_delete": ("🗑 O'chirish", f"🗑 Kalendardan o'chirilsinmi?\n{p['to_name']}"),
            "pc_power": (p["to_name"], f"{p['to_name']} — rostdan ham? (FRIDAY ham to'xtaydi)"),
        }.get(kind, (
            "✅ Yuborish",
            f"📨 Qabul qiluvchi: {p['to_name']}\n\n\"{p['text']}\"\n\nYuborilsinmi?",
        ))
        kb = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton(yes_label, callback_data=f"tgy:{sid}"),
                InlineKeyboardButton("❌ Bekor", callback_data=f"tgn:{sid}"),
            ]]
        )
        await update.effective_message.reply_text(text, reply_markup=kb)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shaxsiy chatga tashlangan hujjatni (PDF/DOCX/txt) o'qib xulosa qiladi."""
    if not _authorized(update):
        return
    msg = update.effective_message
    doc = msg.document
    if not doc:
        return
    chat_id = update.effective_chat.id
    if (doc.file_size or 0) > 20 * 1024 * 1024:
        await msg.reply_text("Hujjat juda katta (20MB dan oshmasin).")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    import tempfile as _tf
    ext = os.path.splitext(doc.file_name or "")[1] or ".bin"
    tmp = os.path.join(_tf.gettempdir(), f"doc_{chat_id}_{msg.message_id}{ext}")
    try:
        f = await context.bot.get_file(doc.file_id)
        await f.download_to_drive(tmp)
        text = await asyncio.to_thread(
            jtools.extract_document_text, tmp, doc.file_name or "", doc.mime_type or ""
        )
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass

    if not text or text.startswith("__XATO__") or not text.strip():
        await msg.reply_text(
            "📄 Hujjatdan matn chiqmadi (rasm-skan yoki qo'llab-quvvatlanmaydigan format)."
        )
        return

    await msg.reply_text(f"📄 «{doc.file_name}» o'qildi ({len(text)} belgi). Xulosa qilyapman...")
    prompt = (
        f"Quyidagi hujjatni ({doc.file_name}) o'qidim. Qisqacha mazmuni va asosiy "
        f"nuqtalarini o'zbekcha, aniq ayt:\n\n{text[:5000]}"
    )
    try:
        reply = await _respond(context, chat_id, prompt)
    except Exception as e:
        s = str(e).lower()
        if "429" in s or "rate_limit" in s or "too many requests" in s:
            reply = "⏳ Groq chegarasi urildi. ~1 daqiqa kutib qayta yuboring."
        else:
            reply = f"Xato yuz berdi: {e}"
    await _send_md(context.bot, chat_id, reply)


MEDIA_MAX_MB = 15  # Gemini inline so'rov chegarasi ~20MB


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rasm va video: Gemini FAQAT media+izohni ko'radi, javobni Groq'dagi agent yozadi
    (shaxsiy kontekst — xotira, tarix — Gemini'ga bormaydi). Avval video hujjat
    sifatida kelib, matn deb o'qilardi ("binar faylni o'qiy olmayman")."""
    if not _authorized(update):
        return
    msg = update.effective_message
    chat_id = update.effective_chat.id
    if msg.photo:
        media, mime = msg.photo[-1], "image/jpeg"  # eng katta o'lcham
    elif msg.video or msg.video_note or msg.animation:
        media = msg.video or msg.video_note or msg.animation
        mime = getattr(media, "mime_type", None) or "video/mp4"
    else:
        media, mime = msg.document, msg.document.mime_type or "image/jpeg"
    is_video = mime.startswith("video/")
    kind = "video" if is_video else "rasm"
    if not vision.available():
        await msg.reply_text(f"🖼 {kind.capitalize()} ko'rish uchun .env ga GEMINI_API_KEY qo'yish kerak.")
        return
    if (media.file_size or 0) > MEDIA_MAX_MB * 1024 * 1024:
        await msg.reply_text(f"{kind.capitalize()} juda katta ({MEDIA_MAX_MB}MB dan oshmasin).")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    note = (msg.caption or "").strip()
    f = await context.bot.get_file(media.file_id)
    data = bytes(await f.download_as_bytearray())
    try:
        desc = await asyncio.to_thread(vision.describe, data, mime, note)
    except vision.VisionError as e:
        log.warning("%s ko'rilmadi: %s", kind, e)
        await msg.reply_text(
            f"🖼 {kind.capitalize()}ni hozir ko'ra olmadim (Gemini limiti yoki band). Keyinroq qayta yubor."
        )
        return

    # Izohsiz: qisqa javob — avval tavsifni qayta sanab chiqib, o'zidan xulosa qo'shardi.
    default = (
        f"{kind.capitalize()}da nima borligini 2-3 gapda ayt. Tavsifni qayta sanab chiqma, "
        "unda yo'q narsani qo'shma."
    )
    prompt = (
        f"[Egang {kind} yubordi. Avtomatik tavsif:\n{desc[:3000]}]\n\n" + (note or default)
    )
    try:
        reply = await _respond(context, chat_id, prompt, note)
    except Exception as e:
        log.exception("Javob berishda xato (rasm)")
        reply = f"Rasmdagi narsa:\n\n{desc}\n\n(izoh yozishda xato: {e})"
    await _send_md(context.bot, chat_id, reply)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ovozli xabar: Whisper bilan tushunadi, FRIDAY javobini matn + OVOZ bilan beradi."""
    if not _authorized(update):
        return
    msg = update.effective_message
    media = msg.voice or msg.audio
    if not media:
        return
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    import tempfile as _tf
    ogg = os.path.join(_tf.gettempdir(), f"jv_in_{chat_id}_{msg.message_id}.ogg")
    mp3 = os.path.join(_tf.gettempdir(), f"jv_out_{chat_id}_{msg.message_id}.mp3")
    try:
        f = await context.bot.get_file(media.file_id)
        await f.download_to_drive(ogg)
        try:
            text = await asyncio.to_thread(voice.transcribe, ogg)
        except Exception as e:
            log.exception("STT xatosi")
            s = str(e).lower()
            if "429" in s or "rate_limit" in s:
                await msg.reply_text("⏳ Ovoz tanish chegarasi urildi — 1 daqiqa kutib qayta yuboring.")
            else:
                await msg.reply_text(f"Ovozni tushunolmadim: {e}")
            return
        if not text:
            await msg.reply_text("🎤 Ovozdan matn chiqmadi — qayta urinib ko'ring.")
            return

        await msg.reply_text(f"🎤 «{text}»")
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        try:
            reply = await _respond(context, chat_id, text)
        except Exception as e:
            log.exception("Javob berishda xato (ovoz)")
            s = str(e).lower()
            if "429" in s or "rate_limit" in s or "too many requests" in s:
                reply = "⏳ Groq tekin chegarasi urildi. ~1 daqiqa kutib qayta urinib ko'ring."
            else:
                reply = f"Xato yuz berdi: {e}"

        await _send_md(context.bot, chat_id, reply)
        await _show_pending_sends(update, chat_id)

        # Javobni ovoz bilan ham yuboramiz (kod/link olib tashlangan qismini).
        if config.VOICE_REPLY:
            speak = voice.speakable(reply)
            if speak:
                try:
                    await context.bot.send_chat_action(
                        chat_id=chat_id, action=ChatAction.RECORD_VOICE
                    )
                    await voice.tts(speak, mp3)
                    with open(mp3, "rb") as vf:
                        await msg.reply_voice(vf)
                except Exception:
                    log.warning("TTS ishlamadi — matn bilan cheklandik")
    finally:
        for p in (ogg, mp3):
            try:
                os.remove(p)
            except Exception:
                pass


_UNMUTE = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
)


# --- Kompyuter boshqaruvi (/pc, /ekran, pc:* tugmalar) ---

def _pc_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Ekran", callback_data="pc:screen"),
         InlineKeyboardButton("🔒 Qulfla", callback_data="pc:lock"),
         InlineKeyboardButton("🔄 Yangila", callback_data="pc:status")],
        [InlineKeyboardButton("😴 Uxlat", callback_data="pc:ask:sleep"),
         InlineKeyboardButton("⏻ O'chir", callback_data="pc:ask:shutdown"),
         InlineKeyboardButton("🔁 Restart", callback_data="pc:ask:restart")],
    ])


async def cmd_pc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    import pc
    text = await asyncio.to_thread(pc.status_text)
    await update.effective_message.reply_text(
        fmt.to_html(text), parse_mode=ParseMode.HTML, reply_markup=_pc_keyboard()
    )


async def _send_screenshot(message):
    import pc
    path, black = await asyncio.to_thread(pc.screenshot)
    try:
        if black:
            await message.reply_text("🖥 Ekran qora — kompyuter qulflangan yoki monitor uxlagan.")
        else:
            with open(path, "rb") as fh:
                await message.reply_photo(fh, caption="🖥 Kompyuter ekrani")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


async def cmd_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/buyruqlar — ruxsat berilgan buyruqlar va ishlab turgan serverlar (modelsiz)."""
    if not _authorized(update):
        return
    import commands
    text = await asyncio.to_thread(commands.list_text)
    await _send_md(context.bot, update.effective_chat.id, text)


async def cmd_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/city — Man City: keyingi o'yinlar, jadval va oxirgi natija (modelsiz)."""
    if not _authorized(update):
        return
    import football

    def build():
        parts = [football.fixtures_text()]
        try:
            parts.append(football.result_text(football.results()[0]))
        except Exception:
            pass
        return "\n\n".join(parts)
    await _send_md(context.bot, update.effective_chat.id, await asyncio.to_thread(build))


async def football_job(context: ContextTypes.DEFAULT_TYPE):
    """Man City: o'yin kuni / 1 soat oldin / natija (10 daqiqada) + jiddiy yangiliklar (2 soatda)."""
    import football
    owner = config.OWNER_ID
    if not owner or memory.get_setting(owner, "football", "0") != "1":
        return
    try:
        msgs = await asyncio.to_thread(football.match_alerts, owner)
        if football.news_due(owner):
            football.mark_news_checked(owner)
            try:
                msgs += await asyncio.to_thread(football.serious_news, owner)
            except Exception as e:
                log.warning("Futbol yangiliklari xatosi: %s", str(e)[:150])
    except Exception as e:
        log.warning("Futbol xatosi: %s", str(e)[:150])
        return
    for text in msgs:
        try:
            await _send_md(context.bot, owner, text)
        except Exception:
            log.warning("Futbol xabari yuborilmadi")


async def cmd_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sanalar — tug'ilgan kunlar va yillik sanalar (modelsiz)."""
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    text = await asyncio.to_thread(jtools.dates_text, chat_id)
    await _send_md(context.bot, chat_id, text)


async def cmd_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO)
    await _send_screenshot(update.effective_message)


async def _run_power(q, action):
    """Tasdiqlangan quvvat amali; o'chirish/restartga «Bekor qilish» tugmasi."""
    import pc
    try:
        result = await asyncio.to_thread(pc.power, action)
    except Exception as e:
        log.exception("Quvvat amalida xato")
        await q.edit_message_text(f"Xato: bajarilmadi — {e}")
        return
    log.info("Quvvat amali bajarildi: %s", action)
    kb = None
    if action in ("shutdown", "restart"):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="pc:cancel")]])
    await q.edit_message_text(result, reply_markup=kb)


async def _on_pc_button(update: Update, context: ContextTypes.DEFAULT_TYPE, data):
    import pc
    q = update.callback_query
    parts = data.split(":")
    cmd = parts[1]
    if cmd == "screen":
        await q.answer("📸")
        await _send_screenshot(q.message)
    elif cmd == "lock":
        await asyncio.to_thread(pc.lock)
        await q.answer("🔒 Qulflandi")
    elif cmd == "status":
        text = await asyncio.to_thread(pc.status_text)
        await q.answer()
        try:
            await q.edit_message_text(fmt.to_html(text), parse_mode=ParseMode.HTML, reply_markup=_pc_keyboard())
        except BadRequest:
            pass  # o'zgarmagan bo'lsa Telegram rad etadi
    elif cmd == "ask" and len(parts) == 3 and parts[2] in pc.POWER_LABELS:
        action = parts[2]
        await q.answer()
        await q.message.reply_text(
            f"{pc.POWER_LABELS[action]} — rostdan ham? (FRIDAY ham to'xtaydi)",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(pc.POWER_LABELS[action], callback_data=f"pc:do:{action}"),
                InlineKeyboardButton("❌ Bekor", callback_data="pc:no"),
            ]]),
        )
    elif cmd == "do" and len(parts) == 3 and parts[2] in pc.POWER_LABELS:
        await q.answer()
        await _run_power(q, parts[2])
    elif cmd == "no":
        await q.answer()
        await q.edit_message_text("❌ Bekor qilindi — kompyuter tegilmadi.")
    elif cmd == "cancel":
        result = await asyncio.to_thread(pc.cancel_power)
        await q.answer()
        await q.edit_message_text(result)
    else:
        await q.answer()


def _forward_keyboard(sid):
    import forward
    item = forward.PENDING.get(sid) or {"text": "", "done": set()}
    order = forward.suggest(item["text"])
    buttons = [
        InlineKeyboardButton(
            ("✔ " if a in item["done"] else "⭐ " if i == 0 else "") + forward.ACTIONS[a],
            callback_data=f"fw:{a}:{sid}",
        )
        for i, a in enumerate(order)
    ]
    return InlineKeyboardMarkup([buttons[:3], buttons[3:]])


async def _offer_forward_actions(update: Update, chat_id, text):
    """Forward qilingan xabar: model chaqirilmaydi — avval egasi nima qilishni tanlaydi."""
    import forward
    origin = update.message.forward_origin
    sender = forward.sender_name(origin)
    sid = forward.add(chat_id, text, sender, getattr(origin, "date", None))
    await update.message.reply_text(
        fmt.to_html(forward.preview(text, sender)),
        parse_mode=ParseMode.HTML,
        reply_markup=_forward_keyboard(sid),
    )


async def _on_forward_button(update: Update, context: ContextTypes.DEFAULT_TYPE, data):
    import forward
    q = update.callback_query
    _, action, sid_s = data.split(":", 2)
    sid = int(sid_s)
    await q.answer(f"{forward.ACTIONS.get(action, '')}…")
    chat_id = update.effective_chat.id

    async def keep_typing():
        while True:
            try:
                await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except Exception:
                pass
            await asyncio.sleep(4)

    typing = asyncio.create_task(keep_typing())
    try:
        out = await asyncio.to_thread(forward.run, sid, action)
    except Exception as e:
        log.exception("Forward amalida xato")
        out = f"Xato: {e}"
    finally:
        typing.cancel()
    await _send_md(context.bot, chat_id, out)
    await _show_pending_sends(update, chat_id)
    if sid in forward.PENDING:
        try:
            await q.edit_message_reply_markup(reply_markup=_forward_keyboard(sid))
        except Exception:
            pass


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline tugmalar: CAPTCHA tasdig'i (yangi a'zo), forward amallari va tasdiqlar (egasi)."""
    q = update.callback_query
    data = q.data or ""

    if data.startswith("fw:"):
        if not _authorized(update):
            await q.answer()
            return
        await _on_forward_button(update, context, data)
        return

    if data.startswith("pc:"):
        if not _authorized(update):
            await q.answer()
            return
        await _on_pc_button(update, context, data)
        return

    # --- Kirish CAPTCHA: tugmani yangi a'zoning O'ZI bosishi kerak ---
    if data.startswith("cap:"):
        try:
            _, chat_s, uid_s = data.split(":", 2)
            chat_id, uid = int(chat_s), int(uid_s)
        except ValueError:
            await q.answer()
            return
        if q.from_user.id != uid:
            await q.answer("Bu tugma sizga emas.", show_alert=True)
            return
        await q.answer("Tasdiqlandi ✅")
        pend = PENDING_CAPTCHAS.pop((chat_id, uid), None)
        if pend and pend.get("job"):
            try:
                pend["job"].schedule_removal()
            except Exception:
                pass
        try:
            await context.bot.restrict_chat_member(chat_id, uid, permissions=_UNMUTE)
        except Exception:
            log.warning("CAPTCHA: ovozini qaytara olmadim")
        try:
            await q.edit_message_text(f"✅ {q.from_user.first_name} tasdiqlandi. Xush kelibsiz!")
        except Exception:
            pass
        return

    # --- Telegram xabar yuborish tasdig'i: faqat egasi ---
    await q.answer()
    if not _authorized(update):
        return

    action, _, sid_s = data.partition(":")
    try:
        sid = int(sid_s)
    except ValueError:
        return
    p = jtools.PENDING_SENDS.pop(sid, None)
    if p is None:
        await q.edit_message_text("Bu so'rov eskirgan (bot qayta ishga tushgan bo'lishi mumkin).")
        return

    kind = p.get("kind", "send")
    if action == "tgy":
        try:
            if kind == "leave":
                result = await asyncio.to_thread(userbot.leave_chat, p["to_id"])
            elif kind == "gcal_delete":
                import gcal
                await asyncio.to_thread(gcal.delete_event, p["to_id"])
                result = f"Kalendardan o'chirildi: {p['to_name']}"
            elif kind == "pc_power":
                await _run_power(q, p["to_id"])
                return
            else:
                result = await asyncio.to_thread(userbot.send_message, p["to_id"], p["text"])
            await q.edit_message_text(f"✅ {result}")
        except Exception as e:
            log.exception("Tasdiqlangan amalda xato")
            await q.edit_message_text(f"Xato: bajarilmadi — {e}")
    else:
        await q.edit_message_text({
            "leave": f"❌ Bekor qilindi ({p['to_name']} da qolding).",
            "gcal_delete": f"❌ Bekor qilindi (tadbir o'chirilmadi).",
            "pc_power": "❌ Bekor qilindi — kompyuter tegilmadi.",
        }.get(kind, f"❌ Bekor qilindi ({p['to_name']} ga yuborilmadi)."))


async def _admin_exempt(context, chat_id, user):
    """Admin/creator himoyasi (test rejimida o'chadi). Faqat bayroqda chaqiriladi."""
    if config.MOD_TEST_MODE:
        return False
    try:
        m = await context.bot.get_chat_member(chat_id, user.id)
        return m.status in ("administrator", "creator")
    except Exception:
        return False


async def _moderate(context, msg, user, reason):
    """Buzilgan xabarni o'chiradi, ogohlantiradi, limitdan oshsa chiqaradi."""
    try:
        await msg.delete()
    except Exception:
        log.warning("Xabarni o'chira olmadim — bot guruhda admin emasga o'xshaydi")
        return
    await _warn_or_ban(context, msg.chat_id, user, reason)


async def _warn_or_ban(context, chat_id, user, reason):
    n = memory.add_warn(chat_id, user.id)
    name = user.mention_html()
    try:
        if n > config.MOD_WARN_LIMIT:
            await context.bot.ban_chat_member(chat_id, user.id)
            memory.reset_warns(chat_id, user.id)
            await context.bot.send_message(
                chat_id,
                f"🚫 {name} guruhdan chiqarildi.\n"
                f"Sabab: {reason} — {config.MOD_WARN_LIMIT} ta ogohlantirishdan "
                "keyin ham davom etdi. Guruhda hurmat saqlanadi.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await context.bot.send_message(
                chat_id,
                f"⚠️ {name}, xabaringiz o'chirildi.\n"
                f"Sabab: {reason}. Ogohlantirish: {n}/{config.MOD_WARN_LIMIT}. "
                "Yana takrorlansa guruhdan chiqarilasiz.",
                parse_mode=ParseMode.HTML,
            )
    except Exception:
        log.exception("Moderatsiya xabari/ban ishlamadi (huquq yetarlimi?)")


def _media_file_id(msg):
    """Tekshirish uchun rasm file_id + kengaytma. Video/animatsiya -> thumbnail."""
    if msg.photo:
        return msg.photo[-1].file_id, ".jpg"
    if msg.video and msg.video.thumbnail:
        return msg.video.thumbnail.file_id, ".jpg"
    if msg.animation and msg.animation.thumbnail:
        return msg.animation.thumbnail.file_id, ".jpg"
    if msg.sticker:
        if not msg.sticker.is_animated and not msg.sticker.is_video:
            return msg.sticker.file_id, ".webp"
        if msg.sticker.thumbnail:
            return msg.sticker.thumbnail.file_id, ".jpg"
    if msg.document:
        mt = msg.document.mime_type or ""
        if mt.startswith("image/"):
            return msg.document.file_id, ".jpg"
        if mt.startswith("video/") and msg.document.thumbnail:
            return msg.document.thumbnail.file_id, ".jpg"
    return None, None


async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Matn moderatsiyasi: so'kinish/haqorat. Guruh xabarlari FRIDAY'ga BORMAYDI."""
    msg = update.effective_message
    if not msg or not msg.text or not msg.from_user:
        return
    user = msg.from_user
    log.info("GURUH matn [%s]: %s: %s", msg.chat_id, user.first_name, msg.text)

    if user.id == config.OWNER_ID and not config.MOD_TEST_MODE:
        log.info("  -> egasi (OWNER), o'tkazib yuborildi. Sinash uchun MOD_TEST_MODE=1")
        return

    reason = ""
    # 1) Xavfli link (tez, lokal)
    if config.MOD_LINKS:
        bad_l, r_l = security.find_dangerous_links(msg.text)
        if bad_l:
            reason = r_l
    # 2) So'kinish/haqorat
    if not reason:
        bad, r = await asyncio.to_thread(moderation.check_message, msg.text)
        if bad:
            reason = r

    if not reason:
        return
    if await _admin_exempt(context, msg.chat_id, user):
        return
    await _moderate(context, msg, user, reason)


async def on_group_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rasm/video/sticker moderatsiyasi: 18+ kontent + caption so'kinishlari."""
    msg = update.effective_message
    if not msg or not msg.from_user:
        return
    user = msg.from_user
    if user.id == config.OWNER_ID and not config.MOD_TEST_MODE:
        return

    reason = ""
    # 1) Caption (rasm ostidagi yozuv) so'kinishли bo'lishi mumkin.
    if msg.caption:
        bad_c, r_c = await asyncio.to_thread(moderation.check_message, msg.caption)
        if bad_c:
            reason = r_c
    # 2) Muqova/rasm NSFW tekshiruvi (lokal NudeNet) — barcha media uchun tez.
    if not reason:
        fid, suffix = _media_file_id(msg)
        if fid:
            try:
                f = await context.bot.get_file(fid)
                data = bytes(await f.download_as_bytearray())
                bad_n, r_n = await asyncio.to_thread(nsfw.is_nsfw_bytes, data, suffix)
                if bad_n:
                    reason = r_n
                    log.info("NSFW aniqlandi [%s]: %s", msg.chat_id, user.first_name)
            except Exception:
                log.warning("Media yuklab/tekshirib bo'lmadi — o'tkazib yuborildi")
    # 3) Video chuqur tekshiruvi: muqova toza bo'lsa ham kadrlarni namunalaymiz.
    if not reason and (msg.video or (msg.document and (msg.document.mime_type or "").startswith("video/"))):
        reason = await _deep_video_scan(msg)

    if not reason:
        return
    if await _admin_exempt(context, msg.chat_id, user):
        return
    await _moderate(context, msg, user, reason)


async def _deep_video_scan(msg):
    """Video: userbot bilan yuklab, kadrlar namunasini tekshiradi.
    Tekshirib bo'lmasa (katta/yuklanmadi) MOD_BLOCK_BIG_VIDEO bo'yicha choralanadi."""
    vid = msg.video or msg.document
    size = getattr(vid, "file_size", 0) or 0
    limit = config.MOD_VIDEO_MAX_MB * 1024 * 1024

    def _unverified(why):
        """Tekshirib bo'lmagan video: qattiq siyosatда o'chiradi, aks holda o'tkazadi."""
        if config.MOD_BLOCK_BIG_VIDEO:
            log.info("Video tekshirib bo'lmadi (%s) — QATTIQ siyosat: o'chiriladi", why)
            return "tekshirib bo'lmaydigan video (18+ ehtimoli)"
        log.info("Video tekshirib bo'lmadi (%s) — muqova bilan cheklandik", why)
        return ""

    if size == 0 or size > limit:
        return _unverified(f"{size // 1024 // 1024 if size else '?'} MB, chegara {config.MOD_VIDEO_MAX_MB}")

    if not userbot._ensure_started():
        return _unverified("userbot ulanmagan")

    mb = size // 1024 // 1024
    log.info("Video chuqur skaner boshlandi (%s MB) — yuklanmoqda...", mb)
    import tempfile as _tf
    dest = os.path.join(_tf.gettempdir(), f"vid_{msg.chat_id}_{msg.message_id}.mp4")
    path = await asyncio.to_thread(
        userbot.download_media, msg.chat_id, msg.message_id, dest
    )
    if not path:
        return _unverified("yuklab bo'lmadi")
    try:
        bad, r = await asyncio.to_thread(nsfw.is_nsfw_video, path)
        if bad:
            log.info("NSFW video ANIQLANDI [%s]", msg.chat_id)
            return r
        log.info("Video tekshirildi — toza (kadr namunasi)")
        return ""
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


async def _profile_is_nsfw(context, user_id):
    """Foydalanuvchi profil rasmi 18+ mi?"""
    try:
        photos = await context.bot.get_user_profile_photos(user_id, limit=1)
        if not photos.total_count:
            return False
        ph = photos.photos[0][-1]
        f = await context.bot.get_file(ph.file_id)
        data = bytes(await f.download_as_bytearray())
    except Exception:
        return False
    bad, _ = await asyncio.to_thread(nsfw.is_nsfw_bytes, data, ".jpg")
    return bad


async def _kick(context, chat_id, user_id):
    """Guruhdan chiqaradi (ban qilib, darrov unban — qayta kira olsin)."""
    try:
        await context.bot.ban_chat_member(chat_id, user_id)
        await context.bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
    except Exception:
        log.exception("Kick ishlamadi (huquq yetarlimi?)")


async def _captcha_kick_job(context: ContextTypes.DEFAULT_TYPE):
    """Muddat tugadi — tasdiqlamagan a'zoni chiqaradi."""
    chat_id, user_id, name = context.job.data
    pend = PENDING_CAPTCHAS.pop((chat_id, user_id), None)
    if not pend:
        return  # allaqachon tasdiqlagan
    await _kick(context, chat_id, user_id)
    try:
        await context.bot.delete_message(chat_id, pend["msg_id"])
    except Exception:
        pass
    try:
        await context.bot.send_message(
            chat_id,
            f"⏳ {name} vaqtida tasdiqlamadi — chiqarildi (bot himoyasi).",
        )
    except Exception:
        pass


async def _start_captcha(context, chat_id, member):
    """Yangi a'zoni ovozini o'chirib, tasdiq tugmasini chiqaradi."""
    try:
        await context.bot.restrict_chat_member(
            chat_id, member.id,
            permissions=ChatPermissions(can_send_messages=False),
        )
    except Exception:
        log.warning("CAPTCHA: ovozini o'chira olmadim — bot 'restrict' huquqi yo'q?")
        return

    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Men odamman", callback_data=f"cap:{chat_id}:{member.id}")]]
    )
    try:
        sent = await context.bot.send_message(
            chat_id,
            f"👋 {member.mention_html()}, guruhga xush kelibsiz!\n"
            f"Yozish uchun {config.MOD_CAPTCHA_SEC} soniya ichida pastdagi tugmani bosing.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
        )
    except Exception:
        return

    if not context.job_queue:
        return
    job = context.job_queue.run_once(
        _captcha_kick_job,
        when=config.MOD_CAPTCHA_SEC,
        data=(chat_id, member.id, member.first_name),
        name=f"cap_{chat_id}_{member.id}",
    )
    PENDING_CAPTCHAS[(chat_id, member.id)] = {"msg_id": sent.message_id, "job": job}


async def on_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yangi a'zo: CAS spamer bazasi + 18+ profil rasm + kirish CAPTCHA."""
    msg = update.effective_message
    if not msg or not msg.new_chat_members:
        return
    for member in msg.new_chat_members:
        if member.is_bot or member.id == config.OWNER_ID:
            continue

        # 1) CAS — ma'lum spamer bazasi
        if config.MOD_CAS and await asyncio.to_thread(security.is_cas_banned, member.id):
            log.info("Yangi a'zo CAS spamer [%s]: %s", msg.chat_id, member.first_name)
            await _kick(context, msg.chat_id, member.id)
            try:
                await context.bot.send_message(
                    msg.chat_id,
                    f"🚫 {member.mention_html()} chiqarildi (ma'lum spamer — CAS bazasi).",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            continue

        # 2) Profil rasmi 18+
        if await _profile_is_nsfw(context, member.id):
            log.info("Yangi a'zo 18+ profil rasm [%s]: %s", msg.chat_id, member.first_name)
            await _kick(context, msg.chat_id, member.id)
            try:
                await context.bot.send_message(
                    msg.chat_id,
                    f"🚫 {member.mention_html()} chiqarildi (18+ profil rasmi).",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            continue

        # 3) Kirish CAPTCHA (odam ekanini isbotlash)
        if config.MOD_CAPTCHA:
            await _start_captcha(context, msg.chat_id, member)




async def daily_prayers_job(context: ContextTypes.DEFAULT_TYPE):
    """Har 10 daqiqada: bugungi namoz eslatmalari hali qo'yilmagan bo'lsa — qo'yadi.
    (Avval run_daily 00:10 edi — kompyuter yarim tunda o'chiq bo'lsa, kun eslatmasiz
    qolardi. O'tib ketgan vaqtlar set_prayer_reminders_for'da o'tkazib yuboriladi.)"""
    from datetime import date as _date
    today = _date.today().isoformat()
    for chat_id in memory.settings_where("auto_prayer", "1"):
        if memory.get_setting(chat_id, "prayer_day") == today:
            continue
        city = memory.get_setting(chat_id, "prayer_city", "Tashkent")
        try:
            await asyncio.to_thread(jtools.set_prayer_reminders_for, chat_id, city, 0)
            memory.set_setting(chat_id, "prayer_day", today)
            log.info("Avto-namoz qo'yildi [%s] %s", chat_id, city)
        except Exception:
            log.warning("Avto-namoz xatosi [%s] — 10 daqiqadan keyin qayta", chat_id)


UNANSWERED_ALERT_HOURS = (12, 19)


async def digest_job(context: ContextTypes.DEFAULT_TYPE):
    """Har 10 daqiqada: dayjest soati o'tgan va bugun yuborilmagan bo'lsa — yuboradi.
    (run_daily emas: bot o'sha soatda o'chiq bo'lsa ham, yoqilganda yetkazadi.)"""
    from datetime import datetime as _dt
    import digest
    now = _dt.now()
    today = now.strftime("%Y-%m-%d")
    for chat_id in memory.settings_where("digest", "1"):
        hour = int(memory.get_setting(chat_id, "digest_hour", "21"))
        if now.hour < hour or memory.get_setting(chat_id, "digest_last") == today:
            continue
        # Avval belgilaymiz — xato bo'lsa har 10 daqiqada qayta urinib spam qilmasin.
        memory.set_setting(chat_id, "digest_last", today)
        try:
            text = await asyncio.to_thread(digest.build_digest, chat_id)
            await _send_md(context.bot, chat_id, text)
            log.info("Dayjest yuborildi [%s]", chat_id)
        except Exception as e:
            log.warning("Dayjest xatosi [%s]: %s", chat_id, e)


async def unanswered_job(context: ContextTypes.DEFAULT_TYPE):
    """12:00 va 19:00 (o'tkazib yuborilgan bo'lsa — keyinroq): javobsizlar ro'yxati.
    Hamma javob berilgan bo'lsa jim turadi."""
    from datetime import datetime as _dt
    import digest
    now = _dt.now()
    slots = [h for h in UNANSWERED_ALERT_HOURS if now.hour >= h]
    if not slots:
        return
    slot = f"{now:%Y-%m-%d}-{slots[-1]}"
    for chat_id in memory.settings_where("unanswered_alerts", "1"):
        if memory.get_setting(chat_id, "unanswered_slot") == slot:
            continue
        memory.set_setting(chat_id, "unanswered_slot", slot)
        try:
            text = await asyncio.to_thread(digest.unanswered_text)
            if text:
                await _send_md(context.bot, chat_id, text)
        except Exception as e:
            log.warning("Javobsizlar tekshiruvi xatosi [%s]: %s", chat_id, e)


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    import digest
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    text = await asyncio.to_thread(digest.build_digest, chat_id)
    await _send_md(context.bot, chat_id, text)


async def cmd_unanswered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    import digest
    chat_id = update.effective_chat.id
    text = await asyncio.to_thread(digest.unanswered_text)
    await _send_md(context.bot, chat_id, text or "✅ Hamma shaxsiy xabarlarga javob berilgan.")


BACKUP_SEND_DAYS = (1, 4)  # seshanba, juma


async def backup_job(context: ContextTypes.DEFAULT_TYPE):
    """Har soatda: bugungi lokal nusxa bo'lmasa — yaratadi. Seshanba va juma kunlari
    kompyuter yoqilgandan keyin (06:00 dan) bir marta siqilgan bazani egasiga yuboradi.
    (Avval yakshanba 20:00 edi — o'sha payt kompyuter odatda o'chiq.)"""
    from datetime import datetime as _dt
    import backup
    try:
        path = await asyncio.to_thread(backup.daily)
    except Exception as e:
        log.warning("Zaxira nusxa olinmadi: %s", e)
        return
    now = _dt.now()
    today = now.strftime("%Y-%m-%d")
    owner = config.OWNER_ID
    if not owner or now.weekday() not in BACKUP_SEND_DAYS or now.hour < 6:
        return
    if memory.get_setting(owner, "backup_sent") == today:
        return
    try:
        zpath = await asyncio.to_thread(backup.weekly_zip)
        ok = await asyncio.to_thread(backup.integrity_ok, path)
        with open(zpath, "rb") as f:
            await context.bot.send_document(
                owner, f, filename=os.path.basename(zpath),
                caption=(
                    f"💾 Haftalik zaxira nusxa ({now:%d.%m.%Y})"
                    + ("" if ok else " ⚠️ tekshiruvdan o'tmadi!")
                    + "\nTiklash: botni to'xtat → ichidagi jarvis.db ni data/ ga qo'y → yoq."
                ),
                disable_notification=True,
            )
        os.remove(zpath)
        memory.set_setting(owner, "backup_sent", today)
        log.info("Haftalik zaxira yuborildi")
    except Exception as e:
        log.warning("Haftalik zaxira yuborilmadi: %s", e)


WEEKLY_HOUR = 6


async def weekly_job(context: ContextTypes.DEFAULT_TYPE):
    """Haftaning BIRINCHI kompyuter yoqilishida (odatda dushanba ertalab) o'tgan
    to'liq hafta hisoboti. (Avval yakshanba 20:00 edi — o'sha payt kompyuter o'chiq.)
    Egasi uchun standart yoqiq; «haftalik hisobotni o'chir» bilan o'chadi."""
    from datetime import datetime as _dt
    owner = config.OWNER_ID
    now = _dt.now()
    if not owner or now.hour < WEEKLY_HOUR:
        return
    if memory.get_setting(owner, "weekly_report", "1") != "1":
        return
    week = now.strftime("%G-W%V")
    if memory.get_setting(owner, "weekly_last") == week:
        return
    memory.set_setting(owner, "weekly_last", week)
    try:
        text = await asyncio.to_thread(jtools.weekly_report_text, owner, None, True)
        await _send_md(context.bot, owner, text)
        log.info("Haftalik hisobot yuborildi")
    except Exception as e:
        log.warning("Haftalik hisobot xatosi: %s", e)


FEEDBACK_FILE = os.path.join(config.DATA_DIR, "feedback.jsonl")


async def cmd_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/xato [izoh] — oxirgi savol-javobni tahlil uchun data/feedback.jsonl ga yozadi.
    Bir haftadan keyin shu fayl + /status + bot.log dagi tool chaqiruvlari ko'rib chiqiladi."""
    if not _authorized(update):
        return
    import json as _json
    from datetime import datetime as _dt
    chat_id = update.effective_chat.id
    hist = memory.get_history(chat_id, limit=2)
    q = next((m["content"] for m in hist if m["role"] == "user"), "")
    a = next((m["content"] for m in reversed(hist) if m["role"] == "assistant"), "")
    note = " ".join(context.args or [])
    with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
        f.write(_json.dumps({
            "ts": f"{_dt.now():%Y-%m-%d %H:%M}", "savol": q[:500], "javob": a[:800], "izoh": note,
        }, ensure_ascii=False) + "\n")
    await update.message.reply_text(
        "📝 Yozib qo'ydim — keyin tahlil qilamiz."
        + ("" if note else " (Keyingi safar sababini ham yoz: /xato sanani noto'g'ri qo'ydi)")
    )


async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    text = await asyncio.to_thread(jtools.weekly_report_text, chat_id)
    await _send_md(context.bot, chat_id, text)


async def loop_job(context: ContextTypes.DEFAULT_TYPE):
    """Musiqa takrorlash: tugashiga oz qolganda boshiga qaytaradi (nowplaying.LOOP)."""
    import nowplaying
    if not nowplaying.LOOP:
        return
    msg = await asyncio.to_thread(nowplaying.loop_tick)
    if msg and msg[0]:
        try:
            await _send_md(context.bot, msg[0], msg[1])
        except Exception:
            log.warning("Loop xabari yuborilmadi")


async def usage_job(context: ContextTypes.DEFAULT_TYPE):
    """Kuchli model kunlik limitining 80% i ishlatilsa — egasini ogohlantiradi
    (12 soatda bir martadan ko'p emas)."""
    owner = config.OWNER_ID
    if not owner:
        return
    main = agent.MODEL_CHAIN[0]
    limit = agent.DAILY_TOKEN_LIMITS.get(main)
    if not limit:
        return
    used = (await asyncio.to_thread(memory.usage_since, 24)).get(main, 0)
    pct = used * 100 / limit
    last = float(memory.get_setting(owner, "usage_warned", "0") or 0)
    if pct < 80 or time.time() - last < 12 * 3600:
        return
    memory.set_setting(owner, "usage_warned", time.time())
    await _send_md(
        context.bot, owner,
        f"⚠️ Kuchli model (`{main.split('/')[-1]}`) kunlik limitining **{pct:.0f}%** i ishlatildi "
        f"({used // 1000}K / {limit // 1000}K, oxirgi 24 soat). Tugasa javoblarni kuchsizroq "
        "zaxira model beradi — sifat biroz pasayishi mumkin. Limit asta-sekin tiklanadi.",
    )


async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/zaxira — hozir nusxa olib, chatga yuboradi."""
    if not _authorized(update):
        return
    import backup
    chat_id = update.effective_chat.id
    path = await asyncio.to_thread(backup.daily)
    zpath = await asyncio.to_thread(backup.weekly_zip)
    ok = await asyncio.to_thread(backup.integrity_ok, path)
    with open(zpath, "rb") as f:
        await context.bot.send_document(
            chat_id, f, filename=os.path.basename(zpath),
            caption=f"💾 Zaxira nusxa{'' if ok else ' ⚠️ tekshiruvdan o‘tmadi!'} — "
                    "xotira, xarajatlar, eslatmalar, kanallar. Kalitlar (session, token) kirmaydi.",
        )
    os.remove(zpath)


BRIEF_LATEST_HOUR = 13  # shundan keyin yoqilsa "xayrli tong" brifingi yuborilmaydi


async def morning_brief_job(context: ContextTypes.DEFAULT_TYPE):
    """Har 10 daqiqada: BRIEF_HOUR dan keyin (kompyuter kechroq yoqilsa — yoqilganda),
    kuniga bir marta tonggi brifing. Avval faqat aynan 07:00 da ishlardi."""
    from datetime import datetime as _dt
    now = _dt.now()
    if not (config.BRIEF_HOUR <= now.hour < BRIEF_LATEST_HOUR):
        return
    today = now.strftime("%Y-%m-%d")
    for chat_id in memory.settings_where("morning_brief", "1"):
        if memory.get_setting(chat_id, "brief_last") == today:
            continue
        memory.set_setting(chat_id, "brief_last", today)
        city = memory.get_setting(chat_id, "brief_city", "Tashkent")
        try:
            text = await asyncio.to_thread(jtools.compose_brief, chat_id, city)
            await _send_md(context.bot, chat_id, text)
            log.info("Tonggi brifing yuborildi [%s]", chat_id)
        except Exception:
            log.warning("Tonggi brifing xatosi [%s]", chat_id)


async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Har 30 soniyada vaqti kelgan (bir martalik + takroriy) eslatmalarni yuboradi."""
    # Takroriy eslatmalar (har kuni/hafta)
    for chat_id, text in memory.due_recurring():
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"🔔 Eslatma: {text}")
        except Exception:
            log.warning("Takroriy eslatma yuborilmadi (chat_id=%s)", chat_id)

    # Yillik sanalar: ertaga/bugun (soat 9 dan keyin, PC yoqilganda ham yetib keladi)
    for chat_id, text, year, occ, is_today in memory.due_dates():
        try:
            await _send_md(context.bot, chat_id, jtools.date_alert_text(text, year, occ, is_today))
        except Exception:
            log.warning("Yillik sana eslatmasi yuborilmadi (chat_id=%s)", chat_id)

    # Kompyuter o'chiq paytida o'tib ketganlar: yoqilganda hammasi birdaniga otilmasin.
    now = time.time()
    missed = {}
    for rid, chat_id, text, due_ts in memory.due_reminders_with_ts():
        # Avval "yuborildi" deb belgilaymiz — yuborish xato bo'lsa ham
        # cheksiz qayta urinmaslik uchun (best-effort).
        memory.mark_reminder_sent(rid)
        late = now - due_ts
        if "namozi vaqti" in text and late > 3600:
            continue  # namoz vaqti o'tib ketgan — eslatishning ma'nosi yo'q
        if late > 3 * 3600:
            missed.setdefault(chat_id, []).append((due_ts, text))
            continue
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"⏰ Eslatma: {text}")
        except Exception:
            log.warning("Eslatma yuborilmadi (chat_id=%s) — o'tkazib yuborildi", chat_id)
    for chat_id, items in missed.items():
        from datetime import datetime as _dt
        lines = [f"• {_dt.fromtimestamp(ts):%d.%m %H:%M} — {t}" for ts, t in sorted(items)[:10]]
        try:
            await _send_md(
                context.bot, chat_id,
                "⏰ **Kompyuter o'chiq paytida o'tib ketgan eslatmalar:**\n" + "\n".join(lines),
            )
        except Exception:
            log.warning("O'tib ketgan eslatmalar yuborilmadi (chat_id=%s)", chat_id)


BOT_COMMANDS = [
    ("status", "Holat va token sarfi"),
    ("pc", "Kompyuter: holat va boshqaruv"),
    ("ekran", "Kompyuter ekrani rasmi"),
    ("buyruqlar", "Build/test/git pull/dev serverlar"),
    ("sanalar", "Tug'ilgan kunlar va yillik sanalar"),
    ("city", "Man City: o'yinlar, jadval, natija"),
    ("hafta", "Haftalik hisobot"),
    ("dayjest", "Kanallar xulosasi"),
    ("javobsiz", "Kim javob kutyapti"),
    ("xato", "Oxirgi javob noto'g'ri — belgilash"),
    ("zaxira", "Baza nusxasini yuborish"),
    ("reset", "Suhbatni tozalash"),
    ("start", "Yordam"),
]


async def _set_commands(app):
    """Telegram'dagi "/" menyusi. Faqat egasining shaxsiy chatida ko'rinadi —
    bot moderatsiya qiladigan guruhlarda buyruqlar chiqmasin."""
    from telegram import BotCommand, BotCommandScopeChat
    try:
        cmds = [BotCommand(c, d) for c, d in BOT_COMMANDS]
        if config.OWNER_ID:
            await app.bot.set_my_commands(cmds, scope=BotCommandScopeChat(config.OWNER_ID))
        else:
            await app.bot.set_my_commands(cmds)
    except Exception as e:
        log.warning("Buyruqlar menyusi o'rnatilmadi: %s", e)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Tarmoq xatolarini bir qatorlik qiladi (traceback bilan terminalni to'ldirmaydi).
    Bunday xatolar vaqtinchalik — bot o'zi qayta ulanadi."""
    err = context.error
    if isinstance(err, (NetworkError, TimedOut)):
        log.warning("Tarmoq uzildi (qayta ulanmoqda): %s", err.__class__.__name__)
    else:
        log.error("Kutilmagan xatolik: %s", err)


# Slashsiz yozilgan buyruq so'zlari ("status") — modelga bormaydi.
WORD_COMMANDS = {
    "status": status, "holat": status, "statistika": status,
    "yordam": start, "help": start, "menyu": start,
    "pc": cmd_pc, "kompyuter": cmd_pc, "ekran": cmd_screen,
    "sanalar": cmd_dates, "tug'ilgan kunlar": cmd_dates,
}


def main():
    config.check()
    memory.init_db()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(_set_commands).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("dayjest", cmd_digest))
    app.add_handler(CommandHandler("javobsiz", cmd_unanswered))
    app.add_handler(CommandHandler("zaxira", cmd_backup))
    app.add_handler(CommandHandler("hafta", cmd_weekly))
    app.add_handler(CommandHandler("xato", cmd_feedback))
    app.add_handler(CommandHandler("pc", cmd_pc))
    app.add_handler(CommandHandler("ekran", cmd_screen))
    app.add_handler(CommandHandler("buyruqlar", cmd_commands))
    app.add_handler(CommandHandler("sanalar", cmd_dates))
    app.add_handler(CommandHandler("city", cmd_city))
    app.add_handler(CallbackQueryHandler(on_button))
    # Shaxsiy chat -> FRIDAY agent; guruhlar -> faqat moderatsiya.
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, on_message
        )
    )
    # Ovozli xabarlar (shaxsiy chat) -> Whisper + FRIDAY + ovozli javob.
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & (filters.VOICE | filters.AUDIO), on_voice
        )
    )
    # Rasmlar (shaxsiy chat) -> Gemini tavsifi + agent javobi. Hujjatdan OLDIN:
    # fayl sifatida yuborilgan rasm ham shu yerga tushsin.
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & (
                filters.PHOTO | filters.Document.IMAGE | filters.VIDEO | filters.VIDEO_NOTE
                | filters.ANIMATION | filters.Document.VIDEO
            ),
            on_photo,
        )
    )
    # Hujjatlar (shaxsiy chat) -> o'qib xulosa qilish.
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.Document.ALL, on_document
        )
    )
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            on_group_message,
        )
    )
    # Yangi a'zo profil rasmi tekshiruvi.
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.StatusUpdate.NEW_CHAT_MEMBERS,
            on_new_member,
        )
    )
    # Rasm/video/sticker NSFW (18+) moderatsiyasi.
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS
            & (
                filters.PHOTO
                | filters.VIDEO
                | filters.ANIMATION
                | filters.Sticker.ALL
                | filters.Document.IMAGE
                | filters.Document.VIDEO
            ),
            on_group_media,
        )
    )

    # Eslatmalarni tekshiruvchi fon vazifasi.
    if app.job_queue:
        app.job_queue.run_repeating(check_reminders, interval=30, first=10)
        app.job_queue.run_repeating(digest_job, interval=600, first=60)
        app.job_queue.run_repeating(unanswered_job, interval=600, first=90)
        app.job_queue.run_repeating(backup_job, interval=3600, first=30)
        app.job_queue.run_repeating(usage_job, interval=900, first=120)
        app.job_queue.run_repeating(weekly_job, interval=600, first=150)
        import nowplaying
        app.job_queue.run_repeating(loop_job, interval=nowplaying.TICK_SEC, first=5)
        app.job_queue.run_repeating(football_job, interval=600, first=45)
        # Kundalik: avto-namoz va tonggi brifing — aniq soatda emas, kompyuter
        # yoqilgandan keyin (kuniga bir marta): run_daily o'chiq kompyuterda o'tib ketardi.
        app.job_queue.run_repeating(daily_prayers_job, interval=600, first=20)
        app.job_queue.run_repeating(morning_brief_job, interval=600, first=45)
    else:
        log.warning("job_queue yo'q — eslatmalar ishlamaydi. "
                    "O'rnating: pip install \"python-telegram-bot[job-queue]\"")

    log.info("FRIDAY ishga tushdi. To'xtatish: Ctrl+C")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
