"""Model yozgan Markdown'ni Telegram HTML'iga o'giradi.

Modellar "markdown ishlatma" desang ham baribir **qalin**, `kod`, # sarlavha,
- ro'yxat yozadi va Telegram'da xom yulduzchalar ko'rinadi. Taqiqlash o'rniga
to'g'ri render qilamiz: Telegram HTML faqat b/i/s/u/code/pre/a/blockquote'ni
tushunadi, qolgan hammasi (sarlavha, ro'yxat, jadval) matnga aylantiriladi.
"""
import html
import re

_FENCE_RE = re.compile(r"```[ \t]*([\w+-]*)[ \t]*\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__")
_ITALIC_RE = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_HEADING_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^([ \t]*)[-*+][ \t]+", re.MULTILINE)
_QUOTE_RE = re.compile(r"^>[ \t]?", re.MULTILINE)
_HR_RE = re.compile(r"^[ \t]*([-*_])([ \t]*\1){2,}[ \t]*(\n|$)", re.MULTILINE)
_TABLE_SEP_RE = re.compile(r"^[ \t]*\|?[ \t:]*-{2,}[-| \t:]*(\n|$)", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^[ \t]*\|(.+)\|[ \t]*$", re.MULTILINE)

# Kod bo'laklari vaqtincha shu belgilar bilan almashtiriladi (ichi formatlanmasin).
_PH = "\x00{}\x00"
_PH_RE = re.compile(r"\x00(\d+)\x00")


def _table_row(m):
    cells = [c.strip() for c in m.group(1).split("|")]
    return " — ".join(c for c in cells if c)


def to_html(text):
    """Markdown -> Telegram HTML (parse_mode=HTML uchun)."""
    text = (text or "").replace("\r\n", "\n")
    saved = []

    def keep(fragment):
        saved.append(fragment)
        return _PH.format(len(saved) - 1)

    def fence(m):
        lang, body = m.group(1), m.group(2).rstrip("\n")
        cls = f' class="language-{lang}"' if lang else ""
        return keep(f"<pre><code{cls}>{html.escape(body, quote=False)}</code></pre>")

    text = _FENCE_RE.sub(fence, text)
    text = _INLINE_CODE_RE.sub(
        lambda m: keep(f"<code>{html.escape(m.group(1), quote=False)}</code>"), text
    )
    text = _LINK_RE.sub(
        lambda m: keep(
            f'<a href="{html.escape(m.group(2))}">{html.escape(m.group(1), quote=False)}</a>'
        ),
        text,
    )

    text = html.escape(text, quote=False)

    text = _TABLE_SEP_RE.sub("", text)
    text = _TABLE_ROW_RE.sub(_table_row, text)
    text = _HR_RE.sub("", text)
    text = _HEADING_RE.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _BULLET_RE.sub(lambda m: m.group(1) + "• ", text)
    text = _BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _STRIKE_RE.sub(lambda m: f"<s>{m.group(1)}</s>", text)
    text = _ITALIC_RE.sub(lambda m: f"<i>{m.group(1)}</i>", text)
    text = _QUOTE_RE.sub("", text)

    text = _tidy(text)
    return _PH_RE.sub(lambda m: saved[int(m.group(1))], text)


def to_plain(text):
    """HTML yuborib bo'lmasa: markdown belgilarini olib tashlangan oddiy matn."""
    text = (text or "").replace("\r\n", "\n")
    saved = []

    def keep(fragment):
        saved.append(fragment)
        return _PH.format(len(saved) - 1)

    text = _FENCE_RE.sub(lambda m: keep(m.group(2).rstrip("\n")), text)
    text = _INLINE_CODE_RE.sub(lambda m: keep(m.group(1)), text)
    text = _LINK_RE.sub(r"\1 (\2)", text)
    text = _TABLE_SEP_RE.sub("", text)
    text = _TABLE_ROW_RE.sub(_table_row, text)
    text = _HR_RE.sub("", text)
    text = _HEADING_RE.sub(r"\1", text)
    text = _BULLET_RE.sub(lambda m: m.group(1) + "• ", text)
    text = _BOLD_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = _STRIKE_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    text = _tidy(text)
    return _PH_RE.sub(lambda m: saved[int(m.group(1))], text)


def _tidy(text):
    """Qator oxiridagi probellar, 2 tadan ortiq bo'sh qator, boshi/oxiri."""
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split(text, limit=3500):
    """Uzun Markdown'ni Telegram chegarasiga sig'adigan bo'laklarga ajratadi.

    Avval paragraf (bo'sh qator), keyin qator bo'yicha bo'ladi — kod bloki yoki
    teg o'rtasidan kesilmasligi uchun HTML'ga o'girishdan OLDIN chaqiriladi.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return [text] if text else []
    chunks, cur = [], ""
    for para in text.split("\n\n"):
        piece = para if not cur else "\n\n" + para
        if len(cur) + len(piece) <= limit:
            cur += piece
            continue
        if cur:
            chunks.append(cur)
        while len(para) > limit:
            cut = para.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            chunks.append(para[:cut])
            para = para[cut:].lstrip("\n")
        cur = para
    if cur:
        chunks.append(cur)
    return chunks
