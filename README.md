# Ziv — a haptic phone companion

**Messages you can feel.** A phone that taps out what a model wrote for you in
vibration patterns, so a deafblind wearer can keep connected without a screen
or sound. The demo run below is the whole loop on the phone: you set an intent,
an NVIDIA open model on Nebius Token Factory writes the line, and the phone
spells it — cue, legible wait, braille cells, felt close, queue release.

> The product plan lives in [docs/HAPTIC_COMPANION_PLAN.md](docs/HAPTIC_COMPANION_PLAN.md) —
> invariants, phases, and the hardware story.
>
> **This repository is the submission artifact for the hackathon.** What is built
> and proven is the submission. The rest is held as asset — available if someone
> asks, not stacked around the claim.

---

## What Ziv does (this submission)

Ziv (working title) is a private haptic message channel for deaf-blind users —
a population with combined hearing and vision loss that almost nothing is built for.
The wearer's phone plays what arrives as vibro-braille they can feel, with no
screen and no sound in the room.

This submission ships as **a phone-based demo**. The built things are real and
proven; the wrist hardware is not part of this entry. See
[What is built / held as asset](#what-is-built--held-as-asset) for the exact
line, because that line is the honest claim here.

- **A model inside the channel, not beside it** — you schedule an *intent*
  (`{"intent": "meds at nine"}`); when it fires the relay calls
  Nemotron-3-Nano-30B-A3B on Nebius Token Factory and plays the line the model
  wrote, through the same turn pipeline any message takes. Without a key the
  promise still fires verbatim, labelled `text_echo` — the log never claims a
  model ran when none did
- **Haptic braille turns** — every message plays as a fixed journey the wearer can
  learn: kind cue → processing ticks → braille cells → end-of-message close, timed
  by the generated feel spec (`docs/haptic-timing.json` → one source; the phone
  feel-tool and the firmware header are both generated from it)
- **Queue, don't interrupt** — a message arriving during playback gets its attention
  cue only and queues until the current event closes (plan §4 invariant 4); a full
  queue gets a sender-visible refusal (HTTP 429 + `message:rejected`)
- **The close that frees the wrist is marked on the wire** (`free: true`) — the
  client's auto-redial fires on that frame, never on a timing guess
- **Durable wearer state** — memory files + a persistent, capped inbox
  (`agent/ziv_store.py`): a message arriving with no band attached is stored, not
  dropped, and delivered as a full event on the next attach (mark-after-play:
  redelivery, never loss)
- **A demo turn that plays without a live provider call** — the demo hands a
  transcript to the relay through the keyless stub path, so the
  turn/gate/queue/close journey is fully real and reproducible on the phone.
- **A feelable timing source and interaction language** — the same generated spec
  that drives the phone today also drives the feel-tool
  ([docs/haptic-name-marks.html](docs/haptic-name-marks.html)): five name marks,
  the full attention vocabulary, the name-mark prefix, the 26-letter braille
  alphabet, and self-test modes (M1 session, blind A/B) — all offline, no relay.

---

## See it (recorded)

**[demo_beat.webm](https://github.com/razukc/ziv/releases/download/submission-v1/demo_beat.webm)** —
the 0:20–1:10 beat, recorded from the real dev-band page: a starter turn,
the queue filled to `8/8`, a refused message with the redial armed
(`3 chances left`), the auto-resend when the freeing close lands, and the
badge draining back to `queue 0/8`. Re-record it yourself:
`python agent/record_beat.py` (walkthrough in [DEMO_SCRIPT.md](DEMO_SCRIPT.md)).

---

## What is built / held as asset

The honest claim is the line between what is built and proven and what is held as
asset. A reviewer should be able to read this table and know which claim is being
made — and which claim is not.

| What is built (this submission) | Held as asset (only if someone asks) |
|---|---|
| **The relay** — a FastAPI server that owns the interaction loop: WS transport with optional token auth, the message gate (queue-don't-interrupt), the turn timeline, the generated timing module, inbox, wearer memory, health, and the PWA it serves (`agent/ziv_server.py`; hermetic tests green) | **Wrist device** — ESP32-S3 + DRV2605L + 6 LRA motors + 6 chord keys + hardware-gated mic + LiPo (~$40 BOM) |
| **The phone PWA** — the wearer feels each message through the Vibration API, with the same timing derivation as the firmware and zero hand-copied numbers (`agent/ziv_client/index.html`; VR unlock after one tap on Android Chrome) | **Braille-chord input** — 6-key braille chord keyboard |
| **The timing spec** — one generated source (`docs/haptic-timing.json`) → firmware header + phone feel-tool + Python consumer + ladder tables; drift guard fails on any hand edit to a generated block | **Hardware-gated mic** — the ESP32 pin |
| **The inbox + memory** — durable wearer state: per-wearer memory files (atomic JSON, corrupt-file recovery surfaced in health) + a capped persistent inbox (messages with no band attached are stored, not dropped, and delivered as full events on next attach) (`agent/ziv_store.py`; gitignored) | **Wearer-hosted relay** — the honest answer to "data under your control" |
| **A live model in the turn** — a scheduled intent is composed by Nemotron-3-Nano-30B-A3B on Nebius Token Factory and the phone spells the line the model wrote; without a key the same promise fires verbatim, labelled `text_echo` | **An audio-in hearing layer** (`POST /inject/audio`) — wired, opt-in, and contract-tested; it needs an endpoint that accepts audio input, so it is not part of this entry's demonstrated beat |
| **A feelable timing source and interaction language** — the generated feel-tool
  ([docs/haptic-name-marks.html](docs/haptic-name-marks.html)): name marks, attention
  vocabulary, prefix, full alphabet, M1 session + blind A/B — offline, no relay | **Fine-tuned braille-output model**, **on-device practice mode / per-contact people-marks**, **spoken replies (TTS)** — not built; naming is community-held and ships under working title |
| **The test suite** — hermetic suite (seam, server, store, timing drift guard, demo-chain generation) + Playwright e2e (real server + real redial) + host firmware bench (274 checks) + QEMU-ladder host suite (49 checks) | **Flashed wrist, braille-reader naming session** — not built yet |

The track claims are in the *built* column: **an NVIDIA open model on Nebius Token Factory doing real work inside a channel with no screen**, **a working demo the wearer feels on their phone**, **persistent wearer memory**, **queue-don't-interrupt as a tested seam**, and **one generated timing source shared by the phone today and the feel-tool — and, later, the wrist firmware (drift-guarded)**.

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

For this submission, Ziv is **a phone-based demo to the Best Apps and Agents track**.
The built things are the submission. The rest is held as asset.

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
| `agent/ziv_server.py` | The relay server — WS transport (optional token auth), HTTP API (`/api/ziv/message`, `/api/ziv/inbox`, `/api/ziv/prefs`, `/api/ziv/timing`, `/api/ziv/health`), serves the PWA |
| `agent/ziv_client/index.html` | The phone PWA (queue badge, refusal note, auto-redial, keyless stub demo path) |
| `agent/ziv_store.py` | Per-wearer memory files + inbox + durable reminder schedule (atomic JSON, corrupt-file recovery, capped) |
| `agent/ziv_relay.py` | The relay seam: `MessageGate`, `TurnTimeline`, lifecycle constants, `TelemetryRing` |
| `agent/requirements.txt` · `agent/.env.example` | Python deps + env vars |
| `firmware/haptic_out/` | The haptic sequencer — the C core that renders messages into actuator events |
| `firmware/app/ziv_qemu/` | The ESP-IDF boot app + host demo (ladder rungs 1–2) |
| `tools/haptic_timing.py` | The timing spec's generator + drift guard (7 generated consumers) |
| `tools/prove.py` | One command, one paste-able block of proof for every suite |
| `tools/model_probe.py` | One live call to the agent path, for the questionnaire's quality rating |
| `tools/build_ziv_demo.py` | The demo-chain single source — one `DEMO_STAGES` generates app, fixture, and docs |
| `tools/qemu_timeline.py` | The rung-2 differ (bench/boot HAP logs vs the derived fixture) |
| `docs/` | Plan, timing spec, QEMU ladder, hardware bring-up + shopping |
| `docs/haptic-name-marks.html` | The feel-tool — the timing source and interaction language, felt on a phone, offline |
| `JUDGE_REPRO.md` · `HONESTY_CHANGELOG.md` | Judge entry points: the claim→proof index and the honesty audit trail |

---

## Quick start (dev-band relay)

Prerequisites: Python 3.10+. No key needed for the demo path.

```bash
cd agent
cp .env.example .env        # optional: NEBIUS_API_KEY enables the real audio path
python -m venv venv
source venv/bin/activate    # venv\Scripts\activate on Windows
pip install -r requirements.txt
python ziv_server.py
```

The printed URL (default `http://127.0.0.1:8787`) is the PWA. On Android Chrome,
allow notification permission and the Vibration API unlocks after one tap gesture.

Copy `.env.example` to `.env` and add `NEBIUS_API_KEY` to let the agent path call
the real model. Without a key everything still runs — a scheduled intent fires
its stored text instead, and the wire log says `text_echo`. To see the real
call on its own, run `python tools/model_probe.py`.

---

## Tests — one command, one block

```bash
python tools/prove.py           # every suite + the drift guard
python tools/prove.py --e2e     # also the browser tier (needs Playwright)
```

Last run on this tree:

```
PASS  hermetic relay suite            131 checks
PASS  haptic bench                    274 checks
PASS  QEMU host suite                  49 checks
PASS  drift guard                     7 consumers in sync
```

The hermetic suite covers the seam (gate, timeline, thread safety incl.
concurrent admits losing/duplicating nothing), the server endpoints, the agent
path (a scheduled intent composed by the model and played as its own words; the
keyless echo; the loud failure), the durable store (schedule round-trip across
instances, corrupt recovery, cap), the two-sided PWA badge contract, and the loud
redial give-up contract. With a browser installed (`pip install playwright &&
playwright install chromium`), `--e2e` adds the redial journey end to end: a real
`MessageGate` filled to the cap behind a live turn, a 429, the client re-sending
by itself when the freeing close lands on the wire, and a budget exhausted three
times ending in a visible dead-end note that only a wearer action clears.

Those numbers are generated, not typed. If a suite changes, this block changes —
which is the point: no hand-maintained count can drift.

Run a single suite while iterating:

```bash
cd agent && python -m pytest -q -m "not e2e"
python firmware/haptic_out/run_tests.py
python tools/haptic_timing.py --verify
```

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
(gitignored — user data, never repo state).The relay server binds to all interfaces by default (a LAN dev relay); the WS transport accepts an optional shared token (`ZIV_RELAY_TOKEN`). This is a single-developer project — no separate disclosure
channel yet; contact the maintainer directly.

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
