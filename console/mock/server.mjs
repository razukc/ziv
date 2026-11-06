#!/usr/bin/env node
// A development stand-in for the relay's sender HTTP API (docs/ARCHITECTURE.md §6).
//
// In-memory state, the same routes, status codes and error shapes the relay
// will serve, and every request body validated against ../../schema/*.json
// with Ajv, so the console cannot drift from the contract while the real
// relay is being written. Not a relay: nothing is persisted and the outbox
// "plays" on a timer.
//
//   node mock/server.mjs                      API on 127.0.0.1:8787
//   ZIV_MOCK_STATIC=dist node mock/server.mjs  also serve the built console
//
// Tokens (override with ZIV_MOCK_ADMIN_TOKEN / ZIV_MOCK_SEND_TOKEN / ZIV_MOCK_READ_TOKEN):
//   admin-token   admin: everything, including /devices/enroll-code and /senders
//   send-token    sender with scopes send + read
//   read-token    sender with scope read only

import { createServer } from "node:http";
import { randomBytes, timingSafeEqual } from "node:crypto";
import { readFileSync, existsSync, statSync } from "node:fs";
import { dirname, join, resolve, extname, normalize } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { normalise } from "../src/normalise.ts";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..", "..");
const schemaDir = join(repoRoot, "schema");
const specPath = join(repoRoot, "docs", "haptic-timing.json");

const MAX_BODY_BYTES = 64 * 1024;
const OUTBOX_CAP = 8;
const SCHEDULE_CAP = 64;
const ENROLL_CODE_TTL_MS = 10 * 60 * 1000;
const STATES = ["pending", "sent", "playing", "played", "failed", "expired", "cancelled"];
const ACTIVE = new Set(["pending", "sent", "playing"]);

// --- schemas ----------------------------------------------------------------

const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
function loadValidator(name) {
  return ajv.compile(JSON.parse(readFileSync(join(schemaDir, `${name}.json`), "utf8")));
}
const validators = {
  submit: loadValidator("http-submit-utterance"),
  utteranceView: loadValidator("http-utterance-view"),
  schedule: loadValidator("http-schedule"),
  scheduleView: loadValidator("http-schedule-view"),
  prefs: loadValidator("http-prefs"),
  enroll: loadValidator("http-enroll"),
  enrollResponse: loadValidator("http-enroll-response"),
  deviceView: loadValidator("http-device-view"),
  health: loadValidator("http-health"),
};

function problem(status, reason, detail, extra = {}) {
  return { status, body: { reason, detail, ...extra } };
}

function validate(validator, body) {
  if (validator(body)) return null;
  const text = ajv.errorsText(validator.errors, { dataVar: "body" });
  return problem(422, "bad_request", text);
}

// --- timing (an approximation; the reference renderer owns the real one) -----

function durationMs(spec, words, paceMs, withPrefix) {
  const c = spec.constants;
  let total = withPrefix ? c.prefix_breath_ms + c.long_buzz_ms + c.tail_gap_ms : 0;
  words.forEach((word, wi) => {
    if (wi > 0) total += paceMs * 2; // word gap: spec work; the mock uses two cell gaps
    [...word].forEach((letter, li) => {
      if (li > 0) total += paceMs;
      const dots = spec.letters[letter] ?? 3;
      total += c.cell_base_ms + c.cell_per_dot_ms * dots;
    });
  });
  total += c.long_buzz_ms; // close
  return total;
}

// --- the server --------------------------------------------------------------

