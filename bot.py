"""Telegram bot: xabarlarni qabul qiladi, JARVIS'ga uzatadi, javobni yuboradi."""
import asyncio
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

import config
import memory
import agent

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("jarvis")


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


def main():
    config.check()
    memory.init_db()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

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
