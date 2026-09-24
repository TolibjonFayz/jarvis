"""Miya: Groq'ni chaqiradi. Token tejash uchun 2 fazali + kategoriyali tool'lar:

Faza 1 (router, tool'siz, arzon) — oddiy suhbat shu yerda tugaydi.
  Tool kerak bo'lsa model <TOOL:kategoriya> deb belgi qaytaradi.
Faza 2 (tool bilan) — FAQAT kerakli kategoriya tool'lari yuboriladi
  (hamma 15 ta emas — bu eng katta token tejash).
"""
import re
import json
import logging
import datetime

from groq import Groq, RateLimitError

import brain
import memory
from config import GROQ_API_KEY, MODEL, MAX_TOKENS
from tools import FINAL, TOOLS, execute_tool

log = logging.getLogger("jarvis")

# max_retries=0: 429 da kutmasdan darhol zaxira modelga o'tamiz.
client = Groq(api_key=GROQ_API_KEY, max_retries=0) if GROQ_API_KEY else None

# Zaxira zanjiri: asosiy model chegarasi (kunlik/daqiqalik) tugasa,
# keyingisiga o'tamiz. Groq'da har model uchun ALOHIDA tekin budjet bor.
MODEL_CHAIN = [
    MODEL,
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


# /status uchun: bot ishga tushgandan beri qaysi model necha marta chaqirildi.
STATS = {"calls": {}, "rate_limited": {}, "last_model": None}


def _create(**kwargs):
    """Chaqiruv: 429 bo'lsa zanjirdagi keyingi modelga o'tadi."""
    last_err = None
    for m in MODEL_CHAIN:
        try:
            resp = client.chat.completions.create(model=m, **kwargs)
            STATS["calls"][m] = STATS["calls"].get(m, 0) + 1
            STATS["last_model"] = m
            return resp
        except RateLimitError as e:
            STATS["rate_limited"][m] = STATS["rate_limited"].get(m, 0) + 1
            last_err = e
            continue
    raise last_err


def _clean(text):
    """qwen kabi modellarning <think> bloklarini olib tashlaydi."""
    return _THINK_RE.sub("", text or "").strip()

# Router javobi (Faza 1) uchun kichikroq chegara — Groq max_tokens'ni ham
# daqiqalik budjetga qo'shib hisoblaydi.
ROUTER_MAX_TOKENS = min(384, MAX_TOKENS)

# Tool ta'riflarini OpenAI/Groq formatiga bir marta o'giramiz.
_tools = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in TOOLS
]

# Kategoriya -> tool nomlari. Router qaysi kategoriya keragini aytadi,
# Faza 2 faqat o'shalarni yuboradi (token tejash).
TOOL_CATEGORIES = {
    "web": ["web_search", "get_weather", "get_currency", "read_url"],
    "tg": [
        "tg_chats", "tg_read", "tg_send", "tg_leave", "tg_pin",
        "unanswered", "set_unanswered_alerts",
    ],
    "dayjest": ["digest_add", "digest_remove", "digest_list", "digest_now", "set_digest"],
    "file": ["read_file", "write_file", "list_files", "run_command"],
    "esl": [
        "set_reminder", "list_reminders", "set_prayer_reminders",
        "set_daily_prayers", "set_morning_brief",
        "set_recurring_reminder", "list_recurring", "cancel_recurring", "cancel_reminder",
    ],
    "todo": ["add_todo", "list_todos", "complete_todo"],
    "pul": [
        "add_expense", "expense_report", "list_expenses", "delete_expense",
        "set_budget", "budget_status",
    ],
    "xot": ["remember", "recall", "forget"],
    "loyiha": ["projects_list", "project_status", "project_changes"],
    "kal": ["agenda", "calendar_events", "calendar_add", "calendar_delete"],
}

_TOOL_RE = re.compile(r"<\s*TOOL\s*:?\s*([a-z, ]*)>?", re.IGNORECASE)

# Tool nomi -> kategoriyasi (router xatosidan kategoriya aniqlash uchun).
_TOOL2CAT = {t: c for c, ts in TOOL_CATEGORIES.items() for t in ts}

