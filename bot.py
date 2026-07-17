import os
import asyncio
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatPermissions,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import NetworkError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

import config
import memory
import agent
import moderation
import nsfw
import security
import tools as jtools
import userbot
import voice

# Kutilayotgan CAPTCHA'lar: (chat_id, user_id) -> {msg_id, job}
PENDING_CAPTCHAS = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("jarvis")

# Keraksiz shovqinni o'chiramiz — faqat JARVIS log'lari va haqiqiy muammolar qolsin.
for _noisy in ("httpx", "httpcore", "apscheduler", "telethon", "telegram.ext.Application"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def _authorized(update: Update) -> bool:
    """Faqat egasi (OWNER_ID) bot bilan gaplasha oladi."""
    if config.OWNER_ID == 0:
        return True
    return bool(update.effective_user and update.effective_user.id == config.OWNER_ID)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(
        "Salom bro! Men JARVIS — shaxsiy AI yordamching.\n"
        "Kod yozaman, fikr aytaman, fayllar bilan ishlayman.\n"
        "Suhbatni tozalash: /reset"
    )


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
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        # agent.respond sinxron (tarmoq chaqiruvi) — event loop'ni bloklamaslik uchun
        # alohida oqimda ishga tushiramiz.
        reply = await asyncio.to_thread(agent.respond, chat_id, text)
    except Exception as e:
        log.exception("Javob berishda xato")
        s = str(e).lower()
        if "429" in s or "rate_limit" in s or "too many requests" in s:
            reply = (
                "⏳ Groq tekin chegarasi (daqiqasiga token limiti) urildi. "
                "Iltimos ~1 daqiqa kutib, qayta yozing bro."
            )
        else:
            reply = f"Xato yuz berdi: {e}"

    # Telegram bitta xabarda 4096 belgigacha ruxsat beradi — uzun bo'lsa bo'laklaymiz.
    for i in range(0, len(reply), 4000):
        await update.message.reply_text(reply[i : i + 4000])

    await _show_pending_sends(update, chat_id)


async def _show_pending_sends(update: Update, chat_id):
    """Tayyorlangan (hali yuborilmagan) Telegram xabarlar uchun tasdiq tugmalari."""
    for sid, p in list(jtools.PENDING_SENDS.items()):
        if p["chat_id"] != chat_id or p["shown"]:
            continue
        p["shown"] = True
        kb = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Yuborish", callback_data=f"tgy:{sid}"),
                InlineKeyboardButton("❌ Bekor", callback_data=f"tgn:{sid}"),
            ]]
        )
        await update.effective_message.reply_text(
            f"📨 Qabul qiluvchi: {p['to_name']}\n\n\"{p['text']}\"\n\nYuborilsinmi?",
            reply_markup=kb,
        )


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ovozli xabar: Whisper bilan tushunadi, JARVIS javobini matn + OVOZ bilan beradi."""
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
            reply = await asyncio.to_thread(agent.respond, chat_id, text)
        except Exception as e:
            log.exception("Javob berishda xato (ovoz)")
            s = str(e).lower()
            if "429" in s or "rate_limit" in s or "too many requests" in s:
                reply = "⏳ Groq tekin chegarasi urildi. ~1 daqiqa kutib qayta urinib ko'ring."
            else:
                reply = f"Xato yuz berdi: {e}"

        for i in range(0, len(reply), 4000):
            await msg.reply_text(reply[i : i + 4000])
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


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline tugmalar: CAPTCHA tasdig'i (yangi a'zo) va Telegram yuborish (egasi)."""
    q = update.callback_query
    data = q.data or ""

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

    if action == "tgy":
        try:
            result = await asyncio.to_thread(userbot.send_message, p["to_id"], p["text"])
            await q.edit_message_text(f"✅ {result}")
        except Exception as e:
            log.exception("Userbot yuborishda xato")
            await q.edit_message_text(f"Xato: yuborilmadi — {e}")
    else:
        await q.edit_message_text(f"❌ Bekor qilindi ({p['to_name']} ga yuborilmadi).")


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
    """Matn moderatsiyasi: so'kinish/haqorat. Guruh xabarlari JARVIS'ga BORMAYDI."""
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


async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Har 30 soniyada vaqti kelgan eslatmalarni yuboradi."""
    for rid, chat_id, text in memory.due_reminders():
        # Avval "yuborildi" deb belgilaymiz — yuborish xato bo'lsa ham
        # cheksiz qayta urinmaslik uchun (best-effort).
        memory.mark_reminder_sent(rid)
        try:
            await context.bot.send_message(chat_id=chat_id, text=f"⏰ Eslatma: {text}")
        except Exception:
            log.warning("Eslatma yuborilmadi (chat_id=%s) — o'tkazib yuborildi", chat_id)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Tarmoq xatolarini bir qatorlik qiladi (traceback bilan terminalni to'ldirmaydi).
    Bunday xatolar vaqtinchalik — bot o'zi qayta ulanadi."""
    err = context.error
    if isinstance(err, (NetworkError, TimedOut)):
        log.warning("Tarmoq uzildi (qayta ulanmoqda): %s", err.__class__.__name__)
    else:
        log.error("Kutilmagan xatolik: %s", err)


def main():
    config.check()
    memory.init_db()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CallbackQueryHandler(on_button))
    # Shaxsiy chat -> JARVIS agent; guruhlar -> faqat moderatsiya.
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, on_message
        )
    )
    # Ovozli xabarlar (shaxsiy chat) -> Whisper + JARVIS + ovozli javob.
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & (filters.VOICE | filters.AUDIO), on_voice
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
    else:
        log.warning("job_queue yo'q — eslatmalar ishlamaydi. "
                    "O'rnating: pip install \"python-telegram-bot[job-queue]\"")

    log.info("JARVIS ishga tushdi. To'xtatish: Ctrl+C")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
