# Roadmap

Living list of what's next. Status meanings:

- `[ ]` — candidate (not started)
- `[~]` — in progress
- `[x]` — shipped (moved here from the list so history stays visible)

Shipped work is logged with dates in [CHANGELOG.md](../CHANGELOG.md) and
checkpoint tags (`pre-v0.1.x`). Promote items to `[~]` only when you're
actively working them.

> **Repo scope:** this repository is now **Ziv-only** (2026-09-17). SkillForge
> (agent, registries, compose, Next.js frontend) moved to its own repository
> and agent — see [HANDOVER_SKILLFORGE.md](HANDOVER_SKILLFORGE.md) for where
> it lives and how it works. The roadmap below carries Ziv items only.

## Ziv — Haptic Phone Companion (submission: phone prototype; wrist is the next revision)

### Next

- [ ] **Fill the `qemu-boot` IDF install step** — the CI skeleton's gated
      steps go live on the first green boot; then promote the job to blocking
      ([QEMU_SIMULATION_LADDER.md](QEMU_SIMULATION_LADDER.md) rung-2
      discipline)
- [ ] **Rung-2 QEMU differ green in CI** — Espressif-QEMU boot capture vs the
      derived demo fixture (`tools/qemu_timeline.py`), the last rung before
      on-wrist work
- [ ] **Dev-band relay v1 closed its open items** — per-wearer memory files +
      persistent inbox already shipped (`pre-v0.1.42`); the device-side
      `ZivRelayAdapter.run_turn` (text frames, Token Factory round-trip)
      stays a week-3 item of the full wrist plan
- [ ] **Import order lands** — 6× DRV2605L + the I²C mux from AliExpress,
      ERM coin motors from Daraz in the meantime
      ([HARDWARE_SHOPPING_GIGANEPAL.md](HARDWARE_SHOPPING_GIGANEPAL.md)
      tracks local vs import and every verified price)
- [ ] **On-wrist rung-H bring-up** — six-actuator validation against the
      feel-tool envelope

### In progress

- [x] **Phone prototype (this submission)** — the built core of Ziv, demoed on
      the phone: `agent/ziv_server.py` (WS transport with optional token auth,
      message turn pump through the real `MessageGate` + `TurnTimeline`,
      `/api/ziv/timing` serving the generated module) + the PWA client
      (`agent/ziv_client/index.html`, Vibration API, zero hand-copied timing)
      + `/inject/audio` as the opt-in audio seam (`pre-v0.1.41`). The route is
      wired and contract-tested, but it is held as asset for this submission:
      it needs an audio-capable provider, the phone build has no capture path,
      and the demo makes no Omni claim (`pre-v0.1.43`)
- [x] **Durable wearer state** — per-wearer memory files
      (`agent/ziv_store.py`: atomic JSON, corrupt-file recovery surfaced in
      health) and a persistent, capped message inbox — a message that arrives
      with no band attached is stored, not dropped, and delivered as a full
      event on the next attach (mark-after-play: redelivery, never loss);
      the wearer's playback pace is a stored preference, clamped into the
      spec envelope (`pre-v0.1.42`)
- [x] **Always-on skeleton** — scheduled relay job that fires an unprompted
      reminder while nobody is "chatting"; the always-on demo beat, proven by
      a cron log; **"always-on" is the relay** — it schedules and composes
      while the phone is away, and the phone renders only while its page is
      open and connected; this build has no capture path
- [x] **Honest scope wired into the top layer** — README, Devpost draft, and
      this roadmap now carry one consistent story: the built things are proven,
      the wrist hardware is the scoped next revision; the friend's-side of the
      conversation is shown as text on their phone, not implied to be spoken
- [~] **QEMU boot app (rung 1)** — an ESP-IDF app skeleton that boots the real
      `haptic_out` binary in Espressif's QEMU fork with the bench mock bus as
      the haptic backend, prints `HAP` timelines from the sequencer's event
      stream, and diffs bench vs QEMU for equivalence
      ([QEMU_SIMULATION_LADDER.md](QEMU_SIMULATION_LADDER.md));
      host-portable core shipped and proven (49-check bench fixture,
      `python firmware/app/ziv_qemu/run_ziv_tests.py`) — QEMU boot + rung-2
      differ pending an IDF/QEMU install

### Shipped highlights

- [x] **Queue-don't-interrupt relay behavior** — incoming messages during
      haptic playback get their attention cue only and queue their content
      until the wearer closes the event (plan §4 invariant 4, from
      early-years deafblind practice); `MessageGate` in `agent/ziv_relay.py`,
      proven in the hermetic e2e suite (`pre-v0.1.34`, 2026-09-12)
- [x] **Executable invariants (TurnTimeline)** — the turn state machine (kind
      cue → processing ticks → playing → end-of-message → gate release),
      wired to the queue gate; out-of-order transitions raise in the seam,
      and the e2e suite proves the whole wearer-visible journey
      (`pre-v0.1.39`, 2026-09-13)

## How items get here

Pull from the Ziv plan ([HAPTIC_COMPANION_PLAN.md](HAPTIC_COMPANION_PLAN.md))
or ideas that come up in iteration. Each item should be one sentence naming
the outcome; the agent implementing it is free to choose the approach. When
an item ships, add a CHANGELOG entry, tick it here, and tag a milestone if
it's substantive.
