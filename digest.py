"""Kanallar dayjesti va javobsiz xabarlar (userbot ustida).

Dayjest: kuzatiladigan har kanalning oxirgi dayjestdan keyingi postlari
alohida qisqa xulosa qilinadi (Groq), har band asl postga havola bilan.
Postlar faqat Groq'ga boradi (Gemini'ga emas). AI limitga urilsa — eng ko'p
ko'rilgan postlar xulosasiz beriladi, dayjest baribir chiqadi.

Javobsiz xabarlar: AI ishlatilmaydi, matn hech qayerga yuborilmaydi.
"""
import datetime
import logging
import re
import time

import memory
import userbot

log = logging.getLogger("jarvis")

POSTS_PER_CHANNEL = 40
INPUT_CHARS = 6000          # bitta kanal uchun modelga ketadigan matn chegarasi
PAUSE_BETWEEN = 10          # soniya — daqiqalik token limitini urmaslik uchun
UNANSWERED_MINUTES = 1
UNANSWERED_MAX_DAYS = 3

_REF_RE = re.compile(r"\[#(\d+)\]")

_SYSTEM = (
    "Telegram kanal postlaridan qisqa dayjest yoz. O'zbek tilida, 2-5 ta band, "
    "har biri '- ' bilan boshlanadi va bitta gapdan iborat, eng muhim yangiliklar "
    "birinchi. Reklama, konkurs, 'obuna bo'ling' postlarini TASHLA. Har band oxirida "
    "manba postni [#id] ko'rinishida yoz. Faqat postlarda bor narsani yoz, qo'shimcha "
    "fikr yoki kirish so'zi yozma. Muhim narsa bo'lmasa faqat '- Muhim yangilik yo'q' yoz."
)


def _post_link(channel, post_id):
    if channel["username"]:
        return f"https://t.me/{channel['username']}/{post_id}"
    raw = str(abs(channel["channel_id"]))
    internal = raw[3:] if raw.startswith("100") else raw
    return f"https://t.me/c/{internal}/{post_id}"


def _posts_block(posts):
    """Eng yangi postlardan boshlab INPUT_CHARS gacha (keyin eskidan yangiga)."""
    picked, total = [], 0
    for p in reversed(posts):
        line = f"#{p['id']} (👁 {p['views']}): {p['text'][:500]}"
        if total + len(line) > INPUT_CHARS and picked:
            break
        picked.append(line)
        total += len(line)
    return "\n\n".join(reversed(picked))


def _summarize(channel, posts):
    import agent  # agent -> tools -> ... aylanma importdan qochish uchun shu yerda

    resp = agent._create(
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Kanal: {channel['title']}\n\n{_posts_block(posts)}"},
        ],
        max_tokens=700,
    )
    text = agent._clean(resp.choices[0].message.content)
    return _REF_RE.sub(lambda m: f"[↗]({_post_link(channel, m.group(1))})", text)


def _fallback(channel, posts):
    top = sorted(posts, key=lambda p: -p["views"])[:3]
    return "\n".join(
        f"- {p['text'].splitlines()[0][:100]} [↗]({_post_link(channel, p['id'])})" for p in top
    )


def build_digest(chat_id):
    """Dayjest matni (Markdown). Kanal yo'q bo'lsa — yo'riqnoma."""
    channels = memory.list_digest_channels(chat_id)
    if not channels:
        return (
            "📰 Dayjest uchun kanal tanlanmagan. Masalan: \"kun.uz kanalini dayjestga qo'sh\" "
            "yoki \"qaysi kanallarga obunaman?\""
        )
    if not userbot._ensure_started():
        return userbot.NOT_READY

    parts = [f"📰 **Dayjest** — {datetime.date.today():%d.%m}"]
    empty = []
    first = True
    for ch in channels:
        try:
            posts = userbot.fetch_posts(ch["channel_id"], ch["last_id"], POSTS_PER_CHANNEL)
        except Exception as e:
            log.warning("Kanal o'qilmadi (%s): %s", ch["title"], e)
            parts.append(f"\n**{ch['title']}**\n- (o'qib bo'lmadi)")
            continue
        if not posts:
            empty.append(ch["title"])
            continue
        if not first:
            time.sleep(PAUSE_BETWEEN)
        first = False
        try:
            body = _summarize(ch, posts)
        except Exception as e:
            log.warning("Dayjest AI xatosi (%s): %s", ch["title"], str(e)[:150])
            body = _fallback(ch, posts)
        parts.append(f"\n**{ch['title']}** · {len(posts)} ta post\n{body}")
        memory.set_digest_last(chat_id, ch["channel_id"], posts[-1]["id"])

    if len(parts) == 1:
        parts.append("Kuzatilayotgan kanallarda yangi post yo'q.")
    elif empty:
        parts.append(f"\n💤 Yangi post yo'q: {', '.join(empty)}")
    return "\n".join(parts)


def unanswered_text():
    """Javobsiz shaxsiy xabarlar ro'yxati (Markdown) yoki None — hammasi javob berilgan."""
    items = userbot.unanswered(UNANSWERED_MINUTES, UNANSWERED_MAX_DAYS)
    if items is None:
        return userbot.NOT_READY
    if not items:
        return None
    lines = [f"📥 **Javob kutayotganlar** ({len(items)})"]
    for it in items[:15]:
        mins = it["minutes"]
        if mins < 60:
            age = f"{mins} daqiqa"
        elif mins < 1440:
            age = f"{mins // 60} soat"
        else:
            age = f"{mins // 1440} kun"
        unread = f" · 🔵 {it['unread']} ta o'qilmagan" if it["unread"] else ""
        lines.append(f"• **{it['name']}** — {age}{unread} · «{it['preview']}»")
    if len(items) > 15:
        lines.append(f"…va yana {len(items) - 15} ta")
    return "\n".join(lines)
