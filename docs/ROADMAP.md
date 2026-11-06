# Roadmap

Living list of what's next. Status meanings:

- `[ ]` — candidate (not started)
- `[~]` — in progress
- `[x]` — shipped (kept here so history stays visible)

Shipped work is logged with dates in [CHANGELOG.md](../CHANGELOG.md) and
checkpoint tags (`pre-v0.1.x`). Promote items to `[~]` only when you're
actively working them. The product plan these items come from is
[HAPTIC_COMPANION_PLAN.md](HAPTIC_COMPANION_PLAN.md).

> **Repo scope:** this repository is Ziv-only (since 2026-09-17). SkillForge
> moved to its own repository — [HANDOVER_SKILLFORGE.md](HANDOVER_SKILLFORGE.md).

## Where the product is going

The target architecture is [ARCHITECTURE.md](ARCHITECTURE.md): the device
renders and acknowledges, the relay sequences through a per-wearer outbox,
and one reference renderer defines correct timing for every player. Its
section 13 lists the order of work; items below are read against it.

## Where the product is

The phone is the band today: the relay (`agent/ziv_server.py`) and the PWA
(`agent/ziv_client/`) carry the whole interaction loop, and the wrist firmware
(`firmware/`) is written and bench-proven but not yet on a board. The next
revision moves the channel from the phone's single motor to six actuators on
the wrist, and moves the relay into the wearer's own hands.

## Next

### The channel

- [ ] **Validate the channel with braille readers** — run the
      [naming-validation protocol](NAMING_VALIDATION_PROTOCOL.md) (M1–M4, the
      rename conversation) with 3–6 readers via a host organisation; the
      outreach letters are drafted ([outreach-drafts.md](outreach-drafts.md)).
      Until this runs, nothing is validated and the name stays a working title
- [ ] **Reading-pace and close decisions** — the two open design questions the
      community is being asked: does the close read as an ending, and is the
      530–770 ms per-letter pace bearable? Decide from reports, then tune the
      spec (one JSON edit, consumers regenerated)
- [ ] **Word-shape cues** — space, capital and number signals in the cell
      stream, which experienced braille readers navigate by (plan §4)

### The phone app

- [ ] **Token-aware client** — the PWA sends `?token=` on the WebSocket and
      `Authorization: Bearer` on its posts, so `ZIV_RELAY_TOKEN` and a working
      phone are no longer mutually exclusive (README → Security)
- [ ] **Playback controls** — replay last cell, pause/resume, skip a word,
      stop; speed already exists as the stored cell-gap preference
- [ ] **Audio in** — `/inject/audio` is wired and contract-tested; it needs an
      audio-capable model endpoint and a capture path in the client, and the
      client must say plainly when neither is configured

### The wrist

- [ ] **Fill the `qemu-boot` IDF install step** — the CI skeleton's gated
      steps go live on the first green boot; then promote the job to blocking
      ([QEMU_SIMULATION_LADDER.md](QEMU_SIMULATION_LADDER.md) rung-2 discipline)
- [ ] **Rung-2 QEMU differ green in CI** — Espressif-QEMU boot capture vs the
      derived demo fixture (`tools/qemu_timeline.py`), the last rung before
      on-wrist work
- [ ] **Import order lands** — 6× DRV2605L + the I²C mux, LRA motors
      ([HARDWARE_SHOPPING_GIGANEPAL.md](HARDWARE_SHOPPING_GIGANEPAL.md) tracks
      local vs import and every verified price)
- [ ] **On-wrist rung-H bring-up** — six-actuator validation against the
      feel-tool envelope ([HARDWARE_BRINGUP.md](HARDWARE_BRINGUP.md)); stage C
      is the first phone-vs-band comparison of the name mark
- [ ] **Device transport** — `ws_client` framing/reconnect/backoff behind a
      socket vtable (ladder rung 3), then the device-side `run_turn`
