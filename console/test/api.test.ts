import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { createMockServer } from "../mock/server.mjs";
import { Api, ApiError, paceEnvelope, reasonForStatus } from "../src/api.ts";

type Mock = ReturnType<typeof createMockServer>;
let mock: Mock;
let origin: string;

before(async () => {
  mock = createMockServer({ advanceMs: 0, budgetMs: 30000 });
  origin = await mock.listen(0);
});
after(async () => {
  await mock.close();
});

const api = (token: string | null): Api => new Api({ baseUrl: origin, token: () => token });

test("url building: base without trailing slash, query only when set", () => {
  const a = new Api({ baseUrl: `${origin}/` });
  assert.equal(a.url("/utterances"), `${origin}/utterances`);
  assert.equal(a.url("/utterances", { state: "pending" }), `${origin}/utterances?state=pending`);
  assert.equal(a.url("/utterances", { state: undefined }), `${origin}/utterances`);
  assert.equal(a.url("/utterances", { state: "" }), `${origin}/utterances`);
});

test("auth header is sent as Bearer and omitted for health", async () => {
  let seen: string | null | undefined;
  const spy: typeof fetch = async (input, init) => {
    const headers = new Headers(init?.headers);
    seen = headers.get("authorization");
    return fetch(input, init);
  };
  const withToken = new Api({ baseUrl: origin, token: () => "send-token", fetch: spy });
  await withToken.listUtterances();
  assert.equal(seen, "Bearer send-token");
  await withToken.getHealth();
  assert.equal(seen, null);
});

test("signed out: request refused locally with unauthorized, no round trip", async () => {
  let called = false;
  const spy: typeof fetch = async (input, init) => {
    called = true;
    return fetch(input, init);
  };
  const a = new Api({ baseUrl: origin, token: () => null, fetch: spy });
  await assert.rejects(a.getPrefs(), (err: unknown) => err instanceof ApiError && err.reason === "unauthorized" && err.status === 0);
  assert.equal(called, false);
});

test("submit: 201 echoes normalised words, duration and budget", async () => {
  const view = await api("send-token").submitUtterance({ text: "Meds at 9, don't forget!" });
  assert.deepEqual(view.words, ["meds", "at", "nine", "dont", "forget"]);
  assert.equal(view.state, "pending");
  assert.equal(view.budget_ms, 30000);
  assert.ok(view.duration_ms > 0 && view.duration_ms <= view.budget_ms);
  const again = await api("read-token").getUtterance(view.id);
  assert.equal(again.id, view.id);
});

test("errors map to reasons: 422 unencodable, 413 over_budget, 403/401 unauthorized, 422 bad_request", async () => {
  await assert.rejects(api("send-token").submitUtterance({ text: "mañana" }), (err: unknown) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.status, 422);
    assert.equal(err.reason, "unencodable");
    assert.match(err.detail, /no braille cell/);
    return true;
  });
  await assert.rejects(api("send-token").submitUtterance({ text: "abcdefghij ".repeat(40) }), (err: unknown) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.status, 413);
    assert.equal(err.reason, "over_budget");
    assert.equal(typeof err.extra["budget_ms"], "number");
    return true;
  });
  await assert.rejects(api("read-token").submitUtterance({ text: "hello" }), (err: unknown) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.status, 403);
    assert.equal(err.reason, "unauthorized");
    return true;
  });
  await assert.rejects(api("nope").listUtterances(), (err: unknown) => err instanceof ApiError && err.status === 401 && err.reason === "unauthorized");
  await assert.rejects(api("send-token").request("/utterances", { method: "POST", body: { text: "x", bogus: 1 } }), (err: unknown) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.status, 422);
    assert.equal(err.reason, "bad_request");
    assert.match(err.detail, /additional properties/);
    return true;
  });
});

test("429 queue_full at the cap, then cancel frees a slot", async () => {
  mock.reset();
  const a = api("send-token");
  const ids: string[] = [];
  for (let i = 0; i < 8; i += 1) ids.push((await a.submitUtterance({ text: `m${i}` })).id);
  await assert.rejects(a.submitUtterance({ text: "one more" }), (err: unknown) => err instanceof ApiError && err.status === 429 && err.reason === "queue_full");
  const cancelled = await a.cancelUtterance(ids[0] as string);
  assert.equal(cancelled?.state, "cancelled");
  assert.equal(cancelled?.reason, "cancelled_by_sender");
  const pending = await a.listUtterances("pending");
  assert.equal(pending.length, 7);
  const all = await a.listUtterances();
  assert.equal(all.length, 8);
  await a.submitUtterance({ text: "fits now" });
});