# Pul xabarlari ("taksi 25 ming", "obed 45k", "bu oy qancha sarfladim") routerni
# chetlab to'g'ri "pul" tool'lariga boradi: router tarixdagi "✅ yozildi"
# javoblariga taqlid qilib, tool chaqirmasdan yolg'on tasdiq berardi.
_MONEY_RE = re.compile(
    r"\d[\d\s.,]*\s*(k|ming|mln|million|milion|som|sum)\b|xarajat|sarfla|sarf\b|b[yi]?udjet",
    re.IGNORECASE,
)
_APOS_RE = re.compile(r"['‘’ʻʼ`]")

# Router tool'siz shunday desa — bajarmasdan "bajardim" deyapti (gallyutsinatsiya).
_CLAIM_RE = re.compile(
    r"✅|qo.?shildi|yozildi|o.?chirildi|saqlandi|belgilandi|qo.?yildi",
    re.IGNORECASE,
)

# Router bularni tool'siz "bilgandek" javob berib, kanal nomlarini o'ylab topardi —
# kalit so'z bo'lsa routerni chetlab, to'g'ri shu kategoriyalarga.
_FORCED_ROUTES = [
    # "bu hafta nima bor?" — router tool'siz javob berib, yo'q eslatmani o'ylab topdi.
    (re.compile(r"nima bor|rejam|rejalarim|kun tartib|band\s*(man|emas)|bo.?sh vaqt", re.IGNORECASE), ["kal"]),
    (re.compile(r"\bpin\b|pin qil|chiqib ket|dan chiq|tark et", re.IGNORECASE), ["tg"]),
    (re.compile(r"dayjest|daydjest|digest|kanal", re.IGNORECASE), ["dayjest", "tg"]),
    # "todolarni o'chir" — egasi takroriy eslatmalarni ham "todo" deydi: ikkalasi birga.
    (re.compile(r"eslatma|todo|to-do|vazifa", re.IGNORECASE), ["esl", "todo"]),
    (re.compile(r"javob berma|javobsiz|javob kut", re.IGNORECASE), ["tg"]),
    (re.compile(r"loyiha|\brepo|commit|\bgit\b|branch|nima qildim", re.IGNORECASE), ["loyiha"]),
    (re.compile(r"kalendar|calendar|taqvim|uchrashuv|meeting|tadbir|\bmajlis", re.IGNORECASE), ["kal"]),
]

# Tool loop'da: javob amal bajarilganini aytsa, shunday tool chaqirilgan bo'lishi SHART.
_ACTION_CLAIM_RE = re.compile(
    r"qo.?shildi|yozildi|o.?chirildi|saqlandi|belgilandi|qo.?yildi|bajarildi|"
    r"bekor qilindi|yuborildi|pin qilindi|chiqildi",
    re.IGNORECASE,
)
_MUTATING = (
    "add_", "set_", "cancel_", "complete_", "delete_", "digest_add", "digest_remove",
    "calendar_add", "calendar_delete", "tg_send", "tg_leave", "tg_pin", "forget", "remember",
)

# Egasi biror narsani O'ZGARTIRISHni so'rayapti — ro'yxat ko'rish oraliq qadam bo'ladi.
_MUTATE_INTENT_RE = re.compile(
    r"o.?chir|qo.?sh|bekor|olib tashla|chiqib ket|dan chiq|\bpin|unut|belgila|bajardim|"
    r"qilib bo.?ldim|tozala|yoq\b|yoqib|o.?zgartir|ko.?chir",
    re.IGNORECASE,
)

_REMEMBER_RE = re.compile(r"eslab qol|esda tut|esingda tut|yodda tut|yodingda tut", re.IGNORECASE)


def _trim_history(msgs, each=500):
    """Eski xabarlarni qisqartiradi — to'liq matn tarixda shart emas."""
    return [
        {"role": m["role"], "content": (m["content"] or "")[:each]}
        for m in msgs
    ]


_WEEKDAYS = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]

# Modelga beriladigan oxirgi xabarlar soni; undan eskisi brain xulosasida.
HISTORY_WINDOW = 6


