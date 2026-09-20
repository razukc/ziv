# Ziv — a haptic phone companion

**Messages you can feel.** A phone that taps out incoming AI messages in vibration
patterns so a deafblind wearer can keep connected without a screen or sound — the
relay hears using NVIDIA Nemotron-3-Nano-Omni on Nebius Token Factory.

> The product plan lives in
> [docs/HAPTIC_COMPANION_PLAN.md](docs/HAPTIC_COMPANION_PLAN.md) — invariants,
> phases, and the hardware story for the next revision. This repository is the
> **phone prototype**: the interaction loop, the relay, the timing, and the PWA
> the wearer feels through the Vibration API. Hardware (ESP32 + DRV2605L + 6
> LRA motors, a ~$40 BOM) is the next revision, not the demo.

---

## What Ziv does (this prototype)

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
  real TF call is wired and tested
- **The phone stands in for the wrist** — the PWA (`agent/ziv_client/index.html`)
  renders the relay's turns through the Android Vibration API and transcribes with the
  phone mic; the wrist hardware (ESP32-S3 + DRV2605L + 6 LRA motors) is the next
  revision — see the plan doc's hardware section

---

## What this is *not* (honest scope for the hackathon)

This prototype is a phone-based demo of the always-on companion interaction loop.
For the hackathon we submit it to the **Best Apps and Agents track** as a working app
for deaf-blind users, powered by NVIDIA Nemotron on Nebius Token Factory. A few things
are scoped honestly rather than claimed:

| What the track says | What this prototype actually does |
|---|---|
| Assemble, secure, and run your own personal AI system | A phone-based prototype run on our Nebius account; the wearer does not yet self-host or control their data — that is the next revision (wrist device + wearer-hosted relay) |
| Always-on personal AI | A scheduled-job skeleton (builds in week 3) that fires unprompted — a demo beat, not a full 24/7 agent |
| Private / data under your control | The haptic output is private by physics (vibration felt only by the wearer); the mic is push-to-talk (not always-on listening). Data resides on our Nebius infrastructure in this prototype |
| Reusable skills / tools/channels of the wearer's choosing | The interaction vocabulary (7 attention patterns + 26-letter alphabet + 5 marks + prefix) is a real skill set, but not a rich skills system; input is mic + text, not a broad tools ecosystem |
| Hardware-gated mic (ESP32 pin) | Push-to-talk through the phone mic (software-gated) — hardware gating is a wrist-device property, built for the next revision |

The strongest track-claimed properties are real: **≥1 NVIDIA open model on Nebius
(Token Factory)**, **persistent memory**, and a **working demo the wearer feels on
their phone**.

---

## Why Best Apps and Agents

Deaf-blind people (~2.4 million Americans with combined hearing and vision loss) have
almost nothing built for them: refreshable braille displays cost $1,500–$12,000 and
have no mic, no agent, no always-on awareness; braille keyboards ($239–$349) are
input-only; existing haptic wristbands (Neosensory, Dot) give awareness or pins, not
language with a brain. Ziv is a different kind of app: one that hears with NVIDIA and
speaks braille on the skin, for a population mass-market product ignores.

---

## Repo layout

| Path | What it is |
|------|------------|
| `agent/ziv_server.py` | The dev-band relay server — WS transport (optional token auth), HTTP API (`/api/ziv/message`, `/inject/audio`, `/api/ziv/inbox`, `/api/ziv/prefs`, `/api/ziv/timing`, `/api/ziv/health`), serves the PWA |
| `agent/ziv_client/index.html` | The phone PWA (queue badge, refusal note, auto-redial, Omni mic path, keyless stub demo path) |
| `agent/ziv_store.py` | Per-wearer memory files + inbox (atomic JSON, corrupt-file recovery) |
| `agent/ziv_relay.py` | The relay seam: `MessageGate`, `TurnTimeline`, lifecycle constants, `TelemetryRing` |
| `agent/requirements.txt` · `agent/.env.example` | Python deps + env vars |
| `firmware/haptic_out/` | The haptic sequencer — the C core that renders messages into actuator events (for the next revision) |
| `firmware/app/ziv_qemu/` | The ESP-IDF boot app + host demo (ladder rungs 1–2, for the next revision) |
| `tools/haptic_timing.py` | The timing spec's generator + drift guard (7 generated consumers) |
| `tools/build_ziv_demo.py` | The demo-chain single source — one `DEMO_STAGES` generates app, fixture, and docs |
| `tools/qemu_timeline.py` | The rung-2 differ (bench/boot HAP logs vs the derived fixture) |
| `docs/` | Plan, timing spec, QEMU ladder, hardware bring-up + shopping |

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

The hermetic suite covers the seam (gate, timeline, thread safety), the server
endpoints, the store, the timing drift guard, and the demo-chain generation. The e2e
tier includes the redial test: a real `MessageGate` filled to the cap behind a live
turn, a 429, and the client re-sending by itself when the freeing close lands on the
wire.

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
(gitignored — user data, never repo state). The relay server binds to loopback by
default; the WS transport accepts an optional shared token (`ZIV_RELAY_TOKEN`). The
Omni endpoint (`/inject/audio`) is guarded by `NEBIUS_API_KEY`: without a key it answers
503, never a silent failure. This is a single-developer project — no separate disclosure
channel yet; contact the maintainer directly.

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
