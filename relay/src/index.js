// FRIDAY relay — kompyuter o'chiq bo'lsa ham FRIDAY BOTI nomidan eslatma yuboradi.
//
// Bot faqat kompyuter yoniq paytda ishlaydi. Yoniq paytda u kelgusi xabarlar ro'yxatini
// shu yerga yuborib turadi (PUT /alerts). Har daqiqada cron vaqti kelganlarini Telegram
// Bot API orqali yuboradi. Bot yoniq bo'lsa, vaqtiga 3 daqiqa qolgan xabarni ro'yxatdan
// o'zi olib tashlaydi (o'zi yuboradi) — takror bo'lmaydi. Yuborilganlar GET /sent da:
// bot keyin yonganda ularni qayta yubormaydi.
//
// Sirlar (wrangler secret): BOT_TOKEN, OWNER_ID, SHARED_SECRET. Saqlash: KV (bitta "state" kaliti).

const MAX_LATE_SEC = 6 * 3600; // bundan eski xabar yuborilmaydi (masalan, relay o'chiq bo'lgan)
const SENT_KEEP_SEC = 3 * 86400;
const MAX_ITEMS = 300;

async function load(env) {
  const raw = await env.KV.get("state");
  return raw ? JSON.parse(raw) : { items: [], sent: {} };
}

function prune(sent, now) {
  const out = {};
  for (const [k, ts] of Object.entries(sent || {})) if (now - ts < SENT_KEEP_SEC) out[k] = ts;
  return out;
}

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });

async function sendTelegram(env, text) {
  const url = `https://api.telegram.org/bot${env.BOT_TOKEN}/sendMessage`;
  const base = { chat_id: env.OWNER_ID, disable_web_page_preview: true };
  let r = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ ...base, text, parse_mode: "HTML" }),
  });
  if (r.status === 400) {
    // HTML'ni Telegram rad etsa — belgilarsiz oddiy matn
    const plain = text.replace(/<[^>]+>/g, "");
    r = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...base, text: plain }),
    });
  }
  if (!r.ok) console.log("telegram xato", r.status, (await r.text()).slice(0, 200));
  return r.ok;
}

export async function runDue(env, now) {
  const state = await load(env);
  const items = state.items || [];
  const due = items.filter((i) => i.due <= now && i.due > now - MAX_LATE_SEC && !(state.sent || {})[i.key]);
  const expired = items.some((i) => i.due <= now - MAX_LATE_SEC);
  if (!due.length && !expired) return 0; // hech narsa o'zgarmadi — KV'ga yozmaymiz (bepul limit)
  const sent = state.sent || {};
  let n = 0;
  for (const i of due) {
    if (await sendTelegram(env, i.text)) {
      sent[i.key] = now;
      n++;
    }
  }
  state.sent = prune(sent, now);
  state.items = items.filter((i) => !state.sent[i.key] && i.due > now - MAX_LATE_SEC);
  await env.KV.put("state", JSON.stringify(state));
  return n;
}

export default {
  async fetch(req, env) {
    if (req.headers.get("x-friday-key") !== env.SHARED_SECRET) return json({ error: "forbidden" }, 403);
    const { pathname } = new URL(req.url);
    const now = Date.now() / 1000;
    if (req.method === "PUT" && pathname === "/alerts") {
      const body = await req.json();
      const state = await load(env);
      const sent = prune(state.sent, now);
      state.items = (body.items || [])
        .filter((i) => i && i.key && i.text && typeof i.due === "number" && !sent[i.key])
        .slice(0, MAX_ITEMS);
      state.sent = sent;
      state.pushed = now;
      await env.KV.put("state", JSON.stringify(state));
      return json({ ok: true, items: state.items.length });
    }
    if (req.method === "GET" && pathname === "/sent") {
      const state = await load(env);
      return json({ sent: prune(state.sent, now) });
    }
    if (req.method === "POST" && pathname === "/run") {
      // Tekshirish uchun: cron kutmasdan hozir vaqti kelganlarni yuborish
      return json({ ok: true, sent: await runDue(env, now) });
    }
    if (req.method === "GET" && pathname === "/health") {
      const state = await load(env);
      return json({ ok: true, items: (state.items || []).length, pushed: state.pushed || 0 });
    }
    return json({ error: "not found" }, 404);
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(runDue(env, Date.now() / 1000));
  },
};
