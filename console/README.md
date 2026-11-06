# Ziv console

The console is the surface for senders, caregivers and the wearer
(docs/ARCHITECTURE.md §8): send a message and see the exact words the relay
will play, follow utterances through the outbox, set the schedule, set pace
and advance mode, enroll devices, mint sender tokens, read health. It talks
to the relay's sender HTTP API (§6) and nothing else. **It never plays
haptics; it is not a renderer.**

It is a small TypeScript web application with no framework: plain DOM,
small modules, generated API types, an esbuild build with content-hashed
assets and a manifest, and a strict Content-Security-Policy (`'self'` only,
no inline scripts or handlers, no third-party code at runtime, no analytics).

Accessibility is the acceptance criterion. The wearer is deaf-blind; every
view must work with a screen reader and a refreshable braille display. The
checklist below is what the code does and what a reviewer checks by hand.

## Layout

```
console/
  package.json          scripts and pinned dev dependencies (nothing ships at runtime)
  tsconfig.json         strict, erasable-syntax-only TypeScript (Node runs the tests unbundled)
  src/
    main.ts             shell: banner, nav, main, live region, hash router
    router.ts           routes, titles, the View/AppContext contracts
    api.ts              the HTTP client: URLs, bearer header, error -> Reason mapping
    normalise.ts        local preview of the relay's text normalisation (letter count)
    dom.ts              h(), labelled field(), error slots, focus helpers
    announce.ts         the one polite live region
    session.ts          token in sessionStorage only
    format.ts, watch.ts
    views/              signin, send, utterances, schedule, prefs, devices, senders, health
    generated/wire.ts   GENERATED from ../schema/*.json (commit it; the build checks its hash)
    index.html          template; the build fills the CSP and hashed asset names
    styles.css
  scripts/
    gen-types.mjs       schema -> TypeScript (json-schema-to-typescript); --check compares the hash
    build.mjs           esbuild -> dist/ with [name]-[hash] files, manifest.json, index.html
    dev.mjs             watch build + the mock serving dist/ on one origin
  mock/server.mjs       in-memory stand-in for the relay API; validates bodies with Ajv
  test/                 node:test suites (API client, Send view in jsdom, axe-core smoke)
  dist/                 build output (gitignored)
```

## Build and run

Node 24 and npm. Dependencies are dev-only and pinned exactly.

```bash
cd console
npm ci                 # or npm install
npm run gen:types      # regenerate src/generated/wire.ts from ../schema/*.json
npm run typecheck      # tsc, no emit
npm test               # node --test: API client, Send view (jsdom), axe-core smoke
npm run build          # -> dist/: app-<hash>.js, styles-<hash>.css, manifest.json, index.html
npm run dev            # watch build + mock relay at http://127.0.0.1:8787/
npm run mock           # the mock alone (ZIV_MOCK_PORT, ZIV_MOCK_STATIC=dist to also serve the build)
```

`npm run build` fails when `src/generated/wire.ts` is stale: the generator
records a SHA-256 over `schema/` in the file header and the build compares
it. After `python -m ziv.wire schema/` changes a schema, run
`npm run gen:types` and commit both.

The dev mock accepts three tokens: `admin-token` (everything, including
`/devices/enroll-code` and `/senders`), `send-token` (scopes send and read)
and `read-token` (read only). Override with `ZIV_MOCK_ADMIN_TOKEN`,
`ZIV_MOCK_SEND_TOKEN`, `ZIV_MOCK_READ_TOKEN`. `ZIV_MOCK_ADVANCE_MS` paces the
simulated pending → sent → playing → played progression (0 disables it);
`ZIV_MOCK_BUDGET_MS` sets the time budget (default 30 000 ms).

### Pointing it at a relay

`dist/` is static. By default the console calls the **same origin** it was
served from (`/utterances`, `/prefs`, ...), so the simplest deployment is for
the relay to serve `dist/` itself, or for a reverse proxy to put both behind
one host. To call a relay on another origin, set the base at build time:

```bash
ZIV_CONSOLE_API_BASE=https://relay.example.net npm run build
```

