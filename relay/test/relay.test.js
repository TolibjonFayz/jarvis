// node --test test/  — KV va Telegram soxta, tarmoqqa chiqilmaydi
import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { runDue } from "../src/index.js";

function makeEnv() {
  const store = new Map();
  return {
    SHARED_SECRET: "s3cret",
    BOT_TOKEN: "123:abc",
    OWNER_ID: "42",
    writes: 0,
    KV: {
      async get(k) { return store.has(k) ? store.get(k) : null; },
      async put(k, v) { this.parent.writes++; store.set(k, v); },
    },
  };
}

function env() {
  const e = makeEnv();
  e.KV.parent = e;
  return e;
}

const req = (method, path, body, key = "s3cret") =>
  new Request(`https://relay.test${path}`, {
    method,
    headers: { "x-friday-key": key, "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });

function mockTelegram(status = 200) {
  const calls = [];
  globalThis.fetch = async (url, opts) => {
    calls.push({ url, body: JSON.parse(opts.body) });
    return new Response("{}", { status: typeof status === "function" ? status(calls.length) : status });
  };
  return calls;
}

test("rejects wrong key", async () => {
  const r = await worker.fetch(req("GET", "/health", null, "bad"), env());
  assert.equal(r.status, 403);
});

test("sends due items once, as the bot, and reports them in /sent", async () => {
  const e = env();
  const now = Math.floor(Date.now() / 1000);
  await worker.fetch(req("PUT", "/alerts", { items: [
    { key: "rem:1", due: now - 10, text: "⏰ <b>Dori</b>" },
    { key: "rem:2", due: now + 600, text: "keyin" },
  ] }), e);
  const calls = mockTelegram();
  assert.equal(await runDue(e, now), 1);
  assert.equal(calls[0].body.chat_id, "42");
  assert.equal(calls[0].body.parse_mode, "HTML");
  assert.match(calls[0].url, /bot123:abc\/sendMessage/);
  assert.equal(await runDue(e, now + 30), 0);                  // takror yo'q
  const sent = await (await worker.fetch(req("GET", "/sent"), e)).json();
  assert.deepEqual(Object.keys(sent.sent), ["rem:1"]);
  // bot qayta yuklasa ham yuborilgan qaytib kirmaydi
  await worker.fetch(req("PUT", "/alerts", { items: [{ key: "rem:1", due: now - 10, text: "x" }] }), e);
  assert.equal(await runDue(e, now + 60), 0);
});

test("no KV write when nothing is due (free-tier limit)", async () => {
  const e = env();
  await worker.fetch(req("PUT", "/alerts", { items: [{ key: "a", due: 5000, text: "x" }] }), e);
  const before = e.writes;
  mockTelegram();
  await runDue(e, 1000);
  assert.equal(e.writes, before);
});

test("too-late items are dropped, not sent", async () => {
  const e = env();
  await worker.fetch(req("PUT", "/alerts", { items: [{ key: "old", due: 0, text: "x" }] }), e);
  const calls = mockTelegram();
  await runDue(e, 7 * 3600);
  assert.equal(calls.length, 0);
  const h = await (await worker.fetch(req("GET", "/health"), e)).json();
  assert.equal(h.items, 0);
});

test("falls back to plain text when HTML is rejected", async () => {
  const e = env();
  await worker.fetch(req("PUT", "/alerts", { items: [{ key: "a", due: 10, text: "<b>buzuq" }] }), e);
  const calls = mockTelegram((n) => (n === 1 ? 400 : 200));
  assert.equal(await runDue(e, 20), 1);
  assert.equal(calls[1].body.parse_mode, undefined);
  assert.equal(calls[1].body.text, "buzuq");
});

test("failed send is retried next minute", async () => {
  const e = env();
  await worker.fetch(req("PUT", "/alerts", { items: [{ key: "a", due: 10, text: "x" }] }), e);
  mockTelegram(500);
  assert.equal(await runDue(e, 20), 0);
  mockTelegram(200);
  assert.equal(await runDue(e, 80), 1);
});
