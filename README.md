# Ziv — a haptic phone companion

**Messages you can feel.** A phone that taps out incoming AI messages in vibration
patterns so a deafblind wearer can keep connected without a screen or sound — the
relay hears using NVIDIA Nemotron-3-Nano-Omni on Nebius Token Factory.

> The product plan lives in [docs/HAPTIC_COMPANION_PLAN.md](docs/HAPTIC_COMPANION_PLAN.md) —
> invariants, phases, and the hardware story for the next revision.
>
> **This repository is the submission artifact for the hackathon:** the built
> part of Ziv, run on a phone for the demo. The wrist hardware is scoped, de-risked,
> and deliberately deferred — not claimed for this submission.

---

## What Ziv does (this submission)

Ziv (working title) is a private, always-on AI companion for deaf-blind users —
a population with combined hearing and vision loss that almost nothing is built for.
One NVIDIA open model on Nebius Token Factory hears speech (push-to-talk); the wearer’s phone
plays what it hears as vibro-braille they can feel, with no screen and no sound in
the room.

This prototype ships as a **phone-based demo for the hackathon**. The built things
are real and proven; the hardware that would make them a wrist device is deferred.
See [What is built / what is scoped](#what-is-built--what-is-scoped) for the exact
line, because that line is the honest claim for this submission.

- **Haptic braille turns** — every message plays as a fixed journey the wearer can
  learn: kind cue → processing ticks → braille cells → end-of-message close, timed
  by the generated feel spec (`docs/haptic-timing.json` → one source, both the phone
  feel-tool and the firmware header are generated from it)
- **Queue, don't interrupt** — a message arriving during playback gets its attention
  cue only and queues until the current event closes (plan §4 invariant 4); a full
  queue gets a sender-visible refusal (HTTP 429 + `message:rejected`)
- **The close that frees the wrist is marked on the wire** (`free: true`) — the
  client's auto-redial fires on that frame, never on a timing guess
- **Durable wearer state** — memory files + a persistent, capped inbox
  (`agent/ziv_store.py`): a message arriving with no band attached is stored, not
  dropped, and delivered as a full event on the next attach (mark-after-play:
  redelivery, never loss)
- **Hears with NVIDIA on Nebius** — the relay transcribes the wearer's voice with
  Nemotron-3-Nano-Omni on Nebius Token Factory (`/inject/audio`, the Omni spike), then
  routes the transcript through the same turn/gate/queue path a typed message would take;
  a keyless stub (`{"simulate": "..."}`) keeps the demo runnable without a key, but the
  real TF call is wired, its request contract covered by a mocked-provider test
- **The phone stands in for the wrist** — the PWA (`agent/ziv_client/index.html`)
  renders the relay's turns through the Android Vibration API and transcribes with the
  phone mic; the wrist hardware (ESP32-S3 + DRV2605L + 6 LRA motors) is the next
  revision — see the plan doc's hardware section

---

## What is built / what is scoped

The honest claim for this submission is the line between what is built and proven
and what is designed and deferred. A reviewer (or a judge) should be able to read
this table and know which claim is being made — and which claim is not.

| What is built (this submission) | What is scoped (next revision) |
|---|---|
| **The relay** — a FastAPI server that owns the interaction loop: WS transport with optional token auth, the message gate (queue-don't-interrupt), the turn timeline, the generated timing module, inbox, wearer memory, health, and the PWA it serves (`agent/ziv_server.py`; hermetic tests green) | **The wrist device** — ESP32-S3 + DRV2605L + 6 LRA motors + 6 chord keys + hardware-gated mic + LiPo (~$40 BOM); the phone is the dev band until boards ship |
| **The phone PWA** — the wearer feels each message through the Vibration API, with the same timing derivation as the firmware and zero hand-copied numbers (`agent/ziv_client/index.html`; VR unlock after one tap on Android Chrome) | **Braille-chord input** — 6-key braille chord keyboard; this prototype's input is phone mic + text |
| **The timing spec** — one generated source (`docs/haptic-timing.json`) → firmware header + phone feel-tool + Python consumer + ladder tables; drift guard fails on any hand edit to a generated block | **Hardware-gated mic** — the ESP32 pin; this prototype uses the phone mic (push-to-talk, software-gated) |
| **The inbox + memory** — durable wearer state: per-wearer memory files (atomic JSON, corrupt-file recovery surfaced in health) + a capped persistent inbox (messages with no band attached are stored, not dropped, and delivered as full events on next attach) (`agent/ziv_store.py`; gitignored) | **Wearer-hosted relay** — this prototype runs on our infrastructure, not the wearer's (model inference on Nebius Token Factory); wearer self-hosting is the next revision (the honest answer to "data under your control") |
| **The Omni spike seam** — phone mic → `/inject/audio` → Nemotron-3-Nano-Omni on Nebius Token Factory → vibro-braille, with the same turn/gate/queue path a typed message takes; keyless stub (`{"simulate": "..."}`) keeps it runnable without a key (`/inject/audio`; guarded: 503 without a key, 502 on provider errors) | **Fine-tuned braille-output model** — Qwen3-1.7B LoRA distillation; v2, not MVP |
| **The always-on skeleton** — a scheduled relay job that fires an unprompted reminder while nobody is "chatting"; the demo beat, proven live by the relay's scheduler (loop + telemetry) | **On-device practice mode / per-contact people-marks** — v2, from early-years practice |
| **The test suite** — hermetic suite (seam, server, store, timing drift guard, demo-chain generation) + Playwright e2e (real server + real redial) + host firmware bench (49 checks) + QEMU-ladder host side | **Flashed wrist, braille-reader naming session, spoken replies (TTS)** — not built yet; naming is community-held and ships under working title |

The real track claims are in the *built* column: **≥1 NVIDIA open model on Nebius
(Token Factory)** doing real work, **persistent wearer memory**, **queue-don't-interrupt
as a tested seam**, and **a working demo the wearer feels on their phone**. The *scoped*
column is what a wrist device would add — it is the honest next revision, not a claim.

> **One asymmetry that is intentional and must not silently unify:** the phone feel-tool's
> spell box caps at **12 letters** (page affordance), while the firmware accepts **16
> (`HAPTIC_OUT_MAX_WORD_LEN`, runtime ceiling)**. Do not unify them — they live at
> different layers and answer different questions. The timing drift guard already refuses
> a drift that would try to harmonize them by accident.

---

## Why this track (and why deaf-blind is the use case, not the whole product)

Ziv is for deaf-blind users — people with combined hearing and vision loss. The
population is small enough that nothing mass-market is built for it, and large enough
that the gap is real: ~2.4 million Americans with combined hearing and vision loss, and
no existing product pairs a haptic braille output channel with an AI that can hear.
Refreshable braille displays cost $1,500–$12,000 and have no mic and no agent; braille
keyboards ($239–$349) are input-only; existing haptic wristbands (Neosensory, Dot) give
awareness or pins, not language with a brain.

But deaf-blind is the **use case that proves the channel**, not the only one. The same
haptic output channel — vibration felt by the wearer and invisible to everyone else — is
useful any time a reply should be private, glance-free, and sound-free: hands-busy or
noisy environments, shared spaces, contexts where a screen is the wrong interface and a
speaker would leak the message to the room. The deaf-blind companion is the sharpest
version of that; the phone-as-dev-band architecture is what makes it buildable for the
hackathon.

For this submission, Ziv is **a phone-based prototype to the Best Apps and Agents track**.
The full private, wearer-controlled system (wrist device with hardware-gated mic +
wearer-hosted relay) is the next revision, scoped honestly rather than claimed.

---

## For judges

- **[JUDGE_REPRO.md](JUDGE_REPRO.md)** — every claim → the test or command that
  proves it, plus a two-minute live run-through (schedule a reminder → kill the
  relay → restart → the reminder survives; outputs captured live on this repo).
- **[HONESTY_CHANGELOG.md](HONESTY_CHANGELOG.md)** — the audit trail: every
  claim corrected to match the code, every bug the test suite caught (including
  two silent data-loss bugs), every soft spot closed or pinned.

---

## Repo layout

| Path | What it is |
|------|------------|
| `agent/ziv_server.py` | The dev-band relay server — WS transport (optional token auth), HTTP API (`/api/ziv/message`, `/inject/audio`, `/api/ziv/inbox`, `/api/ziv/prefs`, `/api/ziv/timing`, `/api/ziv/health`), serves the PWA |
| `agent/ziv_client/index.html` | The phone PWA (queue badge, refusal note, auto-redial, Omni mic path, keyless stub demo path) |
| `agent/ziv_store.py` | Per-wearer memory files + inbox + durable reminder schedule (atomic JSON, corrupt-file recovery, capped) |
| `agent/ziv_relay.py` | The relay seam: `MessageGate`, `TurnTimeline`, lifecycle constants, `TelemetryRing` |
| `agent/requirements.txt` · `agent/.env.example` | Python deps + env vars |
| `firmware/haptic_out/` | The haptic sequencer — the C core that renders messages into actuator events (for the next revision) |
| `firmware/app/ziv_qemu/` | The ESP-IDF boot app + host demo (ladder rungs 1–2, for the next revision) |
| `tools/haptic_timing.py` | The timing spec's generator + drift guard (7 generated consumers) |
| `tools/build_ziv_demo.py` | The demo-chain single source — one `DEMO_STAGES` generates app, fixture, and docs |
| `tools/qemu_timeline.py` | The rung-2 differ (bench/boot HAP logs vs the derived fixture) |
| `docs/` | Plan, timing spec, QEMU ladder, hardware bring-up + shopping |
| `JUDGE_REPRO.md` · `HONESTY_CHANGELOG.md` | Judge entry points: the claim→proof index and the honesty audit trail |

---

## Quick start (dev-band relay)

Prerequisites: Python 3.10+. No key needed for the keyless stub demo path.

```bash
cd agent
cp .env.example .env        # optional: NEBIUS_API_KEY enables the real Omni path
python -m venv venv
source venv/bin/activate    # venv\Scripts\activate on Windows
pip install -r requirements.txt
python ziv_server.py
```

The printed URL (default `http://127.0.0.1:8787`) is the PWA. On Android Chrome,
allow notification permission and the Vibration API unlocks after one tap gesture.
Without `NEBIUS_API_KEY` the Omni path runs the keyless stub: the whole
turn/gate/queue journey is real, only transcription is stubbed (the `{"simulate":
"..."}` path on `/inject/audio`). With a real `NEBIUS_API_KEY`, the relay transcribes
the mic audio with Nemotron-3-Nano-Omni on Nebius Token Factory.

---

## Tests

```bash
cd agent
python -m pytest -q          # hermetic suite — browser e2e deselected
python -m pytest -m e2e      # Playwright e2e (real server + real browser)
```

The hermetic suite — **126 passed, 2 skipped** — covers the seam (gate, timeline,
thread safety incl. concurrent admits losing/duplicating nothing), the server
endpoints, the durable store (schedule round-trip across instances, corrupt
recovery, cap), the two-sided PWA badge contract, the loud redial give-up
contract, and the timing drift guard. The 2 skips are the browser e2e files,
which skip cleanly when Playwright isn't installed — no ignore flags needed.

With a browser installed (`pip install playwright && playwright install
chromium`), the e2e tier — **3 passed in real chromium** — proves the redial
journey end to end: a real `MessageGate` filled to the cap behind a live turn, a
429, the client re-sending by itself when the freeing close lands on the wire,
and a budget exhausted three times ending in a visible dead-end note that only
a wearer action clears. **129 green total.**

Firmware-side checks (host-portable, no ESP-IDF needed):

```bash
python firmware/app/ziv_qemu/run_ziv_tests.py    # 49-check C bench + boot check
```

(The C fixture and QEMU differ need a C toolchain; they are proven on machines with one
and are host-portable — they do not run on machines without a C compiler, and exit
cleanly rather than fail.)

---

## The timing spec is generated — never hand-edit a consumer

`docs/haptic-timing.json` is the single source of truth for feel timing; seven
consumers are generated from it (firmware header, feel-tool JS, the ladder doc's demo
table, …). The drift guard fails on any hand edit to a generated block:

```bash
python tools/haptic_timing.py          # verify (also run by the pre-commit hook)
python tools/haptic_timing.py --write  # regenerate / heal the consumers
```

One deliberate asymmetry, guarded by the drift guard: the feel-tool's spell box caps at
12 letters (page affordance) while the firmware accepts 16 (`HAPTIC_OUT_MAX_WORD_LEN`,
runtime ceiling). Do not unify them.

---

## Security

Ziv stores the wearer's messages and memory files locally in `agent/ziv_data/`
(gitignored — user data, never repo state).The relay server binds to all interfaces by default (a LAN dev relay); the WS transport accepts an optional shared token (`ZIV_RELAY_TOKEN`). The
Omni endpoint (`/inject/audio`) is guarded by `NEBIUS_API_KEY`: without a key it answers
503, never a silent failure. This is a single-developer project — no separate disclosure
channel yet; contact the maintainer directly.

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
