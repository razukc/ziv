# Ziv — a haptic phone companion

**Messages you can feel. Nobody else can see.** A phone that taps out what a
model wrote for you in vibration patterns — no screen, no sound, nothing for the
room to see or overhear. The demo run below is the whole loop on the phone: you
set an intent; with a funded Nebius Token Factory key an NVIDIA open model writes
the line and the phone spells it; without a key the same promise fires verbatim,
labelled `text_echo`, and the log names the path it took rather than claiming a
model ran — cue, legible wait, braille cells, felt close, queue release.

> The product plan lives in [docs/HAPTIC_COMPANION_PLAN.md](docs/HAPTIC_COMPANION_PLAN.md) —
> invariants, phases, and the hardware story.
>
> **This repository is the submission artifact for the hackathon.** What is built
> and proven is the submission. The rest is held as asset — available if someone
> asks, not stacked around the claim.

---

## What Ziv does (this submission)

Ziv (working title) is a private, glance-free, sound-free message channel: the
wearer's phone plays what arrives as vibro-braille they read by touch, with no
screen to look at and nothing for the room to hear or see. Vibration is the one
channel that costs nothing to carry and is used as a doorbell; Ziv turns it into
a channel that carries language, with an agent behind it.

This submission ships as **a phone-based demo**.

- **The model is in the channel, not beside it.** Set an *intent* (`{"intent":
  "meds at nine", "fire_at": ...}`); when it fires the relay calls
  Nemotron-3-Nano-30B-A3B on Nebius Token Factory to write the line the phone
  spells. The intent is free text — a question or a nudge, not only an alarm —
  and without a key it still fires verbatim (`text_echo`). A typed inbound
  message never reaches the model (the opt-in audio seam does, and is held as
  asset).
- **Every turn has the same shape.** kind cue → `processing` ticks → braille
  cells → a close descending 200→140→90→50 ms, so "finished" is felt rather
  than inferred from silence. The vocabulary is small — 7 attention patterns,
  26 letters, 5 name marks — from established early-years practice (Sense UK,
  sourced in the plan). Every constant is generated from one source,
  [docs/haptic-timing.json](docs/haptic-timing.json).
- **A message queues instead of cutting in.** The channel is serial and has no
  scrollback, so one letter costs 530–770 ms of attention (110–350 ms buzz for
  1–5 dots, plus a 420 ms gap): cut into the middle of "taxi" and you lose the word. An arrival
  double-taps at once; the message waits, draining oldest-first. Capped at 8,
  past which the sender gets a loud no (HTTP 429; the gate records
  `message:rejected`). The
  channel frees itself on the wire, not by timing: `free: true` rides the last
  close of a turn, so an armed redial never fires into a message still draining.
- **State is durable.** A message arriving with no band attached (the phone
  running the PWA) is stored, not dropped, and delivered on the next attach —
  marked delivered only after the close plays, so a phone that vanishes
  mid-playback gets the message again. The inbox (cap 20) and schedule (cap 64)
  drop their oldest when full — never quietly; every drop is logged and counted
  in `/api/ziv/health`.
- **The demo turn needs no provider at all.** A typed POST to
  `/api/ziv/message` plays the line with no key; the 429, the queue and the
  drain are the relay's own behavior, reproducible with no credit.
- **The feel-tool is how the name gets chosen.** The same generated spec drives
  a page ([docs/haptic-name-marks.html](docs/haptic-name-marks.html)) that plays
  every name mark, the attention vocabulary and any word, with the M1 and blind
  A/B modes the [naming protocol](docs/NAMING_VALIDATION_PROTOCOL.md) needs —
  which is why **Ziv is a working title**: a name is adopted only if wearers
  recognize the mark (M1, ≥ 80% over 8 rounds) and read it as identity, not
  content. It runs offline, with no relay, no key.

---

## See it (recorded)