def build_system(chat_id, user_text, router=False):
    """Qisqa system prompt. router=True bo'lsa kategoriya tanlash yo'rig'i qo'shiladi."""
    mems = brain.relevant_facts(user_text)
    mem_text = "; ".join(mems) if mems else "yo'q"
    summ = brain.summary(chat_id)
    dt = datetime.datetime.now()
    now = f"{dt:%Y-%m-%d %H:%M}, {_WEEKDAYS[dt.weekday()]}"
    base = (
        "Sen FRIDAY — shaxsiy AI yordamchisan (Iron Man'dagi F.R.I.D.A.Y. uslubi: xotirjam, "
        "aniq, ozgina hazilkash). HAR DOIM o'zbek tilida javob ber (egang boshqa til so'ramasa), "
        "do'stona. Ismingni so'rashsa — FRIDAY. "
        f"Hozir: {now}. "
        "Telegram chat: qisqa va foydali yoz. Formatlash: **qalin**, `kod`, ```kod bloki```, "
        "'- ' ro'yxat mumkin; jadval ISHLATMA. Qalinni kam ishlat (sarlavha yoki eng muhim so'z). "
        "Egangning shaxsiy Telegramini o'qiy olasan; xabar yuborishni tg_send tayyorlaydi, "
        "foydalanuvchi TUGMA bilan tasdiqlaydi (o'zing tasdiq so'rama). "
        "Fayl o'qish: D:\\Tolibjon ichida; yozish/buyruq: faqat workspace. "
        "Imkoniyatlaring FAQAT shular (boshqasini va'da qilma): suhbat/kod, fayl, xotira, "
        "internet qidiruv/havola o'qish, ob-havo, valyuta kursi, eslatma/namoz/tonggi brifing, "
        "todo, xarajat hisobi, shaxsiy Telegram o'qish/yuborish, ovozli xabar, hujjat xulosasi, "
        "guruh moderatsiyasi, rasm ko'rish (rasm yuborilsa tavsifi [qavs] ichida keladi). "
        f"Foydalanuvchi (egang) haqida bilganlaring: {mem_text}. "
        "Sen suhbatdan faktlarni FONDA O'ZING eslab qolasan — 'eslab qol deb ayting' "
        "deb SO'RAMA. Bilmagan narsangni o'ylab topma. "
    )
    if summ:
        base += f"Oldingi suhbat xulosasi: {summ} "
    if router:
        base += (
            "\n\nMUHIM: tool kerak bo'lsa boshqa HECH NARSA yozma, faqat <TOOL:kat> yoz. "
            "kat: web=internet qidiruv/ob-havo/valyuta kursi/havola(URL) o'qish, "
            "tg=shaxsiy Telegram suhbat/xabar/kimga javob bermadim/kanal-guruhdan chiqish/pin, "
            "dayjest=Telegram KANALLAR dayjesti (kanal qo'sh/olib tashla/ro'yxat/hozir ko'rsat/vaqti), "
            "file=fayl/kod yozish/buyruq bajarish, "
            "esl=eslatma/namoz/avto-namoz/tonggi brifing/takroriy eslatma, "
            "todo=vazifalar ro'yxati (qo'shish/ko'rish/bajarildi), "
            "pul=xarajat yozish/hisobot/o'chirish/oylik budjet (masalan 'taksi 25 ming', 'obed 45k', "
            "'bu oy qancha sarfladim'), "
            "kal=Google Calendar va kun tartibi (tadbir ko'rish/qo'shish/o'chirish, 'bugun nima bor'), "
            "loyiha=egangning KOD loyihalari/git (ERP, Climavent, bilim manba, fit-uz, "
            "shelf-sort...): holati, 'ERPda bugun nima o'zgardi', 'bugun nima qildim', "
            "xot=FAQAT aniq buyruq: 'eslab qol', 'unut', 'men haqimda nima bilasan'. "
            "O'zi haqida gapirsa (ukam..., men ... yoqtiraman, ... ishlayapman) tool KERAK "
            "EMAS — oddiy javob ber, fakt fonda o'zi saqlanadi. "
            "Bir nechtasi kerak bo'lsa vergul bilan: <TOOL:web,esl>. "
            "Kurs, ob-havo, narx, yangilik, sana-vaqtga bog'liq DOLZARB raqamlarni "
            "HECH QACHON o'zingdan aytma — bilmaysan, <TOOL:web> yoz. "
            "Aks holda (suhbat, savol, maslahat) to'g'ridan-to'g'ri QISQA javob ber."
        )
    return base