The build bakes the origin into the bundle and adds it to the CSP
`connect-src`; the relay must then answer CORS preflights for
`Authorization` and `Content-Type`. Nothing is read from the URL or from
`localStorage` at runtime; the token is pasted on the Sign in view and held
in `sessionStorage` for that tab only. **Forget this token** in the banner
clears it at any time.

Serve `index.html` and `manifest.json` with `Cache-Control: no-cache` and the
hashed files as immutable; the mock does exactly that when given
`ZIV_MOCK_STATIC=dist`.

## Routes the console speaks

Bodies are the JSON Schemas in `../schema/`; `src/generated/wire.ts` is their
TypeScript. Every error body is `{"reason": <Reason>, "detail": string, ...}`
and the client maps it to an `ApiError` with the reason, the status and any
extra fields (`budget_ms`, `cap`).

| Method and path | Needs | Body / answer |
|---|---|---|
| `POST /utterances` | send | `http-submit-utterance` → 201 `http-utterance-view`; 413 `over_budget`, 429 `queue_full`, 422 `unencodable` or `bad_request` |
| `POST /compose` | send | `http-compose` (`intent`, `kind`, `label`, `expires_after_s`) → 201 `http-utterance-view` once the agent has composed: `source` is `live` when a model wrote the line, `echo` when the relay had no model and played the intent as typed; `state` is `failed` with `reason: compose_failed` when no line fit. Optional header `X-Nebius-Key`: the sender's own model credential, used for that one compose and kept nowhere |
| `GET /utterances?state=<state>` | read | list of `http-utterance-view` |
| `GET /utterances/{id}` | read | `http-utterance-view` |
| `DELETE /utterances/{id}` | send | cancel; the view in its new state (or 204) |
| `POST /schedule` | send | `http-schedule` → 201 `http-schedule-view`; 429 at the cap |
| `GET /schedule` | read | list of `http-schedule-view` |
| `DELETE /schedule/{id}` | send | 204 |
| `GET /prefs` | read | `http-prefs` |
| `PUT /prefs` | send | `http-prefs`; the relay clamps `pace_ms` into the spec envelope and returns what it stored |
| `GET /devices` | read | list of `http-device-view` |
| `POST /devices/enroll-code` | admin | `{"code": string, "expires": datetime}` |
| `POST /senders` | admin | `{"label", "scopes": ["send","read"]}` → `{"token", ...}` with `sender` or `id`; shown once |
| `GET /spec` | any token | the timing spec; the console reads only `constants.cell_gap_{min,max,default}_ms` and `ui.cell_gap_step_ms` for the pace field |
| `GET /health` | public | `http-health`, counts only |

Auth is `Authorization: Bearer <token>`. 401 and 403 both map to the
`unauthorized` reason and are shown as such; the console never guesses a
token's scopes, it shows the relay's refusal. `describeReason()` in
`src/api.ts` has a sentence for every `Reason` the schema carries; the
typecheck fails when the schema grows a reason the console cannot name.

### Send: type the words, or ask the agent

The Send view has two modes. **Type the words** posts `POST /utterances`
and shows the exact normalised words. **Ask the agent** posts an intent to
`POST /compose` (docs/ARCHITECTURE.md §4.5): the relay admits a
`body_pending` utterance at once, so the wearer feels the cue and the
working pattern while the line is composed, and the answer carries the
composed words with their `source`. The result names the source in plain
words (`live: a model wrote the line` / `echo: your words, played as typed`),
so the console never implies a model ran when it did not. The optional
**Use my own Token Factory key** field sends the key in the `X-Nebius-Key`
header of that one request and nothing else; the field is emptied as soon
as the request is sent, whatever the outcome, and the console keeps no copy.

## Accessibility checklist

What the code does, and what to check by hand with a screen reader (NVDA or
VoiceOver) and, when available, a braille display. The automated part is
`test/a11y.test.ts`: axe-core over every view, including the Send view with
an error and with a result, the enroll code and the created token, with zero
violations at the serious and critical levels.

Structure
- [ ] One `<header role="banner">`, one `<nav aria-label="Console">`, one `<main>`, one footer; a "Skip to content" link is the first focusable thing.
- [ ] Exactly one `<h1>` per view; sections have `<h2>` and `aria-labelledby`.
- [ ] Opening a view moves focus to its `<h1>` and sets `document.title` ("Send – Ziv console"); the current nav link has `aria-current="page"`.
- [ ] Tables have a `<caption>`, `<th scope="col">` headers and a `<th scope="row">` on the words/time column so a cell is read with its row.

