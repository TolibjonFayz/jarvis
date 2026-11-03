"""ERP ish radari (EDITH): ERP Climavent prod'ida nimadir buzilsa — darhol aytadi.

AI ishlatilmaydi (tez, ishonchli, token yemaydi). Har RADAR_SEC da tekshiradi:
- api   — prod backend javob beryaptimi (har qanday HTTP < 500 = tirik);
- hik   — Hikvision davomat oqimi: ish kunlari (Du-Sh) HIK_FROM..HIK_TO oralig'ida
          oxirgi hodisa HIK_STALE_MIN dan eski bo'lsa — agent/terminal to'xtagan.
          O'lchov (2026-11-03): agent har 15 daq to'plab yuboradi, kunduzgi eng katta
          tanaffus 30-75 daq — 2 soat jimlik normal emas;
- amo:* — amoCRM sinxroni (har 10 daq ishlaydi): AMO_STALE_MIN dan beri ishlamagan
          yoki oxirgi holati 'ok' emas;
- 5xx   — faoliyat jurnalida oxirgi 15 daqiqada ERR_MIN dan ko'p server xatosi;
- db    — prod bazaga ulanib bo'lmadi.

Har muammo bir marta aytiladi, tiklanganda "✅ tiklandi" (qancha davom etgani bilan).
api va db uchun ketma-ket 2 marta yiqilish kerak (bitta tarmoq uzilishi signal emas).

Prod baza: backend .env dagi ulanish, `default_transaction_read_only=on` — yozish
texnik jihatdan bloklangan; faqat SELECT.
"""
import datetime
import json
import logging
import os
import time
import urllib.error
import urllib.request

import config
import memory

log = logging.getLogger("jarvis")

RADAR_SEC = 300
HIK_FROM, HIK_TO = datetime.time(10, 0), datetime.time(18, 30)
HIK_STALE_MIN = 120
AMO_STALE_MIN = 45
# leads_full sutkada 1 marta (backend AMO_FULL_RECONCILE_MS=24h) — 45 daq qoidasi yolg'on signal berdi
AMO_STALE_OVERRIDE = {"leads_full": 26 * 60}
ERR_MIN = 3
CONFIRM = {"api": 2, "db": 2}   # shuncha ketma-ket yiqilishdan keyin aytiladi

LABELS = {
    "api": "ERP prod API",
    "hik": "Hikvision davomat oqimi",
    "5xx": "ERP server xatolari",
    "db": "ERP prod bazasi",
}


def configured():
    return os.path.exists(config.ERP_ENV_PATH)