def _subset_tools(cats):
    """Kategoriyalarga mos tool'larni qaytaradi; noaniq bo'lsa hammasini."""
    allowed = set()
    for c in cats:
        allowed.update(TOOL_CATEGORIES.get(c, []))
    if not allowed:
        return _tools
    return [t for t in _tools if t["function"]["name"] in allowed]


_NOT_EXPENSE = {
    "type": "function",
    "function": {
        "name": "not_expense",
        "description": "Xabar xarajat yoki budjet haqida EMAS bo'lsa",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def _salvaged_calls(err):
    """Groq sxema tekshiruvida rad etgan chaqiruvni xato javobidan tiklaydi.

    Model to'g'ri tool va argumentni tanlagan, faqat bitta maydon mos
    kelmagan bo'lsa (masalan null) — chaqiruvni tashlab yubormaymiz.
    """
    body = getattr(err, "body", None)
    if not isinstance(body, dict):
        return []
    gen = (body.get("error") or {}).get("failed_generation") or ""
    try:
        data = json.loads(gen)
    except Exception:
        return []
    items = data if isinstance(data, list) else [data]
    calls = []
    for it in items:
        if not isinstance(it, dict) or not it.get("name"):
            continue
        args = it.get("arguments") or it.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        calls.append((it["name"], args if isinstance(args, dict) else {}))
    return calls


def _money_flow(chat_id, user_text):
    """Pul xabari: model FAQAT tool tanlaydi, javob = tool natijasi so'zma-so'z.

    Model natijani o'z so'zi bilan qayta aytganda summalarni buzardi
    (1 390 000 -> "1 365 000"), pulda bu yaramaydi. Bot javoblari berilmaydi —
    unda eski "✅" javoblar bor, model ularga taqlid qiladi; faqat oldingi
    2 ta SAVOL kontekst uchun beriladi ("batafsil chiqar" kabi davomlar uchun).
    Xabar aslida pul haqida bo'lmasa — None (oddiy yo'lga qaytadi).
    """
    now = datetime.datetime.now()
    prev = [
        m["content"][:200]
        for m in memory.get_history(chat_id, limit=6)
        if m["role"] == "user"
    ][-2:]
    system = (
        f"Bugun {now:%Y-%m-%d} ({now:%A}). Foydalanuvchi xabarini xarajat "
        "tool'iga aylantir. Summalar so'mda."
    )
    if prev:
        system += " Oldingi savollari (kontekst): " + " | ".join(prev)
    try:
        resp = _create(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            tools=_subset_tools(["pul"]) + [_NOT_EXPENSE],
            tool_choice="required",
            max_tokens=min(768, MAX_TOKENS),
        )
        calls = []
        for tc in resp.choices[0].message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            calls.append((tc.function.name, args))
    except Exception as e:
        calls = _salvaged_calls(e)
        if not calls:
            log.warning("Pul oqimi ishlamadi, oddiy yo'lga o'tildi: %s", str(e)[:200])
            return None
    if not calls or any(name == "not_expense" for name, _ in calls):
        return None
    results = []
    for name, args in calls:
        args = {k: v for k, v in args.items() if v is not None}
        results.append(execute_tool(name, args, chat_id))
    return "\n\n".join(results)


def _tool_loop(chat_id, history, user_text, cats):
    """Faza 2: tool aylanmasi — faqat kerakli kategoriya tool'lari bilan."""
    tools = _subset_tools(cats)
    if not _REMEMBER_RE.search(_APOS_RE.sub("", user_text)):
        # Oddiy "ukam Aziz..." gapida model remember'ni o'zi chaqirib, faktni
        # "men/mening" shaklida, hammasini muhim deb saqlardi. Buni fondagi
        # brain.extract qiladi; remember faqat aniq buyruqda beriladi.
        tools = [t for t in tools if t["function"]["name"] != "remember"] or None
    messages = [{"role": "system", "content": build_system(chat_id, user_text)}]
    messages += history
    messages.append({"role": "user", "content": user_text})

    tool_kw = {"tools": tools, "tool_choice": "auto"} if tools else {}
    final = ""
    last_result = ""
    mutated = False   # o'zgartiruvchi tool (qo'shish/o'chirish...) chaqirildimi
    nudged = False
    pending_final = ""  # oraliq FINAL ro'yxat (o'zgartirish so'ralganda)
    allowed = {t["function"]["name"] for t in tools or []}
    for step in range(15):
        # calls: [(id, name, arguments_json)]; content: modelning matni
        try:
            resp = _create(messages=messages, max_tokens=MAX_TOKENS, **tool_kw)
            msg = resp.choices[0].message
            content = msg.content
            calls = [(tc.id, tc.function.name, tc.function.arguments) for tc in msg.tool_calls or []]
        except Exception as e:
            s = str(e)
            if "tool_use_failed" in s:
                # Model tool'ni buzib chaqirdi — niyati xato javobida bor, o'shani bajaramiz.
                # (Avval tool'siz qayta so'ralardi; model yana tool chaqirib, bot yiqilardi.)
                salv = [(n, a) for n, a in _salvaged_calls(e) if n in allowed]
                if salv:
                    calls = [(f"salv{step}_{i}", n, json.dumps(a)) for i, (n, a) in enumerate(salv)]
                    content = ""
                else:
                    try:
                        content = _create(messages=messages, max_tokens=MAX_TOKENS).choices[0].message.content
                    except Exception as e2:
                        if "tool_use_failed" not in str(e2):
                            raise
                        content = "⚠️ So'rovni tushunishda xato bo'ldi. Boshqacharoq aytib ko'r."
                    calls = []
            elif "output_parse_failed" in s:
                # Model mulohazasida adashdi — bir marta qayta urinamiz.
                msg = _create(messages=messages, max_tokens=MAX_TOKENS, **tool_kw).choices[0].message
                content = msg.content
                calls = [(tc.id, tc.function.name, tc.function.arguments) for tc in msg.tool_calls or []]
            else:
                raise

        if calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": content or "",
                    "tool_calls": [
                        {"id": cid, "type": "function", "function": {"name": name, "arguments": arguments}}
                        for cid, name, arguments in calls
                    ],
                }
            )
            for cid, name, arguments in calls:
                try:
                    args = json.loads(arguments or "{}")
                except Exception:
                    args = {}
                result = execute_tool(name, args, chat_id)
                log.info("tool %s %s -> %s", name, json.dumps(args, ensure_ascii=False)[:200],
                         result.replace(FINAL, "")[:80].replace("\n", " | "))
                is_mut = name.startswith(_MUTATING)
                mutated = mutated or is_mut
                if result.startswith(FINAL):
                    result = result[len(FINAL):]
                    # Tayyor javob (dayjest, ro'yxat) — model qayta yozsa havolalar/
                    # raqamlar buziladi, shuning uchun so'zma-so'z. Lekin "o'chir/qo'sh"
                    # so'ralgan bo'lsa ro'yxat faqat ORALIQ qadam — to'xtamaymiz
                    # (aks holda ro'yxatni ko'rsatib, o'chirmay qolardi).
                    if is_mut or not _MUTATE_INTENT_RE.search(user_text):
                        return result
                    pending_final = result
                last_result = result
                messages.append(
                    {"role": "tool", "tool_call_id": cid, "content": result}
                )
            continue

        final = _clean(content)
        if tools and not mutated and _ACTION_CLAIM_RE.search(final):
            if not nudged:
                # "O'chirildi/qo'shildi" dedi, lekin o'zgartiruvchi tool chaqirmadi
                # (masalan list_todos'ni ko'rib "o'chirildi" derdi). Bir marta qayta.
                nudged = True
                messages.append({"role": "assistant", "content": final})
                messages.append({
                    "role": "user",
                    "content": "[Tizim] Sen hech narsani o'zgartiruvchi tool chaqirmading — amal "
                               "BAJARILMADI. Kerakli tool'ni chaqir yoki bajara olmasligingni halol ayt.",
                })
                continue
            final = (
                "⚠️ Buni bajara olmadim — hech narsa o'zgarmadi. Aniqroq aytib ko'r "
                "(masalan: «takroriy eslatmalarni hammasini o'chir»)."
            )
        break

    if pending_final and not mutated:
        # Ro'yxat ko'rsatildi, lekin hech narsa o'zgarmadi (masalan "qaysi birini?"
        # deb so'radi) — ro'yxat so'zma-so'z + modelning savoli.
        return pending_final + (f"\n\n{final}" if final else "")
    # Tool ishladi-yu, model javob yozmadi — hech bo'lmasa natijani ko'rsatamiz.
    return final or last_result