Controls and forms
- [ ] Every input, select and textarea has an explicit `<label for>`; every button has visible text (and `aria-label` only to add the row's words, e.g. "Cancel: meds nine").
- [ ] Required fields carry `required` and `aria-required`; hints are tied with `aria-describedby`.
- [ ] Field errors set `aria-invalid="true"`, are prefixed "Error:", and are added to that field's `aria-describedby`; form-level errors are tied to the form the same way. Focus moves to the first field with a problem.
- [ ] The letter count under the message is **not** a live region (typing would flood the display); it is described by the textarea and read on focus.
- [ ] Buttons go `aria-disabled` while a request is in flight instead of `disabled`, so focus is never dropped mid-submit; repeat presses are ignored.
- [ ] No hover-only, drag or timing-dependent interaction; nothing auto-dismisses. Codes and tokens stay on screen until the view changes.

Announcements (one `role="status"`, `aria-live="polite"`, `aria-atomic` region)
- [ ] Announced: the result of something the user did (sent, cancelled, saved, deleted, copied, refreshed, signed in), its errors, and state changes of utterances the user sent or cancelled in this tab.
- [ ] Not announced: polling results, letter counts, route changes (focus on the heading does that), anything the user did not ask for. A repeat of the same text within a second is dropped.
- [ ] Messages are short and front-loaded: "Sent: meds nine. 13 s of 30 s. pending." / "Error: Too long for the time budget. ..." Codes are announced letter by letter.

Polling (Utterances, every 4 s)
- [ ] Pauses while the tab is hidden (`visibilitychange`), resumes with an immediate refresh.
- [ ] Updates rows in place and only when they changed; a row that contains focus is left alone until focus leaves; rows are never reordered while focus is inside the table. Polling never calls `focus()`.
- [ ] Cancelling moves focus to the row's State cell before the Cancel button disappears.

Visual
- [ ] Rem units throughout; 200% text zoom reflows (no fixed heights, tables scroll horizontally in their own region).
- [ ] Colour is never the only signal: states are words, errors say "Error:", primary/connected are "Yes"/"No", invalid fields change border style not only colour.
- [ ] `:focus-visible` outline plus a contrasting ring on every control; `forced-colors` and `prefers-color-scheme: dark` handled; `prefers-reduced-motion` disables the (already minimal) transitions.
- [ ] Contrast meets AA on the default palette (axe cannot check this in jsdom; check in a browser).

Security and privacy on the client
- [ ] CSP: `default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self' [+ the configured relay]`; no inline scripts, styles or event handler attributes.
- [ ] Token in `sessionStorage` only, never in the URL, a cookie or `localStorage`; "Forget this token" is always visible when signed in.
- [ ] Requests use `credentials: "omit"` and `cache: "no-store"`; `referrer` is `no-referrer`.
- [ ] Tokens and enroll codes are shown once, as selectable plain text in a read-only field with a Copy button; the console keeps no copy.

## Tests

`npm test` runs, with node's built-in runner and no real-time sleeps (waits
are on conditions):

- `test/api.test.ts` — the client against the mock: URL building, the bearer header (absent for `/health`), the local refusal when signed out, 201 echo of normalised words, 422/413/429/401/403 mapped to reasons, cap and cancel, schedule, pref clamping, admin routes, network and non-JSON failures.
- `test/send.test.ts` — the Send view in jsdom: the letter count, a submit rendering words/budget/state and announcing once, an unencodable error rendered into the error slot (associated via `aria-describedby`) and the polite live region, over-budget and unauthorized errors; the Ask-the-agent mode (intent posted, key in the header only and cleared, `source` shown as echo or live).
- `test/a11y.test.ts` — the whole shell: landmarks, headings, focus, labels on every control, captions on every table, axe-core with zero serious/critical violations, and polling that never moves focus.

The mock validates every request body against the schemas with Ajv and
checks its own `UtteranceView`, `ScheduleView`, `DeviceView` and `Health`
answers against theirs, so a console that drifts from the contract fails
here before it meets the relay.