def _env():
    env = {}
    with open(config.ERP_ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _connect():
    import psycopg2
    e = _env()
    return psycopg2.connect(
        host=e["POSTGRES_HOST"], port=e["POSTGRES_PORT"], user=e["POSTGRES_USER"],
        password=e["POSTGRES_PASSWORD"], dbname=e["POSTGRES_DB"], connect_timeout=15,
        options="-c default_transaction_read_only=on -c statement_timeout=15000",
    )


def _fetch():
    """Bazadan xom ko'rsatkichlar (epoch soniyalarda)."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute('SELECT extract(epoch FROM max("createdAt")) FROM attendance_events')
        hik_last = cur.fetchone()[0]
        cur.execute("SELECT entity, extract(epoch FROM last_run_at), last_status, last_error "
                    "FROM amo_sync_state")
        amo = [{"entity": r[0], "last": float(r[1]) if r[1] is not None else None,
                "status": r[2], "error": r[3]} for r in cur.fetchall()]
        cur.execute("SELECT count(*), max(path) FROM activity_logs WHERE NOT ok AND status >= 500 "
                    "AND \"createdAt\" > now() - interval '15 minutes'")
        err_n, err_path = cur.fetchone()
        return {"hik_last": float(hik_last) if hik_last else None, "amo": amo,
                "err_n": int(err_n or 0), "err_path": err_path}
    finally:
        conn.close()


def _api_ok():
    try:
        urllib.request.urlopen(config.ERP_API_URL, timeout=20)
        return True, ""
    except urllib.error.HTTPError as e:
        return e.code < 500, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)[:80]


def _ago(sec):
    m = int(sec // 60)
    return f"{m // 60} soat {m % 60} daq" if m >= 60 else f"{m} daq"


def evaluate(now, api, data, data_err=""):
    """{kalit: muammo matni} — hozir mavjud muammolar (sof funksiya, sinash oson)."""
    ts = now.timestamp()
    out = {}
    ok, why = api
    if not ok:
        out["api"] = f"prod API javob bermayapti ({why})"
    if data is None:
        out["db"] = f"prod bazaga ulanib bo'lmadi ({data_err[:80]})"
        return out
    if (now.weekday() < 6 and HIK_FROM <= now.time() <= HIK_TO
            and (not data["hik_last"] or ts - data["hik_last"] > HIK_STALE_MIN * 60)):
        age = _ago(ts - data["hik_last"]) if data["hik_last"] else "hech qachon"
        out["hik"] = (f"ofis terminallaridan {age}dan beri birorta hodisa kelmadi — "
                      "Hikvision agenti yoki terminal to'xtagan bo'lishi mumkin")
    for a in data["amo"]:
        if a["status"] and a["status"] != "ok":
            out[f"amo:{a['entity']}"] = (f"amoCRM sinxroni ({a['entity']}) xato bilan: "
                                         f"{(a['error'] or a['status'])[:100]}")
        elif a["last"] and ts - a["last"] > AMO_STALE_OVERRIDE.get(a["entity"], AMO_STALE_MIN) * 60:
            out[f"amo:{a['entity']}"] = (f"amoCRM sinxroni ({a['entity']}) {_ago(ts - a['last'])}dan "
                                         "beri ishlamadi")
    if data["err_n"] >= ERR_MIN:
        out["5xx"] = f"oxirgi 15 daqiqada {data['err_n']} ta server xatosi (masalan {data['err_path']})"
    return out


def _state(chat_id):
    try:
        return json.loads(memory.get_setting(chat_id, "radar_state", "{}") or "{}")
    except ValueError:
        return {}


def step(chat_id, problems, now):
    """Holatni yangilaydi; yuboriladigan xabarlar ro'yxati."""
    ts = now.timestamp()
    state = _state(chat_id)
    msgs = []
    for key, text in problems.items():
        s = state.setdefault(key, {"since": ts, "count": 0, "alerted": False})
        s["count"] += 1
        s["text"] = text
        if not s["alerted"] and s["count"] >= CONFIRM.get(key, 1):
            s["alerted"] = True
            msgs.append(f"🛰 **ERP radar:** {text}")
    # Baza ochilmasa hik/amo/5xx ni bilmaymiz — ularni "tiklandi" deb hisoblamaymiz
    blind = "db" in problems
    for key in [k for k in state if k not in problems and not (blind and k not in ("api", "db"))]:
        s = state.pop(key)
        if s.get("alerted"):
            label = LABELS.get(key, key.replace("amo:", "amoCRM sinxroni: "))
            msgs.append(f"✅ **ERP radar:** {label} tiklandi ({_ago(ts - s['since'])} davom etdi)")
    memory.set_setting(chat_id, "radar_state", json.dumps(state))
    return msgs


def check(now=None):
    now = now or datetime.datetime.now()
    api = _api_ok()
    try:
        data, err = _fetch(), ""
    except Exception as e:
        data, err = None, str(e)
    return evaluate(now, api, data, err)


def tick(chat_id, now=None):
    """Radar job: muammolarni tekshirib, yangi/tiklangan holatlar haqida xabarlar."""
    if not configured() or memory.get_setting(chat_id, "radar_on", "1") != "1":
        return []
    now = now or datetime.datetime.now()
    return step(chat_id, check(now), now)


def status_text(chat_id):
    if not configured():
        return f"🛰 ERP radar o'chiq: {config.ERP_ENV_PATH} topilmadi."
    on = memory.get_setting(chat_id, "radar_on", "1") == "1"
    now = datetime.datetime.now()
    t0 = time.time()
    problems = check(now)
    lines = [f"🛰 **ERP radar** {'yoqilgan' if on else 'o‘chirilgan'} · har {RADAR_SEC // 60} daqiqada "
             f"(tekshiruv {time.time() - t0:.1f} s)"]
    if problems:
        lines += [f"🔴 {t}" for t in problems.values()]
    else:
        lines.append("✅ Prod API, Hikvision oqimi, amoCRM sinxroni, server xatolari — hammasi joyida.")
    lines.append("\n/radar off|on")
    return "\n".join(lines)