def respond(chat_id, user_text, route_text=None):
    """Bitta xabarga javob. Avval arzon router, kerak bo'lsa kategoriyali tool aylanmasi.

    route_text: pul yo'nalishini shu matn bo'yicha aniqlash (rasmda — faqat
    egasining izohi; aks holda chekdagi "so'm" so'zidan o'zi xarajat yozardi).
    """
    history = _trim_history(memory.get_history(chat_id, limit=HISTORY_WINDOW))

    route = user_text if route_text is None else route_text
    if _MONEY_RE.search(_APOS_RE.sub("", route)):
        final = _money_flow(chat_id, user_text)
        if final is not None:
            memory.add_message(chat_id, "user", user_text)
            memory.add_message(chat_id, "assistant", final)
            brain.after_turn(chat_id, HISTORY_WINDOW)
            return final

    forced = next((cats for rx, cats in _FORCED_ROUTES if rx.search(route)), None)
    if not forced:
        import projects
        if projects.mentioned(route):
            forced = ["loyiha"]
    if forced:
        final = _tool_loop(chat_id, history, user_text, forced)
        memory.add_message(chat_id, "user", user_text)
        memory.add_message(chat_id, "assistant", final)
        brain.after_turn(chat_id, HISTORY_WINDOW)
        return final or "(javob bo'sh chiqdi)"

    # --- Faza 1: arzon, tool'siz router ---
    p1_messages = [{"role": "system", "content": build_system(chat_id, user_text, router=True)}]
    p1_messages += history
    p1_messages.append({"role": "user", "content": user_text})

    try:
        r1 = _create(messages=p1_messages, max_tokens=ROUTER_MAX_TOKENS)
        text1 = _clean(r1.choices[0].message.content)
    except Exception as e:
        s = str(e)
        # Ikkala holat ham "tool kerak" degani:
        #  - tool_use_failed: model marker o'rniga tool chaqirdi
        #  - output_parse_failed: model mulohazasida adashdi (odatda tool haqida)
        if "tool_use_failed" not in s and "output_parse_failed" not in s:
            raise
        # Xato matnidan kategoriyani topishga urinamiz:
        cat = ""
        mm = _TOOL_RE.search(s)  # ichida <TOOL:tg> yozilgan bo'lishi mumkin
        if mm and mm.group(1):
            c = mm.group(1).split(",")[0].strip().lower()
            if c in TOOL_CATEGORIES:
                cat = c
        if not cat:
            nm = re.search(r'"name":\s*"(\w+)"', s)
            name = (nm.group(1).lower() if nm else "")
            cat = name if name in TOOL_CATEGORIES else _TOOL2CAT.get(name, "")
        text1 = f"<TOOL:{cat}>"

    m = _TOOL_RE.search(text1)
    if text1 and not m and _CLAIM_RE.search(text1):
        # Tool'siz "qo'shildi/yozildi" — ishonmaymiz, "yozadigan" tool'lar bilan
        # qayta (hammasi ~3800 token bo'lib, daqiqalik limitni urardi).
        final = _tool_loop(chat_id, history, user_text, ["esl", "todo", "xot"])
    elif text1 and not m:
        final = text1  # Oddiy suhbat — shu yerda tugadi (arzon).
    else:
        cats = []
        if m and m.group(1):
            cats = [c.strip().lower() for c in m.group(1).split(",")]
        final = _tool_loop(chat_id, history, user_text, cats)

    memory.add_message(chat_id, "user", user_text)
    memory.add_message(chat_id, "assistant", final)
    brain.after_turn(chat_id, HISTORY_WINDOW)
    return final or "(javob bo'sh chiqdi)"