- [ ] **Braille-chord input** — the 6-key keyboard decode, with the 3-button
      fallback (read / stop / repeat) as the floor, not a footnote

### The relay

- [ ] **Wearer-hosted relay** — a documented self-host recipe (systemd unit,
      TLS, token on by default) so the wearer's data stays under the wearer's
      control
- [ ] **First tagged release `0.1.0`** — when the phone channel is validated
      with at least one reader session and the token-aware client ships

## In progress

- [~] **QEMU boot app (rung 1)** — the ESP-IDF app that boots the real
      `haptic_out` binary in Espressif's QEMU fork with the bench mock bus as
      the haptic backend; host-portable core shipped and proven (49-check
      bench fixture, `python firmware/app/ziv_qemu/run_ziv_tests.py`); QEMU
      boot + rung-2 differ pending an IDF/QEMU install

## Shipped

- [x] **Phone prototype** — `agent/ziv_server.py` (WebSocket transport with
      optional token auth, message turn pump through the real `MessageGate` +
      `TurnTimeline`, `/api/ziv/timing` serving the generated module) + the PWA
      (`agent/ziv_client/index.html`, Vibration API, zero hand-copied timing);
      `/inject/audio` as the opt-in audio seam (`pre-v0.1.41`, `pre-v0.1.43`)
- [x] **Durable wearer state** — per-wearer memory files (`agent/ziv_store.py`:
      atomic JSON, corrupt-file recovery surfaced in health), a persistent
      capped inbox (a message that arrives with no band attached is stored,
      not dropped, and delivered as a full event on the next attach —
      mark-after-play, so redelivery, never loss), and the durable reminder
      schedule; the wearer's playback pace is a stored preference clamped into
      the spec envelope (`pre-v0.1.42`)
- [x] **Always-on relay** — the schedule loop fires an unprompted reminder
      while nobody is chatting; a scheduled *intent* is composed by a live
      model when it fires (`text_live`) or echoed verbatim without a key
      (`text_echo`), and the wire names the path it took
- [x] **Per-session bands** — `?session=<id>` gives each phone its own hub,
      gate and turn lock, so two open clients never share turns
- [x] **Queue-don't-interrupt** — incoming messages during playback get their
      attention cue only and queue their content until the close plays (plan
      §4 invariant 4); `MessageGate` in `agent/ziv_relay.py`, bounded at 8 with
      a loud 429 past the cap, thread-safe under contention (`pre-v0.1.34`,
      `pre-v0.1.45`)
- [x] **Executable invariants (TurnTimeline)** — the turn state machine (kind
      cue → processing ticks → playing → end-of-message → gate release), wired
      to the queue gate; out-of-order transitions raise in the seam
      (`pre-v0.1.39`)
- [x] **The freeing close on the wire** — `free: true` rides the last close of
      a turn, so the client's armed redial never fires into a draining message
      (`pre-v0.1.46`)
- [x] **One generated timing source** — `docs/haptic-timing.json` → seven
      consumers, with a drift guard in the hook, the suite and CI
      (`pre-v0.1.26` onward)
- [x] **The feel-tool** — name marks, attention vocabulary, full alphabet,
      M1 session mode and blind A/B, offline, hosted
      (`pre-v0.1.24`–`pre-v0.1.27`)
- [x] **Firmware sequencer + bench** — `haptic_out` with the mock DRV2605L
      bus, 274 checks (`pre-v0.1.28`, `pre-v0.1.30`)
- [x] **Community tooling** — Discussions, the "Tried it" feedback form, the
      outreach letters ([COMMUNITY_SETUP.md](COMMUNITY_SETUP.md))

## How items get here

Pull from the plan or from what iteration and community reports surface. Each
item is one sentence naming the outcome; whoever implements it is free to
choose the approach. When an item ships, add a CHANGELOG entry, tick it here,
and tag a milestone if it's substantive.
