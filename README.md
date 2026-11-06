# Ziv — a haptic message channel

**Messages you can feel. No screen, no speaker.** Ziv plays what arrives for
you as vibration on your skin: who is speaking, an arrival cue, the words
spelled as braille cells, and a felt close that says "finished". A relay
decides what plays and in what order; a device on your body keeps the rhythm
and reports back when the message has been felt. Today that device is a web
page on a phone, the reference renderer. The wrist band's firmware plays the
same timeline and is proven on the host, not yet on a board.

Ziv (a working title — see [Naming](#naming)) is built for deaf-blind
people, who have combined hearing and vision loss and for whom neither a
screen nor a speaker is a channel. It is also for anyone who wants a reply that
is quiet, glance-free, and private by physics: nothing to overhear, nothing to
look at.

> The product plan lives in [docs/HAPTIC_COMPANION_PLAN.md](docs/HAPTIC_COMPANION_PLAN.md)
> — the problem, the device concept, the interaction invariants, and the
> milestones. The software architecture is
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); the tree now implements it.
> What is planned next is in [docs/ROADMAP.md](docs/ROADMAP.md).

## Try it

- **[Feel-tool](https://site-5505fea77ec84b4f8e1a5d70c82d5877.freebuff.page)**
  — the interactive source of Ziv's timing rules and attention vocabulary:
  name-mark cards, the full alphabet, a spell box, an M1 recognition session
  and a blind A/B mode. Nothing to install, no relay, no key. Plays on Android
  Chrome; desktop and iOS show the visual rhythm only. The page is
  [docs/haptic-name-marks.html](docs/haptic-name-marks.html), generated from
  the same spec the firmware uses.
- **The relay, the console and the web renderer** — run the
  [quick start](#quick-start) below, enroll a browser as a device, and send
  yourself a message from the console. The web renderer vibrates only while
  its page is visible; it is a foreground demo of the device contract, and it
  has not yet been exercised in a real browser on a phone.

Afterwards we want to hear from you: did the close feel like an ending, and is
the reading pace bearable? Those are the two decisions currently open.
[Open a discussion](https://github.com/razukc/ziv/discussions) for questions
and ideas, or file a **"Tried it"** report
[via the feedback form](https://github.com/razukc/ziv/issues/new/choose).
Describe exactly what you felt or saw; there is no need to predict how other
people would feel. The community setup is documented in
[docs/COMMUNITY_SETUP.md](docs/COMMUNITY_SETUP.md).

---

## How a turn works

Everything you feel is one *utterance*: a whole message that your device
holds, plays, and acknowledges on its own. The relay never paces a motor.

- **The sender's text becomes the exact words you will feel.** Digits are
  spelled as number words, punctuation is dropped, and a character with no
  braille cell is refused with a reason. The sender is shown those words
  before anything plays.
- **Length is time, not letters.** The relay works out how long the words
  take on your device at your pace. Anything over the budget (15 seconds by
  default) is refused, and the sender is told the budget. Nothing is ever cut
  short.
- **Who, then why, then what.** An unsolicited message opens with the name
  mark and a tail that says what kind of thing it is: a message, a reminder,
  an error, a system note. Then comes the arrival cue, then the words as
  braille cells, with a short silence inside a word and a longer one between
  words. A reply to something you wrote has no prefix.
- **A felt close.** Every utterance ends with the same descending pattern
  (200 → 140 → 90 → 50 ms), so "finished" is felt rather than inferred from
  silence.
- **A reply being written is felt as waiting.** When a model is composing
  the line, your device plays the cue at once and repeats a working pattern
  on its own clock until the words arrive. If they never do, it plays the
  error pattern and says so.
- **Delivered means felt.** Your device reports the cue, each word and the
  close; the relay marks the message delivered only when the close has
  played. A phone that goes dark mid-message says so, and the message is
  offered again when a device is back. Reconnects resume from the last
  acknowledged message; redelivery is the failure mode, never silent loss.
- **You hold the controls.** Stop, replay, replay the last word, skip a word,
  change the pace, and choose whether the next message starts by itself or
  waits for your tap. A message that arrives while another is playing gets
  its cue at once and waits its turn.

## What is built / what is next

| Built and proven | Next |
|---|---|
| **The relay** (`ziv/`) — admission, the per-wearer outbox, SQLite with leased firing, the scheduler, the composer (echo or a model), scoped sender tokens, first-frame device auth, a content-free event log and health; it serves the two front ends | **Sender notifications** — senders poll for state today; **`ziv-relay check`**, a preflight for a running relay; **retention and backup tooling** |
| **The web renderer** (`client/`) — the reference `single_actuator` device: local sequencing from `GET /spec`, a persisted queue, acknowledgement, the wearer's controls, a headless driver for tests | **The native phone app** — a foreground service that vibrates with the screen off and keeps its queue across restarts; the web page is a foreground demo |
| **The console** (`console/`) — the accessible sender and caregiver surface: send, follow, schedule, prefs, devices, senders, health; axe-clean in jsdom | **A session with a screen reader and a braille display** — nothing has run in a real browser yet |
| **The band firmware** (`firmware/`) — the sequencer, an utterance decoder, a turn player, a bounded queue, the relay protocol with reconnect and resume; host-proven and conformant on both profiles | **The band on hardware** (rung H) and **QEMU rung 2 in CI**; the ESP-IDF glue is written but uncompiled |
| **Spec v4, the reference renderer and the conformance harness** — one JSON source, seven generated consumers, one oracle every renderer is diffed against | **Validation with wearers** — the single-actuator slot timings and the word gap are provisional until braille readers have felt them |
| **The suites** — core, store, relay, integration with the headless device, client, console, bench, band (counts below) | **Browser e2e in CI** — five tests are written and collected; they need a Chromium that can launch |

Nothing here is validated with deaf-blind readers yet, and nothing in this
repository makes a clinical or efficacy claim. The claim is a working
prototype of a new channel.

### Naming

**Ziv is a working title.** In DeafBlind practice, name marks are given by the
community, not self-declared. The feel-tool exists so that the name can be
chosen: it plays every candidate mark with the M1 and blind A/B modes the
[naming protocol](docs/NAMING_VALIDATION_PROTOCOL.md) needs. A name is adopted
only if wearers recognise the mark (M1, ≥ 80% over 8 rounds) and read it as
identity, not content. `tools/rename_check.py` validates rename candidates
against the mark's dot-count arc; `tools/m1_summary.py` computes the gates
from session CSVs.

---

## Quick start

Prerequisites: Python 3.12+, Node 24 for the front ends, a host C compiler for
the firmware suites. No model key is needed; without one the compose path
plays the intent as typed and says so (`source: echo`).

```bash
# install the relay into a venv at the root
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
# or: uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"

# build the two front ends; the relay serves them when their dist/ exists
(cd client && npm ci && npm run build)
(cd console && npm ci && npm run build)

.venv/bin/ziv-relay init      # creates ./ziv_data/ziv.sqlite and prints the admin token once
.venv/bin/ziv-relay run       # http://127.0.0.1:8787 — GET / redirects to /console/
```

Open <http://127.0.0.1:8787/console/> and sign in with the admin token. From
another terminal:

```bash
# a sender token for curl (scopes: send,read; shown once)
.venv/bin/ziv-relay sender add curl --scopes send,read
export TOKEN=...

# enroll a device: a short-lived code, exchanged once for a device key
.venv/bin/ziv-relay enroll-code           # or Console → Devices → New enroll code
# open http://127.0.0.1:8787/client/ and paste the code under "Enroll this browser as a device",
# or run the same renderer headless:
node client/dist/device-cli.js --relay ws://127.0.0.1:8787 --enroll <CODE> --clock real

# a message: the answer echoes the exact words that will be felt and the budget
curl -X POST http://127.0.0.1:8787/utterances -H "Authorization: Bearer $TOKEN" \
     -H 'content-type: application/json' -d '{"text": "taxi here"}'

# an intent, composed when it is admitted: the device cues and ticks while the line is written
curl -X POST http://127.0.0.1:8787/compose -H "Authorization: Bearer $TOKEN" \
     -H 'content-type: application/json' -d '{"intent": "meds at nine"}'

# a reminder for later (fire_at is UTC); text plays as written, intent is composed when it fires
curl -X POST http://127.0.0.1:8787/schedule -H "Authorization: Bearer $TOKEN" \
     -H 'content-type: application/json' -d '{"fire_at": "2026-11-06T09:00:00Z", "text": "meds nine"}'

# what the relay knows, without a word of content
curl http://127.0.0.1:8787/health
.venv/bin/ziv-relay events --tail 20
```

In the console, **Send → Type the words** posts the same `POST /utterances`
and shows the normalised words; **Send → Ask the agent** posts
`POST /compose` and names the source of the line (`live` when a model wrote
it, `echo` when your words played as typed). The optional own-key field sends
a Token Factory key in the `X-Nebius-Key` header of that one request only.

Settings come from the environment or a `.env` in the current directory.
Every one has a default; the relay runs with nothing set.

| Variable | Default | Meaning |
|---|---|---|
| `ZIV_DB_PATH` | `./ziv_data/ziv.sqlite` | the one database file (`--db` overrides) |
| `ZIV_HOST`, `ZIV_PORT` | `127.0.0.1`, `8787` | the bind |
| `ZIV_TLS_CERT`, `ZIV_TLS_KEY` | unset | serve TLS directly; set both or neither |
| `ZIV_ALLOW_PLAIN_HTTP` | `0` | allow a plain-HTTP bind off loopback — a LAN bench only |
| `ZIV_ADMIN_TOKEN` | unset | the console's admin token; otherwise `init` mints one and stores its hash |
| `ZIV_BUDGET_MS` | `15000` | the time budget an utterance must fit |
| `ZIV_OUTBOX_CAP`, `ZIV_SCHEDULE_CAP` | `20`, `64` | per-wearer caps; past them the sender gets 429 with a reason |
| `ZIV_DEVICE_CAPACITY` | `4` | utterances a device may hold at once |
| `ZIV_HANDOFF_WINDOW_S` | `8` | no progress from a device within this → offered to the next device |
| `ZIV_BODY_TIMEOUT_S` | `20` | a pending body that never comes fails the utterance |
| `ZIV_POLL_S`, `ZIV_LEASE_S` | `1`, `30` | the scheduler's tick and its claim lease |
| `ZIV_RETENTION_DAYS` | `7` | finished utterances and delivered replies are pruned after this; events are kept four times as long |
| `ZIV_PRUNE_INTERVAL_S` | `600` | how often retention runs |
| `ZIV_HELLO_TIMEOUT_S`, `ZIV_SEND_TIMEOUT_S` | `5`, `5` | a device's first frame, and one frame to one device |
| `ZIV_MAX_BODY_BYTES` | `65536` | hard limit on any request body |
| `ZIV_ENROLL_CODE_TTL_S` | `600` | how long an enrollment code is valid |
| `ZIV_WEARER_ID`, `ZIV_WEARER_NAME` | `w_1`, `wearer` | the wearer this relay serves |
| `ZIV_CLIENT_DIST`, `ZIV_CONSOLE_DIST` | `client/dist`, `console/dist` when built | the front ends to serve; `off` disables one |
| `NEBIUS_API_KEY` | unset | enables the live composer; without it the composer is `echo` |
| `NEBIUS_BASE_URL` | `https://api.tokenfactory.nebius.com/v1` | the OpenAI-compatible endpoint |
| `ZIV_TEXT_MODEL` | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | the model the live composer calls |

---

## Tests

```bash
.venv/bin/python -m pytest -q                      # core, store, relay, reference, conformance, integration
.venv/bin/python -m pytest -m e2e tests/e2e        # browser tier: a real relay + headless Chromium (Playwright)
python3 tools/haptic_timing.py                     # timing drift guard, all 7 generated consumers
.venv/bin/python conformance/run.py --check        # the oracle's golden timelines are in sync with the reference
.venv/bin/python conformance/run.py --player "node client/dist/conformance.js" --profile single_actuator
python3 firmware/haptic_out/run_tests.py           # haptic bench against the mock DRV2605L
python3 firmware/app/ziv_qemu/run_ziv_tests.py     # rung-1 host demo + HAP fixture diff (not a QEMU boot)
python3 firmware/band/run_band_tests.py            # band unit tests, conformance on both profiles, transport test
cd client && npm test                              # the renderer under fake timers, the page in happy-dom, the headless CLI
cd console && npm test                             # API client, Send view in jsdom, axe-core on every view
cd console && npm run gen:types -- --check         # generated TypeScript matches schema/
```

The integration tests spawn a real relay and drive it with the headless
device built from `client/dist`; they skip when `node` or the build is
missing. The browser tier skips when Chromium cannot launch.

Last run on this tree (2026-11-06):

```
PASS  python suite                 164 passed, 5 deselected (the browser tier)
SKIP  browser tier                 5 skipped — chromium cannot launch on this host
PASS  drift guard                  spec ok: v4 — 7 consumers in sync
PASS  conformance oracle           12 utterances × 2 profiles in sync with the reference
PASS  web renderer vs reference    12/12 on single_actuator, 12/12 on six_actuator
PASS  haptic bench                 459 checks, 0 failures
PASS  rung-1 host demo             49 checks, 0 failures; 27 HAP events matched
PASS  band host suite              636 checks, 0 failures; conformance 12/12 on both profiles; transport 9 checks
PASS  client                       55 tests
PASS  console                      20 tests; generated types match schema/
```

GitHub Actions (`.github/workflows/ci.yml`) runs three blocking jobs on every
push — the relay (drift guard, schema diff, oracle check, client build, the
Python suite), the renderers (client and console typecheck, test, build, and
the web renderer against the reference) and the firmware (bench, rung-1,
band) — plus a non-blocking `qemu-boot` job that stays informational until an
ESP-IDF install step is filled in.

---

## The timing spec is generated — never hand-edit a consumer

`docs/haptic-timing.json` is the single source of truth for feel timing: every
buzz and gap, the Grade-1 alphabet, the attention patterns, the name marks,
the kind → cue/tail table, the two renderer profiles and the conformance
tolerance. Seven consumers are generated from it: the feel-tool's JS block,
the firmware header (`firmware/haptic_out/haptic_timing.h`), the Python
tables (`ziv/haptics/tables.py`), the spec doc's tables
([docs/HAPTIC_TIMING_SPEC.md](docs/HAPTIC_TIMING_SPEC.md)), the boot demo's
stage table and fixture (`firmware/app/ziv_qemu/main/ziv_demo_sequence.{h,c}`)
and the ladder doc's demo-chain block.

```bash
python3 tools/haptic_timing.py          # verify (also run by the pre-commit hook and CI)
python3 tools/haptic_timing.py --write  # regenerate the consumers after editing the JSON
```

One deliberate asymmetry, guarded by the drift guard: the feel-tool's spell box
caps at 12 letters (page affordance) while the firmware accepts 16
(`HAPTIC_OUT_MAX_WORD_LEN`, runtime ceiling). Do not unify them.

### Conformance

The reference renderer, `ziv/haptics/reference.py`, turns an utterance into
the timeline of buzzes a faithful device produces; admission charges that
timeline's duration as the time budget. [conformance/](conformance/README.md)
holds twelve golden utterances, their expected timelines on both profiles,
and a runner that diffs any player command against the reference within the
spec's 10 ms tolerance — the band's C sequencer and the web renderer both pass
12/12 on both profiles.

Install the pre-commit hook once per clone — `git config core.hooksPath hooks`
— and it runs the drift guard, the wire-schema diff, the oracle check and the
haptic bench before every commit. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Repo layout

| Path | What it is |
|------|------------|
| `ziv/` | The relay package: `wire.py` (the wire contract), `haptics/` (generated tables + the reference renderer), `core/` (outbox, admission, schedule, credentials — pure), `store/` (SQLite, migrations), `relay/` (settings, `create_app`, HTTP, WebSocket, scheduler, composer, static front ends), `cli.py` (`ziv-relay`) |
| `client/` | The web renderer — the reference `single_actuator` device, plus the conformance entry and the headless device driver ([client/README.md](client/README.md)) |
| `console/` | The accessible sender and caregiver console, typed against `schema/` ([console/README.md](console/README.md)) |
| `conformance/` | Golden utterances, expected timelines, the runner and the reference player ([conformance/README.md](conformance/README.md)) |
| `firmware/haptic_out/` | The haptic sequencer — host-portable C11 with a mock DRV2605L bus and a bench suite ([README](firmware/haptic_out/README.md)) |
| `firmware/band/` | The band as a device renderer: decoder, turn player, queue, transport, host proofs, and the uncompiled ESP-IDF glue under `esp/` ([README](firmware/band/README.md)) |
| `firmware/app/ziv_qemu/` | The ESP-IDF boot app; rung 1 proven on the host, QEMU boot pending an IDF install ([README](firmware/app/ziv_qemu/README.md)) |
| `tools/` | `haptic_timing.py` (generator + drift guard), `build_ziv_demo.py` and `qemu_timeline.py` (the boot demo and the HAP differ), `m1_summary.py` and `rename_check.py` (the naming protocol's gates) |
| `docs/` | Plan, architecture, roadmap, timing spec and its JSON source, the feel-tool page, QEMU ladder, hardware bring-up and shopping list, naming protocol, community setup, outreach drafts |
| `schema/` | JSON Schema generated from `ziv/wire.py` — the contract the console, the client and the firmware tests build against |
| `tests/` | The Python suite (`test_core_*`, `test_store_db`, `test_relay_*`, `test_reference_renderer`, `test_conformance`, `test_integration_device`, `test_timing_guard`) and the `e2e/` browser tier |
| `sites/feel-tool/` | Hosting for the feel-tool page |
| `hooks/` · `.github/` | The pre-commit hook; CI and the issue templates |

---

## Security

- **TLS off loopback.** The relay binds to `127.0.0.1` by default. Off
  loopback it refuses to start without `ZIV_TLS_CERT` + `ZIV_TLS_KEY` (or a
  TLS reverse proxy in front of a loopback bind); `ZIV_ALLOW_PLAIN_HTTP=1`
  overrides that for a LAN bench and prints a warning.
- **Devices authenticate in the first frame.** The device key travels in the
  `hello` frame, never in a URL, so no credential reaches an access log. A
  wrong key closes the socket with 4401. Keys come from a short-lived
  enrollment code (10 minutes) exchanged exactly once, and are stored hashed.
- **Senders carry scoped tokens.** `send`, `read` and `admin` scopes with a
  per-sender rate limit; tokens are hashed at rest and compared in constant
  time. The admin token is minted once by `ziv-relay init` or supplied as
  `ZIV_ADMIN_TOKEN`. The served front ends, `/health`, `/spec` and the
  enrollment handshake are the only unauthenticated routes.
- **Health and events are content-free.** Counts, states, reasons and
  durations — never a word. `ziv-relay events` is the operator's view.
- **Bring your own key, once.** A model key sent in `X-Nebius-Key` is used for
  that one compose, never stored or logged, and scrubbed from provider errors.
- **Bounded and loud.** Request bodies are capped at 64 KiB, every queue has a
  cap, and every refusal names its reason (`queue_full` 429, `over_budget`
  413, `unencodable` 422, `unauthorized` 401, …).
- **Retention.** Finished utterances and delivered replies are pruned after
  `ZIV_RETENTION_DAYS` (7); the event log is kept four times as long. The
  database lives in `./ziv_data/` (gitignored — wearer data, never repo
  state).

This is a single-developer project with no separate disclosure channel yet;
contact the maintainer directly.

## Honest limits

- The native Android renderer is not built. The web renderer is the reference
  implementation of the contract and a foreground-only demo: browsers do not
  vibrate a hidden page.
- The band has not been flashed or booted under QEMU. Everything under
  `firmware/band/esp/`, the I²C bus's device path and the FreeRTOS task are
  written against ESP-IDF 5.x and uncompiled.
- Nothing has run in a real browser, with a screen reader or with a braille
  display. The console's accessibility is checked by axe-core in jsdom and by
  hand against its checklist, not yet by a user.
- The single-actuator slot timings and the word gap are provisional; no wearer
  has felt them.
- There is no preflight gate for a running relay; `ziv-relay check` is future
  work.
- Senders are not notified of state changes; they poll `GET /utterances/{id}`.

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