test("schedule: add, list, delete; text xor intent enforced", async () => {
  mock.reset();
  const a = api("send-token");
  const fireAt = new Date(Date.now() + 3_600_000).toISOString();
  const created = await a.addSchedule({ fire_at: fireAt, intent: "pills", kind: "reminder", expires_after_s: 600 });
  assert.equal(created.composed, true);
  assert.equal(created.label, "pills");
  assert.equal((await a.listSchedule()).length, 1);
  await assert.rejects(a.addSchedule({ fire_at: fireAt, text: "a", intent: "b" }), (err: unknown) => err instanceof ApiError && err.reason === "bad_request");
  await assert.rejects(a.addSchedule({ fire_at: fireAt }), (err: unknown) => err instanceof ApiError && err.reason === "bad_request");
  await a.deleteSchedule(created.id);
  assert.equal((await a.listSchedule()).length, 0);
  await assert.rejects(a.deleteSchedule(created.id), (err: unknown) => err instanceof ApiError && err.status === 404);
});

test("prefs: PUT is clamped into the spec envelope and returns stored values", async () => {
  mock.reset();
  const a = api("send-token");
  const spec = await a.getSpec();
  const env = paceEnvelope(spec);
  const stored = await a.putPrefs({ pace_ms: 1999, advance: "tap", late: "play", history: true });
  assert.equal(stored.pace_ms, env.max);
  assert.equal(stored.advance, "tap");
  assert.equal(stored.late, "play");
  assert.equal(stored.history, true);
  const got = await a.getPrefs();
  assert.deepEqual(got, stored);
  await assert.rejects(a.putPrefs({ pace_ms: 5 }), (err: unknown) => err instanceof ApiError && err.status === 422);
});

test("admin routes: enroll code and sender creation need the admin token", async () => {
  await assert.rejects(api("send-token").createEnrollCode(), (err: unknown) => err instanceof ApiError && err.status === 403 && err.reason === "unauthorized");
  const code = await api("admin-token").createEnrollCode();
  assert.match(code.code, /^[0-9A-Z]{6,12}$/);
  assert.ok(Date.parse(code.expires) > Date.now());
  const created = await api("admin-token").createSender({ label: "mum", scopes: ["send"] });
  assert.ok(created.token.length > 20);
  assert.ok(created.id ?? created.sender);
  // the new token works with exactly its scopes
  await api(created.token).submitUtterance({ text: "hi" });
  await assert.rejects(api(created.token).listUtterances(), (err: unknown) => err instanceof ApiError && err.status === 403);
  await assert.rejects(api("admin-token").createSender({ label: "", scopes: [] }), (err: unknown) => err instanceof ApiError && err.reason === "bad_request");
});

test("health is public and counts only; devices list has a primary", async () => {
  const health = await api(null).getHealth();
  assert.equal(health.status, "ok");
  assert.equal(typeof health.outbox["pending"], "number");
  const devices = await api("read-token").listDevices();
  assert.equal(devices.filter((d) => d.primary).length, 1);
});

test("network failure and non-JSON answers are labelled, not swallowed", async () => {
  const dead = new Api({ baseUrl: "http://127.0.0.1:1", token: () => "x" });
  await assert.rejects(dead.getPrefs(), (err: unknown) => err instanceof ApiError && err.reason === "network" && err.status === 0);
  const weird: typeof fetch = async () => new Response("<html>nope</html>", { status: 502, statusText: "Bad Gateway" });
  const a = new Api({ baseUrl: origin, token: () => "x", fetch: weird });
  await assert.rejects(a.getPrefs(), (err: unknown) => err instanceof ApiError && err.reason === "unexpected" && err.status === 502 && /nope/.test(err.detail));
  assert.equal(reasonForStatus(404), "not_found");
  assert.equal(reasonForStatus(409), "conflict");
  assert.equal(reasonForStatus(422), "bad_request");
  assert.equal(reasonForStatus(500), "unexpected");
});
