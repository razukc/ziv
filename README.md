# Ziv — a haptic message channel

**Messages you can feel. No screen, no speaker.** Ziv plays what arrives for
you as vibration on your skin: an arrival cue, a legible wait while a reply is
written, the text spelled as braille cells, and a felt close that says
"finished". Today it runs on an Android phone through the Vibration API; the
same timing drives the wrist band firmware that comes next.

Ziv (a working title — see [Naming](#naming)) is built for deaf-blind
people, who have combined hearing and vision loss and for whom neither a
screen nor a speaker is a channel. It is also for anyone who wants a reply that
is quiet, glance-free, and private by physics: nothing to overhear, nothing to
look at.

> The product plan lives in [docs/HAPTIC_COMPANION_PLAN.md](docs/HAPTIC_COMPANION_PLAN.md)
> — the problem, the device concept, the interaction invariants, and the
> milestones. The target software architecture is
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). What is planned next is in
> [docs/ROADMAP.md](docs/ROADMAP.md).

## Try it

- **[Feel-tool](https://site-5505fea77ec84b4f8e1a5d70c82d5877.freebuff.page)**
  — the interactive source of Ziv's timing rules and attention vocabulary:
  name-mark cards, the full alphabet, a spell box, an M1 recognition session
  and a blind A/B mode. Nothing to install, no relay, no key. Plays on Android
  Chrome; desktop and iOS show the visual rhythm only. The page is
  [docs/haptic-name-marks.html](docs/haptic-name-marks.html), generated from
  the same spec the firmware uses.
- **The relay and phone app** — run the [quick start](#quick-start) below,
  open the page on an Android phone, and send yourself a message.

Afterwards we want to hear from you: did the close feel like an ending, and is
the reading pace bearable? Those are the two decisions currently open.
[Open a discussion](https://github.com/razukc/ziv/discussions) for questions
and ideas, or file a **"Tried it"** report
[via the feedback form](https://github.com/razukc/ziv/issues/new/choose).
Describe exactly what you felt or saw; there is no need to predict how other
people would feel. The community setup is documented in
[docs/COMMUNITY_SETUP.md](docs/COMMUNITY_SETUP.md).

---

## How it works

- **Every turn has the same shape.** Kind cue → `processing` ticks → braille
  cells → a close descending 200→140→90→50 ms, so "finished" is felt rather
  than inferred from silence. The vocabulary is small — 7 attention patterns,
  26 letters, 5 name marks — from established early-years deafblind practice
  (Sense UK, sourced in the plan). Every constant is generated from one file,
  [docs/haptic-timing.json](docs/haptic-timing.json).
- **A message queues instead of cutting in.** The channel is serial and has no
  scrollback: one letter costs 530–770 ms of attention, and cutting into the
  middle of "taxi" loses the word. An arrival mid-turn double-taps at once and
  waits; the queue drains oldest-first. It is capped at 8, past which the
  sender gets a loud no (HTTP 429, recorded as `message:rejected`). The channel
  frees itself on the wire, not by timing: `free: true` rides the last close of
  a turn, so an armed redial never fires into a message still draining.
- **State is durable, with documented edges.** A message that arrives while no
  phone is attached is stored in a 20-item inbox and delivered on the next
  attach — marked delivered only after the close plays, so a phone that
  vanishes mid-playback gets it again. The inbox and the 64-item reminder
  schedule drop their oldest when full, never quietly: every drop is logged and
  counted in `/api/ziv/health`. Per-wearer memory (for now, the reading pace)
  is an atomic JSON file; a corrupt file is discarded and reported, never
  swallowed.
- **A model can write the line.** A scheduled *intent* (free text — a question
  or a nudge, not only an alarm) is composed when it fires by an open model on
  Nebius Token Factory (Nemotron-3-Nano-30B-A3B), and the phone spells what the
  model wrote, labelled `text_live`. Without a key the same promise fires
  verbatim, labelled `text_echo`, and the log names the path it took rather
  than claiming a model ran. A typed inbound message never reaches the model.
- **The relay is the always-on part.** It schedules and composes while the
  phone is away; the phone renders only while its page is open and connected.
  The wearer's data lives on the relay, in `agent/ziv_data/`, and the
  wearer-hosted relay is the next revision's answer to "data under your
  control".

## What is built / what is next

| Built and proven | Next |
|---|---|
| **The relay** — a FastAPI server that owns the interaction loop: WebSocket transport with optional token auth, the message gate (queue-don't-interrupt), the turn timeline, inbox, wearer memory, the reminder schedule, health, and the PWA it serves (`agent/ziv_server.py`) | **The wrist band** — ESP32-S3 + DRV2605L + 6 LRA motors + 6 chord keys + hardware-gated mic + LiPo (~$40 BOM); the sequencer is written and bench-proven, the board is not flashed yet ([docs/HARDWARE_BRINGUP.md](docs/HARDWARE_BRINGUP.md)) |
| **The phone app** — a PWA that plays each turn through the Vibration API with the same timing derivation as the firmware and zero hand-copied numbers (`agent/ziv_client/index.html`) | **Braille-chord input** — the 6-key keyboard; the phone replies by typed text today |
| **The timing spec** — one generated source → firmware header, phone feel-tool, Python module, docs tables; a drift guard fails on any hand edit to a generated block | **Hearing** — an audio-in seam (`POST /inject/audio`) is wired and contract-tested but needs an audio-capable model endpoint; the phone build has no capture path |
| **Durable wearer state** — per-wearer memory files, the capped persistent inbox, the durable reminder schedule (`agent/ziv_store.py`) | **Wearer-hosted relay**, **spoken replies (TTS)**, **per-contact people-marks**, **an on-device practice mode** |
| **The test suite** — hermetic relay suite, browser tier, host firmware bench, QEMU-ladder host suite, timing drift guard (counts below) | **A braille-reader naming session** — the protocol is written ([docs/NAMING_VALIDATION_PROTOCOL.md](docs/NAMING_VALIDATION_PROTOCOL.md)); it has not been run |

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

Prerequisites: Python 3.10+. No key is needed; the model path falls back to
`text_echo`.

```bash
cd agent
cp .env.example .env        # optional: NEBIUS_API_KEY enables the live text model
python -m venv venv
source venv/bin/activate    # venv\Scripts\activate on Windows
pip install -r requirements.txt
python ziv_server.py
```

The relay listens on port 8787. Open `http://<lan-ip>:8787/ziv_client/index.html`
on an Android phone on the same network, tap **Open the band** (the tap
supplies the gesture the browser requires before it will vibrate), then from
another terminal:

```bash
# a message: cue, cells, close
curl -X POST http://127.0.0.1:8787/api/ziv/message -H 'content-type: application/json' \
     -d '{"text": "taxi here"}'

# a scheduled intent, composed by the model when it fires (text_echo without a key)
curl -X POST http://127.0.0.1:8787/api/ziv/schedule -H 'content-type: application/json' \
     -d '{"intent": "meds at nine", "fire_at": 0}'

# what the relay knows: attached bands, queue depth vs cap, inbox, schedule, model status
curl http://127.0.0.1:8787/api/ziv/health
```

The operator console on the same page shows the wire log, the queue badge, and
a collapsed bring-your-own-key panel: a Token Factory key pasted there is used
for exactly one compose and never stored.

`scripts/relay_preflight.sh` is the hand-over gate: it refuses to pass a relay
whose schedule loop cannot fire a reminder unprompted.

---

## Tests

`pytest` and Playwright come from `agent/requirements-dev.txt`. The firmware
runners need a host C compiler — `cc`/`gcc`/`clang`/`zig cc`, or the `ziglang`
pip package in the venv.

```bash
cd agent && python -m pytest -q                  # hermetic suite (browser e2e deselected)
cd agent && python -m pytest -m e2e              # browser tier: real relay in-process + headless Chromium (~75 s)
python tools/haptic_timing.py                    # timing drift guard, all 7 generated consumers
python firmware/haptic_out/run_tests.py          # haptic bench against the mock DRV2605L
python firmware/app/ziv_qemu/run_ziv_tests.py    # rung-1 host demo + HAP fixture diff (not a QEMU boot)
python scripts/ziv_client_cache.py --check       # PWA shell changed without a service-worker cache bump?
```

Last run on this tree:

```
PASS  hermetic relay suite            233 checks
PASS  browser tier                      5 checks   (last verified on the hackathon tree; this host lacks Chromium's system libs)
PASS  haptic bench                    274 checks
PASS  rung-1 host demo                 49 checks
PASS  drift guard                     7 consumers in sync
```

The hermetic suite covers the seam (gate, timeline, thread safety including
concurrent admits losing or duplicating nothing), the server endpoints, the
model path (a scheduled intent composed and played as the model's words; the
keyless echo; the loud failure), the durable store (round-trip across
instances, corrupt recovery, caps), the two-sided PWA badge contract, the
busy-sheet compose contract, the client-surface contract (no capture path, no
dead controls), the preflight gate's exit codes, and the redial give-up
contract. GitHub Actions runs the hermetic suite, the drift guard, the cache
check and the rung-1 bench on every push (`.github/workflows/ci.yml`).

---

## The timing spec is generated — never hand-edit a consumer

`docs/haptic-timing.json` is the single source of truth for feel timing. Seven
consumers are generated from it: the feel-tool's JS block, the firmware header,
the Python module the relay and tests import, the spec doc's tables, the QEMU
boot demo's stage table and fixture, and the ladder doc's demo-chain block.

```bash
python tools/haptic_timing.py          # verify (also run by the pre-commit hook and CI)
python tools/haptic_timing.py --write  # regenerate the consumers after editing the JSON
```

One deliberate asymmetry, guarded by the drift guard: the feel-tool's spell box
caps at 12 letters (page affordance) while the firmware accepts 16
(`HAPTIC_OUT_MAX_WORD_LEN`, runtime ceiling). Do not unify them.

Install the pre-commit hook once per clone — `git config core.hooksPath hooks`
— and it runs the drift guard, the haptic bench, and the staged PWA cache check
before every commit. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Repo layout

| Path | What it is |
|------|------------|
| `agent/ziv_server.py` | The relay — WebSocket transport + HTTP API (`/api/ziv/message`, `/api/ziv/compose`, `/api/ziv/schedule`, `/api/ziv/inbox`, `/api/ziv/prefs`, `/api/ziv/timing`, `/api/ziv/health`, …), serves the PWA |
| `agent/ziv_relay.py` | The relay seam: `MessageGate`, `TurnTimeline`, lifecycle constants, `TelemetryRing` |
| `agent/ziv_store.py` | Per-wearer memory files + inbox + durable reminder schedule (atomic JSON, corrupt-file recovery, capped); data in the gitignored `agent/ziv_data/` |
| `agent/ziv_client/` | The phone PWA: `index.html`, service worker, manifest, icons |
| `agent/tests/` | The hermetic suite and the `e2e`-marked browser tier |
| `firmware/haptic_out/` | The haptic sequencer — the host-portable C core that renders messages into actuator events, with a mock DRV2605L bus and a bench suite |
| `firmware/app/ziv_qemu/` | The ESP-IDF boot app; rung 1 proven on the host, QEMU boot pending an IDF install ([docs/QEMU_SIMULATION_LADDER.md](docs/QEMU_SIMULATION_LADDER.md)) |
| `tools/haptic_timing.py` | The timing spec's generator + drift guard |
| `tools/build_ziv_demo.py` · `tools/qemu_timeline.py` | The boot demo's single source and the HAP log differ |
| `tools/m1_summary.py` · `tools/rename_check.py` | The naming protocol's gate analyzer and rename validator |
| `scripts/` | The PWA cache guard, the relay preflight gate, the schedule-loop liveness probe |
| `sites/feel-tool/` | Hosting for the feel-tool page |
| `docs/` | Plan, roadmap, timing spec, QEMU ladder, hardware bring-up and shopping list, naming protocol, community setup, outreach drafts |

---

## Security

Ziv stores the wearer's messages and memory files locally in `agent/ziv_data/`
(gitignored — user data, never repo state). The relay binds to all interfaces
by default: it is a LAN dev relay, not a deployment.

Setting `ZIV_RELAY_TOKEN` locks it down: the WebSocket handshake must present
the token as `?token=`, and every route that can carry or reveal the wearer's
content (`/api/ziv/message`, `/api/ziv/compose`, `/inject/audio`,
`/api/ziv/schedule`, `/api/ziv/ready`, `/api/ziv/model/check`,
`/api/ziv/inbox`, `/api/ziv/prefs`) must send `Authorization: Bearer`.
`/api/ziv/timing`, `/api/ziv/health` (counts and telemetry, no message text)
and the client page stay open, because the PWA bootstraps from them before it
can hold a credential.

`GET /api/ziv/model/check` is the explicit model probe: `200` with a sample
when the key answers, `502` with the provider's own status when it refuses,
`503` when no key is wired. `health.text.configured` says a key is wired;
`health.text.available` is proof from the last real compose, `null` until one
runs, so an unfunded key reads `available: false, status: 402` rather than
`true`.

`POST /api/ziv/compose` is the bring-your-own-key path: a key sent in
`X-Nebius-Key` is used for one model call, never stored, never logged, and
scrubbed from any provider error. It is one-shot on purpose — a key is not
attached to a reminder that fires later.

**Known gap, stated plainly:** the PWA itself sends no token, so with a token
set the phone client cannot connect. The token is unset by default; a
token-aware client is on the roadmap.

This is a single-developer project with no separate disclosure channel yet;
contact the maintainer directly.

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
