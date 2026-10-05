"""Man City kuzatuvi — ESPN ochiq API (kalit kerak emas).

Egasi so'ragani (2026-10-05): faqat JIDDIY xabarlar va o'yinlar.
- O'yin kuni ertalab: "Bugun o'yin" (vaqt Toshkent bo'yicha), 1 soat oldin eslatma.
- O'yin tugagach: hisob + gol urganlar + qizil kartochkalar (24 soatgacha kechiksa ham).
- Yangiliklar: ESPN Man City lentasi -> model faqat jiddiylarini ajratadi (jarohat, rasmiy
  transfer, murabbiy, diskvalifikatsiya, sud/ochko ayirish). Mish-mish, fikr, reyting — yo'q.

Yuborilganlar settings'da (football_sent, football_news_seen) — takror chiqmaydi.
"""
import datetime
import json
import logging
import time
import urllib.request

import config
import memory
import net

log = logging.getLogger("jarvis")

TEAM_ID = "382"
TEAM = "Man City"
BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
STANDINGS = "https://site.api.espn.com/apis/v2/sports/soccer/eng.1/standings"
TZ = datetime.timezone(datetime.timedelta(hours=config.TZ_OFFSET))

MORNING_HOUR = 8          # o'yin kuni shu soatdan keyin "bugun o'yin"
PRE_MIN = 60              # boshlanishidan shuncha daqiqa oldin eslatma
RESULT_WINDOW_H = 24      # shu vaqt ichida tugagan o'yin natijasi yuboriladi
NEWS_EVERY_SEC = 2 * 3600
NEWS_MAX = 3              # bir tekshiruvda ko'pi bilan

LEAGUES = {
    "eng.1": "APL", "uefa.champions": "Chempionlar ligasi", "eng.fa": "FA kubogi",
    "eng.league_cup": "Liga kubogi", "eng.charity": "Superkubok", "club.friendly": "O'rtoqlik o'yini",
    "fifa.cwc": "Klublar JCh", "uefa.super_cup": "UEFA Superkubogi",
}
_DONE = ("STATUS_FULL_TIME", "STATUS_FINAL", "STATUS_FINAL_AET", "STATUS_FINAL_PEN")
_SKIP = ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED")
_DAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]

_cache = {}  # url -> (ts, data)


def _get(url, ttl=0):
    hit = _cache.get(url)
    if ttl and hit and time.time() - hit[0] < ttl:
        return hit[1]
    net.prefer_ipv4()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 FRIDAY"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    _cache[url] = (time.time(), data)
    return data


def _score(c):
    s = c.get("score")
    if isinstance(s, dict):
        s = s.get("displayValue")
    return None if s in (None, "") else str(s)


def parse(e):
    """ESPN event -> oddiy dict."""
    comp = e["competitions"][0]
    side = {c["homeAway"]: c for c in comp["competitors"]}
    home, away = side["home"], side["away"]
    league = e.get("league") if isinstance(e.get("league"), dict) else {}
    slug = league.get("slug") or ""
    return {
        "id": e["id"],
        "slug": slug,
        "league": LEAGUES.get(slug) or league.get("abbreviation") or league.get("name") or "",
        "kickoff": datetime.datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(TZ),
        "home": home["team"].get("shortDisplayName") or home["team"]["displayName"],
        "away": away["team"].get("shortDisplayName") or away["team"]["displayName"],
        "home_score": _score(home), "away_score": _score(away),
        "is_home": home["team"]["id"] == TEAM_ID,
        "status": comp.get("status", {}).get("type", {}).get("name", ""),
        "venue": (comp.get("venue") or {}).get("fullName", ""),
    }


def fixtures():
    """Kelgusi o'yinlar (hamma turnirlar), vaqt bo'yicha."""
    d = _get(f"{BASE}/all/teams/{TEAM_ID}/schedule?fixture=true", ttl=3 * 3600)
    ms = [parse(e) for e in d.get("events", [])]
    return sorted((m for m in ms if m["status"] not in _SKIP), key=lambda m: m["kickoff"])


def results():
    """O'tgan o'yinlar — eng yangisi birinchi."""
    d = _get(f"{BASE}/all/teams/{TEAM_ID}/schedule", ttl=600)
    ms = [parse(e) for e in d.get("events", [])]
    return sorted((m for m in ms if m["status"] in _DONE), key=lambda m: m["kickoff"], reverse=True)


def _night(ko):
    """00:00-05:59 dagi o'yin odamcha "oldingi kun kechasi" — Payshanba 00:00 = Chorshanba kechasi."""
    return ko.hour < 6