export function createMockServer(options = {}) {
  const spec = options.spec ?? JSON.parse(readFileSync(specPath, "utf8"));
  const budgetMs = options.budgetMs ?? Number(process.env.ZIV_MOCK_BUDGET_MS ?? 30000);
  const advanceMs = options.advanceMs ?? Number(process.env.ZIV_MOCK_ADVANCE_MS ?? 2500);
  const cors = options.cors ?? process.env.ZIV_MOCK_CORS === "1";
  const staticDir = options.staticDir ?? (process.env.ZIV_MOCK_STATIC ? resolve(process.env.ZIV_MOCK_STATIC) : null);
  const adminToken = options.adminToken ?? process.env.ZIV_MOCK_ADMIN_TOKEN ?? "admin-token";
  const log = options.log ?? (() => {});

  const envelope = {
    min: spec.constants.cell_gap_min_ms,
    max: spec.constants.cell_gap_max_ms,
    dflt: spec.constants.cell_gap_default_ms,
  };

  const state = {
    senders: new Map(), // token -> { sender, label, scopes }
    utterances: new Map(), // id -> view (+ hidden fields)
    schedule: [],
    nextScheduleId: 1,
    nextSenderN: 1,
    prefs: { pace_ms: envelope.dflt, advance: "auto", late: "drop", history: false },
    devices: [],
    enrollCodes: new Map(), // code -> expires ms
    timers: new Set(),
    counters: { refused: 0, expired: 0, cancelled: 0 },
  };

  function reset() {
    for (const t of state.timers) clearTimeout(t);
    state.timers.clear();
    state.senders.clear();
    state.senders.set(options.sendToken ?? process.env.ZIV_MOCK_SEND_TOKEN ?? "send-token", {
      sender: "s_console",
      label: "console",
      scopes: ["send", "read"],
    });
    state.senders.set(options.readToken ?? process.env.ZIV_MOCK_READ_TOKEN ?? "read-token", {
      sender: "s_reader",
      label: "reader",
      scopes: ["read"],
    });
    state.utterances.clear();
    state.schedule = [];
    state.nextScheduleId = 1;
    state.nextSenderN = 1;
    state.prefs = { pace_ms: envelope.dflt, advance: "auto", late: "drop", history: false };
    state.devices = [
      { device: "d_band", name: "Band", profile: "six_actuator", primary: true, connected: true, last_seen: nowIso() },
      { device: "d_phone", name: "Phone", profile: "single_actuator", primary: false, connected: false, last_seen: null },
    ];
    state.enrollCodes.clear();
    state.counters = { refused: 0, expired: 0, cancelled: 0 };
  }
  reset();

  // --- auth ---------------------------------------------------------------

  function tokenOf(req) {
    const header = req.headers["authorization"];
    if (typeof header !== "string") return null;
    const m = /^Bearer\s+(\S+)$/i.exec(header.trim());
    return m ? m[1] : null;
  }
  function same(a, b) {
    const ba = Buffer.from(a);
    const bb = Buffer.from(b);
    return ba.length === bb.length && timingSafeEqual(ba, bb);
  }
  function principal(req) {
    const token = tokenOf(req);
    if (!token) return null;
    if (same(token, adminToken)) return { kind: "admin", scopes: ["send", "read", "admin"] };
    for (const [t, s] of state.senders) if (same(token, t)) return { kind: s.scopes.includes("admin") ? "admin" : "sender", ...s };
    return null;
  }
  function requireScope(req, scope) {
    const who = principal(req);
    if (!who) return { error: problem(401, "unauthorized", "missing or unknown bearer token") };
    if (scope && !who.scopes.includes(scope)) {
      return { error: problem(403, "unauthorized", `this token lacks the ${scope} scope`) };
    }
    return { who };
  }

  // --- outbox -----------------------------------------------------------

  function nowIso() {
    return new Date().toISOString();
  }
  function activeCount() {
    let n = 0;
    for (const u of state.utterances.values()) if (ACTIVE.has(u.state)) n += 1;
    return n;
  }
  function publicView(u) {
    const { _expiresMs, _notBeforeMs, ...view } = u;
    return view;
  }
  function transition(u, next, reason = null) {
    u.state = next;
    u.reason = reason;
    u.updated = nowIso();
    if (next === "sent" || next === "playing") {
      u.device = state.devices.find((d) => d.primary && d.connected)?.device ?? u.device ?? null;
    }
  }
  function schedulePlayback(u) {
    if (advanceMs <= 0) return;
    const step = () => {
      state.timers.delete(timer);
      if (!ACTIVE.has(u.state)) return;
      const now = Date.now();
      if (u._expiresMs !== null && now > u._expiresMs && u.state !== "playing") {
        if (state.prefs.late === "drop") {
          state.counters.expired += 1;
          transition(u, "expired", "expired");
          return;
        }
      }
      if (u._notBeforeMs !== null && now < u._notBeforeMs) {
        arm(Math.min(u._notBeforeMs - now, 60_000));
        return;
      }
      const primary = state.devices.find((d) => d.primary && d.connected);
      if (!primary) {
        arm(advanceMs);
        return;
      }
      if (u.state === "pending") transition(u, "sent");
      else if (u.state === "sent") transition(u, "playing");
      else if (u.state === "playing") transition(u, "played");
      if (ACTIVE.has(u.state)) arm(u.state === "playing" ? Math.min(u.duration_ms, 6000) : advanceMs);
    };
    let timer;
    const arm = (ms) => {
      timer = setTimeout(step, ms);
      timer.unref?.();
      state.timers.add(timer);
    };
    arm(advanceMs);
  }

  function admit(body, who, kindDefault) {
    let words;
    if (body.words) {
      words = body.words;
    } else {
      const n = normalise(body.text, Boolean(body.allow_lossy));
      if (!n.ok) {
        state.counters.refused += 1;
        return { error: problem(n.reason === "over_budget" ? 413 : 422, n.reason, n.detail) };
      }
      words = n.words;
      if (words.length === 0) {
        state.counters.refused += 1;
        return { error: problem(422, "unencodable", "nothing left to spell after normalisation") };
      }
    }
    const kind = body.kind ?? kindDefault;
    // every sender utterance is unsolicited, so the prefix (mark + tail) always plays
    const duration = durationMs(spec, words, state.prefs.pace_ms, true);
    if (duration > budgetMs) {
      state.counters.refused += 1;
      return {
        error: problem(413, "over_budget", `this would take ${duration} ms; the budget is ${budgetMs} ms at the current pace`, {
          duration_ms: duration,
          budget_ms: budgetMs,
        }),
      };
    }
    if (activeCount() >= OUTBOX_CAP) {
      state.counters.refused += 1;
      return { error: problem(429, "queue_full", `the outbox holds ${OUTBOX_CAP} waiting utterances; try again when one has played`, { cap: OUTBOX_CAP }) };
    }
    const notBefore = body.not_before ? Date.parse(body.not_before) : null;
    const expires = body.expires ? Date.parse(body.expires) : null;
    if (notBefore !== null && expires !== null && expires <= notBefore) {
      return { error: problem(422, "bad_request", "expires must be after not_before") };
    }
    const created = nowIso();
    const view = {
      id: randomBytes(16).toString("base64url"),
      state: "pending",
      kind,
      words,
      source: who?.kind === "agent" ? "echo" : "sender",
      duration_ms: duration,
      budget_ms: budgetMs,
      device: null,
      reason: null,
      created,
      updated: created,
      _expiresMs: expires,
      _notBeforeMs: notBefore,
    };
    if (!validators.utteranceView(publicView(view))) {
      throw new Error(`mock produced an invalid UtteranceView: ${ajv.errorsText(validators.utteranceView.errors)}`);
    }
    state.utterances.set(view.id, view);
    schedulePlayback(view);
    return { view };
  }

  // --- routes ---------------------------------------------------------------

  async function handleApi(req, url, readBody) {
    const method = req.method ?? "GET";
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const seg = path.split("/").slice(1);

    if (path === "/health" && method === "GET") {
      const outbox = Object.fromEntries(STATES.map((s) => [s, 0]));
      for (const u of state.utterances.values()) outbox[u.state] += 1;
      const body = {
        status: "ok",
        version: "mock-0.1.0",
        spec_version: spec.version,
        wire_version: 1,
        devices_connected: state.devices.filter((d) => d.connected).length,
        outbox,
        schedule_pending: state.schedule.length,
        caps: { outbox: OUTBOX_CAP, schedule: SCHEDULE_CAP, words: 64, text: 500, budget_ms: budgetMs, ...state.counters },
        compose: { last: "none", source: "echo" },
      };
      if (!validators.health(body)) throw new Error(ajv.errorsText(validators.health.errors));
      return { status: 200, body };
    }

    if (path === "/devices/enroll" && method === "POST") {
      const body = await readBody();
      if (body.error) return body.error;
      const bad = validate(validators.enroll, body.json);
      if (bad) return bad;
      const exp = state.enrollCodes.get(body.json.code);
      if (!exp || exp < Date.now()) return problem(401, "unauthorized", "unknown or expired enrollment code");
      state.enrollCodes.delete(body.json.code);
      const device = `d_${randomBytes(4).toString("hex")}`;
      state.devices.push({ device, name: body.json.name, profile: body.json.profile, primary: false, connected: false, last_seen: null });
      const resp = { device, device_key: randomBytes(24).toString("base64url") };
      if (!validators.enrollResponse(resp)) throw new Error(ajv.errorsText(validators.enrollResponse.errors));
      return { status: 201, body: resp };
    }

    // Everything below is authenticated.
    if (path === "/spec" && method === "GET") {
      const a = requireScope(req, null);
      if (a.error) return a.error;
      return { status: 200, body: spec };
    }

    if (seg[0] === "utterances") {
      if (seg.length === 1 && method === "POST") {
        const a = requireScope(req, "send");
        if (a.error) return a.error;
        const body = await readBody();
        if (body.error) return body.error;
        const bad = validate(validators.submit, body.json);
        if (bad) return bad;
        if (Boolean(body.json.text) === Boolean(body.json.words)) {
          return problem(422, "bad_request", "provide text or words, exactly one");
        }
        const r = admit(body.json, a.who, "message");
        if (r.error) return r.error;
        return { status: 201, body: publicView(r.view) };
      }
      if (seg.length === 1 && method === "GET") {
        const a = requireScope(req, "read");
        if (a.error) return a.error;
        const want = url.searchParams.get("state");
        if (want !== null && !STATES.includes(want)) {
          return problem(422, "bad_request", `state must be one of ${STATES.join(", ")}`);
        }
        const list = [...state.utterances.values()]
          .filter((u) => want === null || u.state === want)
          .sort((x, y) => (x.created < y.created ? 1 : -1))
          .map(publicView);
        return { status: 200, body: list };
      }
      if (seg.length === 2) {
        const id = decodeURIComponent(seg[1]);
        const u = state.utterances.get(id);
        if (method === "GET") {
          const a = requireScope(req, "read");
          if (a.error) return a.error;
          if (!u) return problem(404, "bad_request", "no such utterance");
          return { status: 200, body: publicView(u) };
        }
        if (method === "DELETE") {
          const a = requireScope(req, "send");
          if (a.error) return a.error;
          if (!u) return problem(404, "bad_request", "no such utterance");
          if (!ACTIVE.has(u.state)) return problem(409, "bad_request", `already ${u.state}; nothing to cancel`);
          state.counters.cancelled += 1;
          transition(u, "cancelled", "cancelled_by_sender");
          return { status: 200, body: publicView(u) };
        }
      }
    }

    if (seg[0] === "schedule") {
      if (seg.length === 1 && method === "GET") {
        const a = requireScope(req, "read");
        if (a.error) return a.error;
        const list = [...state.schedule].sort((x, y) => (x.fire_at < y.fire_at ? -1 : 1));
        return { status: 200, body: list };
      }
      if (seg.length === 1 && method === "POST") {
        const a = requireScope(req, "send");
        if (a.error) return a.error;
        const body = await readBody();
        if (body.error) return body.error;
        const bad = validate(validators.schedule, body.json);
        if (bad) return bad;
        if (Boolean(body.json.text) === Boolean(body.json.intent)) {
          return problem(422, "bad_request", "provide text or intent, exactly one");
        }
        if (body.json.text) {
          const n = normalise(body.json.text, false);
          if (!n.ok) return problem(n.reason === "over_budget" ? 413 : 422, n.reason, n.detail);
        }
        if (state.schedule.length >= SCHEDULE_CAP) {
          return problem(429, "queue_full", `the schedule holds ${SCHEDULE_CAP} entries`, { cap: SCHEDULE_CAP });
        }
        const label = (body.json.intent ?? body.json.text).slice(0, 40);
        const view = {
          id: state.nextScheduleId++,
          fire_at: new Date(Date.parse(body.json.fire_at)).toISOString(),
          kind: body.json.kind ?? "reminder",
          composed: Boolean(body.json.intent),
          label,
        };
        if (!validators.scheduleView(view)) throw new Error(ajv.errorsText(validators.scheduleView.errors));
        state.schedule.push(view);
        return { status: 201, body: view };
      }
      if (seg.length === 2 && method === "DELETE") {
        const a = requireScope(req, "send");
        if (a.error) return a.error;
        const id = Number(seg[1]);
        const i = state.schedule.findIndex((s) => s.id === id);
        if (i < 0) return problem(404, "bad_request", "no such schedule entry");
        state.schedule.splice(i, 1);
        return { status: 204 };
      }
    }

    if (path === "/prefs") {
      if (method === "GET") {
        const a = requireScope(req, "read");
        if (a.error) return a.error;
        return { status: 200, body: { ...state.prefs } };
      }
      if (method === "PUT") {
        const a = requireScope(req, "send");
        if (a.error) return a.error;
        const body = await readBody();
        if (body.error) return body.error;
        const bad = validate(validators.prefs, body.json);
        if (bad) return bad;
        const next = { ...state.prefs };
        for (const k of ["pace_ms", "advance", "late", "history"]) {
          if (body.json[k] !== undefined && body.json[k] !== null) next[k] = body.json[k];
        }
        next.pace_ms = Math.min(envelope.max, Math.max(envelope.min, next.pace_ms));
        state.prefs = next;
        return { status: 200, body: { ...state.prefs } };
      }
    }

    if (path === "/devices" && method === "GET") {
      const a = requireScope(req, "read");
      if (a.error) return a.error;
      for (const d of state.devices) if (!validators.deviceView(d)) throw new Error(ajv.errorsText(validators.deviceView.errors));
      return { status: 200, body: state.devices };
    }

    if (path === "/devices/enroll-code" && method === "POST") {
      const a = requireScope(req, "admin");
      if (a.error) return a.error;
      const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
      const bytes = randomBytes(8);
      let code = "";
      for (const b of bytes) code += alphabet[b % alphabet.length];
      const expiresMs = Date.now() + ENROLL_CODE_TTL_MS;
      state.enrollCodes.set(code, expiresMs);
      return { status: 201, body: { code, expires: new Date(expiresMs).toISOString() } };
    }

    if (path === "/senders" && method === "POST") {
      // Body per ziv/wire.py CreateSender: label, scopes (send|read|admin),
      // optional rate_per_min. Answer per SenderView, token shown once.
      const a = requireScope(req, "admin");
      if (a.error) return a.error;
      const body = await readBody();
      if (body.error) return body.error;
      const j = body.json;
      const SCOPES = ["send", "read", "admin"];
      const okLabel = j && typeof j.label === "string" && j.label.trim().length >= 1 && j.label.length <= 40;
      const okScopes =
        j && Array.isArray(j.scopes) && j.scopes.length >= 1 && j.scopes.every((s) => SCOPES.includes(s)) && new Set(j.scopes).size === j.scopes.length;
      const okRate = j && (j.rate_per_min === undefined || (Number.isInteger(j.rate_per_min) && j.rate_per_min >= 1 && j.rate_per_min <= 6000));
      const extraKeys = j && typeof j === "object" ? Object.keys(j).filter((k) => !["label", "scopes", "rate_per_min"].includes(k)) : ["body"];
      if (!okLabel || !okScopes || !okRate || extraKeys.length > 0) {
        return problem(422, "bad_request", 'body must be {"label": string (1-40), "scopes": non-empty subset of ["send","read","admin"], "rate_per_min"?: 1-6000}');
      }
      const id = `s_${state.nextSenderN++}`;
      const token = `zs_${randomBytes(24).toString("base64url")}`;
      const scopes = [...j.scopes];
      state.senders.set(token, { sender: id, label: j.label.trim(), scopes });
      return { status: 201, body: { id, label: j.label.trim(), scopes, rate_per_min: j.rate_per_min ?? 60, created: nowIso(), token } };
    }

    return null;
  }

  // --- static files (the built console, for `npm run dev`) -------------------

  const MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
  };
  function serveStatic(req, url, res) {
    if (!staticDir || (req.method !== "GET" && req.method !== "HEAD")) return false;
    let rel = decodeURIComponent(url.pathname);
    if (rel === "/" || rel === "") rel = "/index.html";
    const file = normalize(join(staticDir, rel));
    if (!file.startsWith(staticDir) || !existsSync(file) || !statSync(file).isFile()) return false;
    const type = MIME[extname(file)] ?? "application/octet-stream";
    const hashed = /-[A-Z0-9]{8}\.(js|css|map)$/.test(file);
    res.writeHead(200, {
      "Content-Type": type,
      "Cache-Control": hashed ? "public, max-age=31536000, immutable" : "no-cache",
      "X-Content-Type-Options": "nosniff",
    });
    if (req.method === "HEAD") res.end();
    else res.end(readFileSync(file));
    return true;
  }

  // --- plumbing ------------------------------------------------------------

  const server = createServer(async (req, res) => {
    const url = new URL(req.url ?? "/", "http://mock");
    const baseHeaders = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
    if (cors) {
      baseHeaders["Access-Control-Allow-Origin"] = "*";
      baseHeaders["Access-Control-Allow-Headers"] = "Authorization, Content-Type";
      baseHeaders["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS";
      if (req.method === "OPTIONS") {
        res.writeHead(204, baseHeaders);
        res.end();
        return;
      }
    }
    const send = (status, body) => {
      if (body === undefined) {
        res.writeHead(status, baseHeaders);
        res.end();
      } else {
        res.writeHead(status, { ...baseHeaders, "Content-Type": "application/json; charset=utf-8" });
        res.end(JSON.stringify(body));
      }
      log(`${req.method} ${url.pathname}${url.search} -> ${status}`);
    };
    const readBody = () =>
      new Promise((resolveBody) => {
        const chunks = [];
        let size = 0;
        req.on("data", (c) => {
          size += c.length;
          if (size <= MAX_BODY_BYTES) chunks.push(c);
        });
        req.on("end", () => {
          if (size > MAX_BODY_BYTES) {
            resolveBody({ error: problem(413, "bad_request", `body over ${MAX_BODY_BYTES} bytes`) });
            return;
          }
          const text = Buffer.concat(chunks).toString("utf8");
          if (text.length === 0) {
            resolveBody({ error: problem(422, "bad_request", "a JSON body is required") });
            return;
          }
          try {
            resolveBody({ json: JSON.parse(text) });
          } catch {
            resolveBody({ error: problem(422, "bad_request", "body is not valid JSON") });
          }
        });
        req.on("error", () => resolveBody({ error: problem(400, "bad_request", "could not read the body") }));
      });

    try {
      const result = await handleApi(req, url, readBody);
      if (result) {
        send(result.status, result.body);
        return;
      }
      if (serveStatic(req, url, res)) return;
      send(404, { reason: "bad_request", detail: `no route ${req.method} ${url.pathname}` });
    } catch (err) {
      send(500, { reason: "bad_request", detail: `mock failure: ${err instanceof Error ? err.message : String(err)}` });
    }
  });

  return {
    server,
    state,
    reset,
    listen(port = 0, host = "127.0.0.1") {
      return new Promise((resolveListen) => {
        server.listen(port, host, () => {
          const addr = server.address();
          resolveListen(`http://${host}:${typeof addr === "object" && addr ? addr.port : port}`);
        });
      });
    },
    close() {
      for (const t of state.timers) clearTimeout(t);
      state.timers.clear();
      return new Promise((resolveClose) => {
        server.closeAllConnections?.();
        server.close(() => resolveClose());
      });
    },
  };
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isMain) {
  const port = Number(process.env.ZIV_MOCK_PORT ?? 8787);
  const host = process.env.ZIV_MOCK_HOST ?? "127.0.0.1";
  const mock = createMockServer({ log: (line) => console.log(`[mock] ${line}`) });
  const origin = await mock.listen(port, host);
  console.log(`[mock] relay stand-in on ${origin}`);
  console.log(`[mock] tokens: admin-token, send-token, read-token (see mock/server.mjs)`);
  if (process.env.ZIV_MOCK_STATIC) console.log(`[mock] serving ${resolve(process.env.ZIV_MOCK_STATIC)} at /`);
  const stop = () => mock.close().then(() => process.exit(0));
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
}