**The submission video** — hosted on the Devpost project page, not stored in
this repo; **the field is empty until the re-record lands.** That take runs
against the public origin with the VM's funded key, so the model-path beat is a
live call: `tell me to drink` → the line the model writes, wire `source: text_live`
(without a key the same beat fires the intent verbatim, `text_echo`). The
earlier keyless take is withdrawn: it predates the 12-cell cap fix, and its
13-letter line lost the final `w` on the band. The recorder is sized for
Devpost's three-minute cap and covers the cold open, the channel, the
model-path beat, the refusal + drain, the relay kill/restart durability beat,
and the closing card.

**The silent beat (released asset, no narration)** —
**[demo_beat.webm](https://github.com/razukc/ziv/releases/download/submission-v1/demo_beat.webm)** —
a 37-second silent excerpt, recorded from the then-current dev-band page: a
starter turn, the queue filled to `8/8`, a refused message with the redial
armed, the auto-resend when the freeing close lands, and the badge draining
back to `queue 0/8`. Silent (no voiceover), so it carries no model claim at all.
`agent/record_full_demo.py` records the submission take: it drives the public
origin over `ZIV_BASE` + `ZIV_REMOTE` + `ZIV_SSH`, restarts the systemd unit
for the durability beat, and derives the narration from what that run actually
did. `record_beat.py` and `record_beat_narrated.py` are archival, written
against the earlier page shown above; none is part of the judge repro.

---

## What is built / held as asset

The honest claim is the line between what is built and proven and what is held as
asset. A reviewer should be able to read this table and know which claim is being
made — and which claim is not.

| What is built (this submission) | Held as asset (only if someone asks) |
|---|---|
| **The relay** — a FastAPI server that owns the interaction loop: WS transport with optional token auth, the message gate (queue-don't-interrupt), the turn timeline, the generated timing module, inbox, wearer memory, health, and the PWA it serves (`agent/ziv_server.py`; hermetic tests green) | **Wrist device** — ESP32-S3 + DRV2605L + 6 LRA motors + 6 chord keys + hardware-gated mic + LiPo (~$40 BOM) |
| **The phone PWA** — the wearer feels each message through the Vibration API, with the same timing derivation as the firmware and zero hand-copied numbers (`agent/ziv_client/index.html`; one tap on Android Chrome wakes it and supplies the gesture vibration requires) | **Braille-chord input** — 6-key braille chord keyboard |
| **The timing spec** — one generated source (`docs/haptic-timing.json`) → firmware header + phone feel-tool + Python consumer + ladder tables; drift guard fails on any hand edit to a generated block | **Hardware-gated mic** — the ESP32 pin |
| **The inbox + memory** — durable wearer state: per-wearer memory files (atomic JSON, corrupt-file recovery surfaced in health) + a capped persistent inbox (messages with no band attached are stored, not dropped, and delivered as full events on next attach) (`agent/ziv_store.py`; data in gitignored `agent/ziv_data/`) | **Wearer-hosted relay** — the honest answer to "data under your control" |
| **A live model in the turn** — a scheduled intent is composed by Nemotron-3-Nano-30B-A3B on Nebius Token Factory and the phone spells the line the model wrote; without a key the same promise fires verbatim, labelled `text_echo` | **An audio-in hearing layer** (`POST /inject/audio`) — wired, opt-in, and contract-tested; it needs an endpoint that accepts audio input, so it is not part of this entry's demonstrated beat |
| **A feelable timing source and interaction language** — the generated feel-tool
  ([docs/haptic-name-marks.html](docs/haptic-name-marks.html)): name marks, attention
  vocabulary, prefix, full alphabet, M1 session + blind A/B — offline, no relay | **Fine-tuned braille-output model**, **on-device practice mode / per-contact people-marks**, **spoken replies (TTS)** — not built; naming is community-held and ships under working title |
| **The test suite** — hermetic suite (seam, server, store, timing drift guard, demo-chain generation) + host firmware bench (274 checks) + QEMU-ladder host suite (49 checks); the 4 browser-tier tests are deselected from the verified count and run separately with `-m e2e` | **Flashed wrist, braille-reader naming session** — not built yet |

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
that the gap is real: ~2.4 million Americans with combined hearing and vision loss
(HKNC's 2026 DeafBlind Awareness Week statement, sourced in the plan), and the
submission's competitor table finds no existing product that pairs a haptic braille
output channel with an AI that can hear. Refreshable braille displays cost
$1,500–$12,000 and have no mic and no agent; braille keyboards ($239–$349) are
input-only (pricing sources are in the plan). Existing haptic wearables (Neosensory's
Buzz, for example) carry notifications or awareness cues, not language with a brain.

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

- **Live demo: <https://35-224-56-20.sslip.io>** — this repo's relay, on HTTPS behind
  Caddy and managed by systemd, so it comes back on its own after a reboot. Open it on
  Android Chrome — vibration needs the Vibration API, and the page says so where it is
  missing — tap **Open the band**, or drive it with the curl calls in `JUDGE_REPRO.md`.
  The console also takes **your own Nebius key** for one compose: nothing is stored,
  and the VM's credit is not spent on it.
- **[JUDGE_REPRO.md](JUDGE_REPRO.md)** — every behavioral claim → the test or
  command that proves it, plus a live run-through against that origin and a
  local durability beat (schedule a reminder → kill the relay → restart → it survives).
- **[HONESTY_CHANGELOG.md](HONESTY_CHANGELOG.md)** — the audit trail: every
  claim corrected to match the code, every bug the test suite caught (including
  two silent data-loss bugs), every soft spot closed or pinned.

---

## Repo layout

| Path | What it is |
|------|------------|
| `agent/ziv_server.py` | The relay server — WS transport + HTTP API (`/api/ziv/message`, `/api/ziv/compose`, `/api/ziv/schedule`, `/api/ziv/ready`, `/api/ziv/model/check`, `/api/ziv/inbox`, `/api/ziv/prefs`, `/api/ziv/timing`, `/api/ziv/health`), serves the PWA |
| `agent/ziv_client/index.html` | The phone PWA (queue badge, refusal note, auto-redial) |
| `agent/ziv_store.py` | Per-wearer memory files + inbox + durable reminder schedule (atomic JSON, corrupt-file recovery, capped); its data lives in the gitignored `agent/ziv_data/` |
| `agent/ziv_relay.py` | The relay seam: `MessageGate`, `TurnTimeline`, lifecycle constants, `TelemetryRing` |
| `agent/requirements.txt` · `agent/.env.example` | Python deps + env vars |
| `firmware/haptic_out/` | The haptic sequencer — the C core that renders messages into actuator events |
| `firmware/app/ziv_qemu/` | The ESP-IDF boot app + host demo; rung 1 is proven on the host, while rung 2's QEMU boot is still pending an IDF install (`docs/QEMU_SIMULATION_LADDER.md`) |
| `tools/haptic_timing.py` | The timing spec's generator + drift guard (7 generated consumers) |
| `agent/tests/` | The 18 test modules (230 hermetic tests; the 5 browser-tier tests are marked `e2e`) |
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
cp .env.example .env        # optional: NEBIUS_API_KEY enables the live text model
python -m venv venv
source venv/bin/activate    # venv\Scripts\activate on Windows
pip install -r requirements.txt
python ziv_server.py
```

The relay listens on port 8787; open `http://127.0.0.1:8787` for the PWA. On
Android Chrome, tap the band awake before using it (the first tap also supplies
the gesture the browser requires before it will vibrate).

Copy `.env.example` to `.env` and add `NEBIUS_API_KEY` to let the agent path call
the real model. Without a key everything still runs — a scheduled intent fires
its stored text instead, and the wire log says `text_echo`. To see the real
call on its own, schedule an `intent` instead of a `text` on the schedule call
shown in [JUDGE_REPRO.md](JUDGE_REPRO.md) and watch for `source: text_live`.

---

## Tests — the suites

`pytest` is not in `requirements.txt` (the demo does not need it); install it once
with `pip install pytest`. The firmware runners also need a host C compiler —
`cc`/`gcc`/`clang`/`zig cc`, or the `ziglang` package this checkout's `agent/venv`
carries (see `JUDGE_REPRO.md`).

```bash
cd agent && python -m pytest -q                  # hermetic suite (4 e2e deselected)
python tools/haptic_timing.py                    # timing drift guard
python firmware/haptic_out/run_tests.py          # haptic bench
python firmware/app/ziv_qemu/run_ziv_tests.py    # rung-1 host demo (not a QEMU boot)
```

Last run on this tree:

```
PASS  hermetic relay suite            199 checks
PASS  browser tier                      4 checks
PASS  haptic bench                    274 checks
PASS  rung-1 host demo                 49 checks
PASS  drift guard                     7 consumers in sync
```

The hermetic suite covers the seam (gate, timeline, thread safety incl.
concurrent admits losing/duplicating nothing), the server endpoints, the agent
path (a scheduled intent composed by the model and played as its own words; the
keyless echo; the loud failure), the durable store (schedule round-trip across
instances, corrupt recovery, cap), the two-sided PWA badge contract, the
busy-sheet compose contract, the client-surface contract (no capture path and
no dead controls), the demo pre-flight gate's exit codes and reminder cleanup,
and the loud redial give-up contract. The four browser-tier tests are marked `e2e` and
deselected by default; they are not part of the 199 verified tests above, but
they run on this tree against the current visible compose flow — the idle
compose screen and the mid-turn busy-sheet:
`cd agent && python -m pytest -m e2e` → **4 passed** (~65 s).

The PWA shell has a fail-closed guard of its own:
`python scripts/ziv_client_cache.py --check` fails when a shell file changed
without a service-worker cache bump (every installed PWA would keep the old page), and
`hooks/pre-commit` runs the same check against the **staged** tree, so a bump
that was never staged cannot slip into a commit either.

Those are the counts from the last full run on this tree; the commands above
reproduce them.

Run a single suite while iterating:

```bash
cd agent && python -m pytest -q -m "not e2e"
python firmware/haptic_out/run_tests.py
python tools/haptic_timing.py
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
(gitignored — user data, never repo state). The relay server binds to all
interfaces by default (a LAN dev relay).

Setting `ZIV_RELAY_TOKEN` locks the relay down: the WS handshake must present
it as `?token=`, and every route that can carry or reveal the wearer's content
(`/api/ziv/message`, `/api/ziv/compose`, `/inject/audio`, `/api/ziv/schedule`,
`/api/ziv/ready`, `/api/ziv/model/check`, `/api/ziv/inbox`, `/api/ziv/prefs`)
must send `Authorization: Bearer` — the
reader routes share one declared auth dependency; the two write routes carry
the same check explicitly.
`/api/ziv/timing` (the generated spec), `/api/ziv/health` (counts and telemetry,
no message text) and the client page stay open, because the PWA bootstraps from
them before it can hold a credential.

`GET /api/ziv/model/check` is the explicit model probe: one small Token Factory
call, `200` with a `sample` when the key answers, `502` with the provider's own
status and words when it refuses (`401`/`402`/`404`), `503` when no key is
wired. It is bearer-gated like the content routes. `health.text.last_compose`
records the same status for the last *reminder* compose, without the intent or
the composed line — so a reminder that fell back to `text_echo` says why.
`health.text.configured` is the wiring check (key + model present);
`health.text.available` is proof — `null` until a real compose runs, then that
attempt's outcome — so an unfunded key reads `available: false, status: 402`
rather than `true`.

`POST /api/ziv/compose` is the judge-key path: the console's collapsed "Use your
own Nebius key" panel sends a key in `X-Nebius-Key` for one model call, and the
composed line plays on that tab's band as `text_live`. The key is used once,
never stored, never logged, and scrubbed from any provider error. It is
one-shot on purpose — a key is not attached to a reminder that fires later.
This lets a judge verify the live model path without the relay owner's credit.

**Known gap, stated plainly:** the PWA itself sends no token — it opens `/ws`
without `?token=` and posts without an `Authorization` header. So with a token
set, the dev-band client cannot connect or send at all; "auth on" and "the demo
works" are mutually exclusive today. The token is unset by default. Making the
client token-aware is a feature, not yet built (`HONESTY_CHANGELOG.md` §1.6).

This is a single-developer project — no separate disclosure channel yet; contact
the maintainer directly.

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).