def _when(ko, now=None):
    now = now or datetime.datetime.now(TZ)
    base = ko - datetime.timedelta(days=1) if _night(ko) else ko
    days = (base.date() - now.date()).days
    day = "bugun" if days == 0 else "ertaga" if days == 1 else _DAYS[base.weekday()]
    if _night(ko):
        day += " kechasi"
    return f"{day} {ko:%H:%M} ({ko:%d.%m})" if days > 1 or _night(ko) else f"{day} {ko:%H:%M}"


def opponent(m):
    return m["away"] if m["is_home"] else m["home"]


def match_title(m):
    return f"{m['home']} — {m['away']}"


def fixtures_text(n=5, now=None):
    try:
        ms = fixtures()[:n]
    except Exception as e:
        return f"❌ O'yinlar ro'yxatini olib bo'lmadi: {str(e)[:80]}"
    lines = [f"⚽ **{TEAM} — keyingi o'yinlar**"]
    for m in ms:
        where = "uyda" if m["is_home"] else "mehmonda"
        lines.append(f"• {_when(m['kickoff'], now)} — {opponent(m)} ({where}) · {m['league']}")
    if not ms:
        lines.append("Rejada o'yin yo'q.")
    t = table_line()
    if t:
        lines.append("\n" + t)
    return "\n".join(lines)


def _outcome(m):
    try:
        us, them = (int(m["home_score"]), int(m["away_score"]))
    except (TypeError, ValueError):
        return "🏁"
    if not m["is_home"]:
        us, them = them, us
    if us == them and m["status"] == "STATUS_FINAL_PEN":
        return "🎯"  # penaltilar seriyasi
    return "✅" if us > them else "➖" if us == them else "❌"


def results_text(n=5):
    try:
        ms = results()[:n]
    except Exception as e:
        return f"❌ Natijalarni olib bo'lmadi: {str(e)[:80]}"
    lines = [f"🏁 **{TEAM} — oxirgi natijalar**"]
    for m in ms:
        lines.append(f"{_outcome(m)} {m['kickoff']:%d.%m} {m['home']} {m['home_score']}–{m['away_score']} "
                     f"{m['away']} · {m['league']}")
    return "\n".join(lines)


def table_line():
    """'📊 APL: 1-o'rin, 15 ochko (5 o'yin: 5-0-0)' — xato bo'lsa bo'sh."""
    try:
        d = _get(STANDINGS, ttl=3 * 3600)
        for e in d["children"][0]["standings"]["entries"]:
            if e["team"]["id"] == TEAM_ID:
                st = {s["name"]: s.get("displayValue") for s in e["stats"]}
                line = (f"📊 APL: {st.get('rank')}-o'rin, {st.get('points')} ochko "
                        f"({st.get('gamesPlayed')} o'yin: {st.get('wins')}-{st.get('ties')}-{st.get('losses')})")
                ded = st.get("deductions")
                if ded and ded not in ("0", "-0"):
                    line += f" · ⚠️ {ded.lstrip('-')} ochko ayirilgan"
                return line
    except Exception:
        pass
    return ""


def _scorers(m):
    """{jamoa: {futbolchi: ["43'", "57'"]}}, qizil kartochkalar ro'yxati."""
    d = _get(f"{BASE}/{m['slug'] or 'all'}/summary?event={m['id']}", ttl=600)
    goals, reds = {}, []  # goals: {jamoa: {futbolchi: [daqiqalar]}}
    for k in d.get("keyEvents", []):
        typ = (k.get("type") or {}).get("type", "")
        clock = (k.get("clock") or {}).get("displayValue", "")
        team = (k.get("team") or {}).get("displayName", "").replace("Manchester City", TEAM)
        who = [p["athlete"]["displayName"] for p in k.get("participants", []) if p.get("athlete")]
        name = who[0] if who else "?"
        if k.get("scoringPlay"):
            if "own" in typ:
                name += " (avtogol)"
            elif "penalty" in typ:
                name += " (pen.)"
            goals.setdefault(team, {}).setdefault(name, []).append(clock)
        elif "red-card" in typ:
            reds.append(f"{clock} {name} ({team})")
    return goals, reds


def result_text(m):
    head = f"{_outcome(m)} **{m['home']} {m['home_score']}–{m['away_score']} {m['away']}** · {m['league']}"
    lines = [head]
    try:
        goals, reds = _scorers(m)
    except Exception:
        goals, reds = {}, []
    for team, by_player in goals.items():
        lines.append(f"⚽ {team}: " + ", ".join(f"{p} {', '.join(c)}" for p, c in by_player.items()))
    if reds:
        lines.append("🟥 " + ", ".join(reds))
    if m["slug"] == "eng.1":
        t = table_line()
        if t:
            lines.append(t)
    return "\n".join(lines)


# --- Avtomatik xabarlar ---

def _sent(chat_id):
    try:
        return json.loads(memory.get_setting(chat_id, "football_sent", "[]") or "[]")
    except ValueError:
        return []


def _mark(chat_id, keys):
    sent = (_sent(chat_id) + keys)[-80:]
    memory.set_setting(chat_id, "football_sent", json.dumps(sent))


def match_alerts(chat_id, now=None):
    """[(matn)] — o'yin kuni, 1 soat oldin va natija. Yuborilganlar belgilanadi."""
    now = now or datetime.datetime.now(TZ)
    sent = set(_sent(chat_id))
    out, keys = [], []
    try:
        upcoming = fixtures()
    except Exception as e:
        log.warning("Futbol: fixtures xato: %s", str(e)[:100])
        upcoming = []
    # Chempionlar ligasi Toshkentda 00:00/01:00 da — "bugun" = shu kecha ertangi 06:00 gacha.
    tonight_end = datetime.datetime.combine(now.date() + datetime.timedelta(days=1),
                                            datetime.time(6, 0), TZ)
    for m in upcoming:
        ko = m["kickoff"]
        left = (ko - now).total_seconds() / 60
        if left <= 0 or ko > tonight_end:
            continue
        where = f"\n🏟 {m['venue']}" if m["venue"] else ""
        if left <= PRE_MIN + 15 and f"pre:{m['id']}" not in sent:
            out.append(f"⏰ **{round(left)} daqiqadan keyin:** {match_title(m)} · {m['league']}{where}")
            keys += [f"pre:{m['id']}", f"day:{m['id']}"]
        elif now.hour >= MORNING_HOUR and f"day:{m['id']}" not in sent and f"pre:{m['id']}" not in sent:
            when = (f"soat {ko:%H:%M}" if ko.date() == now.date()
                    else f"bugun kechasi soat {ko:%H:%M} ({ko:%d.%m})")
            out.append(f"⚽ **Bugun o'yin:** {match_title(m)} — {when} · {m['league']}{where}")
            keys.append(f"day:{m['id']}")
    try:
        done = results()
    except Exception as e:
        log.warning("Futbol: results xato: %s", str(e)[:100])
        done = []
    for m in done:
        age_h = (now - m["kickoff"]).total_seconds() / 3600
        if age_h <= RESULT_WINDOW_H and f"ft:{m['id']}" not in sent:
            out.append(result_text(m))
            keys.append(f"ft:{m['id']}")
    if keys:
        _mark(chat_id, keys)
    return out


# --- Jiddiy yangiliklar ---

_NEWS_PROMPT = (
    "Sen Manchester City muxlisi uchun yangiliklarni filtrlaysan. Egasi FAQAT JIDDIY "
    "xabarlarni xohlaydi:\n"
    "- erkaklar asosiy jamoasi futbolchisining jarohati, jarohat GUMONI (injury fear/doubt, "
    "terma jamoada ham) yoki jarohatdan qaytishi;\n"
    "- RASMIY transfer (imzolandi, sotildi, ijaraga ketdi, shartnoma uzaytirildi);\n"
    "- bosh murabbiy yoki rahbariyat o'zgarishi; diskvalifikatsiya;\n"
    "- sud/tergov: hukm, jarima, ochko ayirish, apellyatsiya qarori; klubning rasmiy bayonoti.\n"
    "KERAK EMAS: mish-mish (rumors, wants, eye, linked, could), fikr/tahlil/reyting/viktorina, "
    "o'yin oldi sharhlar, sobiq futbolchilar va boshqa klublar haqida, ayollar jamoasi, "
    "allaqachon yuborilganlar ro'yxatidagi voqeaning takrori (yangi muhim fakt bo'lmasa).\n"
    "Har birini o'zbekcha 1-2 jumlada aniq faktlar bilan yoz (ism, nima bo'ldi, qancha muddat). "
    "Tabiiy, sodda o'zbekcha; namuna: «Haaland Norvegiya o'yinida jarohat sabab almashtirishni "
    "so'radi — Liverpool o'yiniga ulgurishi noma'lum.» Matnda YO'Q sana, yil yoki raqamni qo'shma. "
    'Faqat JSON: {"items": [{"headline": "<maqola sarlavhasi AYNAN>", "uz": "..."}]} — '
    'jiddiysi bo\'lmasa {"items": []}.'
)


def _match(headline, arts):
    """Model qaytargan sarlavha -> maqola. Raqam so'raganda model o'z ro'yxatini 1,2,3 deb
    sanab, havolalar boshqa maqolalarga ketgan edi — shuning uchun sarlavha bo'yicha."""
    import difflib
    best, score = None, 0.0
    for a in arts:
        r = difflib.SequenceMatcher(None, headline.lower(), a["headline"].lower()).ratio()
        if r > score:
            best, score = a, r
    return best if score >= 0.6 else None


def _news_articles():
    d = _get(f"{BASE}/eng.1/news?team={TEAM_ID}&limit=20")
    out = []
    for a in d.get("articles", []):
        teams = [c.get("description") for c in a.get("categories", []) if c.get("type") == "team"]
        if "Manchester City" not in teams:
            continue
        out.append({
            "id": str(a.get("id") or a.get("headline")),
            "headline": a.get("headline", ""),
            "desc": (a.get("description") or "")[:200],
            "published": a.get("published", ""),
            "url": ((a.get("links") or {}).get("web") or {}).get("href", ""),
        })
    return out


def _json_list(chat_id, key):
    try:
        return json.loads(memory.get_setting(chat_id, key, "[]") or "[]")
    except ValueError:
        return []


def serious_news(chat_id, now=None):
    """Yangi jiddiy xabarlar matnlari. Ko'rilgan maqolalar belgilanadi (model xato bersa — yo'q)."""
    import agent
    import brain

    now = now or datetime.datetime.now(datetime.timezone.utc)
    seen = _json_list(chat_id, "football_news_seen")
    first_run = not seen
    arts = [a for a in _news_articles() if a["id"] not in seen]
    if first_run:
        # Birinchi marta: faqat oxirgi 24 soat (eski hammasini to'kib tashlamaslik uchun)
        cutoff = (now - datetime.timedelta(hours=24)).isoformat()[:16]
        fresh = [a for a in arts if a["published"][:16] >= cutoff]
    else:
        fresh = arts
    if not fresh:
        memory.set_setting(chat_id, "football_news_seen", json.dumps((seen + [a["id"] for a in arts])[-150:]))
        return []
    sent_before = _json_list(chat_id, "football_news_sent")
    listing = "\n".join(f"- {a['headline']} — {a['desc']}" for a in fresh)
    prompt = (f"Allaqachon yuborilganlar:\n{chr(10).join(sent_before[-10:]) or '(yo`q)'}\n\n"
              f"Yangi maqolalar:\n{listing}")
    resp = agent._create(messages=[{"role": "system", "content": _NEWS_PROMPT},
                                   {"role": "user", "content": prompt}], max_tokens=1500)
    data = brain._json(resp.choices[0].message.content) or {}
    if "items" not in data:
        raise ValueError("model JSON bermadi")
    out, used = [], set()
    for it in data["items"]:
        if len(out) >= NEWS_MAX or not isinstance(it, dict):
            break
        a = _match(str(it.get("headline", "")), fresh)
        uz = str(it.get("uz", "")).strip()
        if not a or not uz or a["id"] in used:
            continue
        used.add(a["id"])
        link = f"\n[ESPN]({a['url']})" if a["url"] else ""
        out.append(f"📰 **{TEAM}:** {uz}{link}")
        sent_before.append(uz[:150])
    memory.set_setting(chat_id, "football_news_seen", json.dumps((seen + [a["id"] for a in arts])[-150:]))
    memory.set_setting(chat_id, "football_news_sent", json.dumps(sent_before[-20:], ensure_ascii=False))
    return out


def news_due(chat_id):
    last = float(memory.get_setting(chat_id, "football_news_ts", "0") or 0)
    return time.time() - last >= NEWS_EVERY_SEC


def mark_news_checked(chat_id):
    memory.set_setting(chat_id, "football_news_ts", str(time.time()))


def week_lines(days=7, now=None):
    """Haftalik hisobot uchun: kelasi `days` kundagi o'yinlar."""
    now = now or datetime.datetime.now(TZ)
    try:
        ms = [m for m in fixtures() if 0 <= (m["kickoff"] - now).total_seconds() <= days * 86400]
    except Exception:
        return []
    return [f"• {_when(m['kickoff'], now)} — {opponent(m)} "
            f"({'uyda' if m['is_home'] else 'mehmonda'}) · {m['league']}" for m in ms]
