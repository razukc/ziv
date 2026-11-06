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

## Where the product is

The tree implements [ARCHITECTURE.md](ARCHITECTURE.md), built on 2026-11-06
as parallel workstreams (§13 records this). The device renders and
acknowledges; the relay sequences through a per-wearer outbox in SQLite;
one reference renderer defines correct timing, and a conformance harness
holds every renderer to it. What exists: the relay (`ziv/`, `ziv-relay`),
the web renderer (`client/`, the reference `single_actuator` device and a
foreground-only demo), the accessible console (`console/`), the band
firmware around the proven sequencer (`firmware/band/`, host-proven,
conformant on both profiles, uncompiled for the ESP32-S3), spec v4 with the
word gap, the kinds table and the two profiles, and the suites that gate
every push. What does not exist yet: a renderer that works with the screen
off, a band on a wrist, and any wearer who has felt the result.

## Next

### The channel

- [ ] **Validate the channel with braille readers** — run the
      [naming-validation protocol](NAMING_VALIDATION_PROTOCOL.md) (M1–M4, the
      rename conversation) with 3–6 readers via a host organisation; the
      outreach letters are drafted ([outreach-drafts.md](outreach-drafts.md)).
      Until this runs, nothing is validated and the name stays a working title
- [ ] **Wearer validation sessions for spec v4** — the single-actuator slot
      timings (50 / 30 / 80 ms, 530 ms per cell), the 520 ms word gap and the
      close are provisional until readers have felt them on the feel-tool and
      on a device; the first thing to try if slot positions blur is a slower
      slot (70 / 40 / 100). Decide from reports, then tune the spec (one JSON
      edit, consumers and expected timelines regenerated)
- [ ] **Word-shape cues** — space, capital and number signals in the cell
      stream, which experienced braille readers navigate by (plan §4)

### The phone

- [ ] **The native phone renderer** — an Android app with a foreground
      service that vibrates with the screen off, keeps its queue across
      process restarts, and implements the same contract as the band with the
      `single_actuator` profile; the web renderer is its reference and its
      conformance entry is the template. No JDK or SDK here yet
- [ ] **The web renderer in a real browser** — run the page on an Android
      phone and the five browser e2e tests on a host where Chromium launches;
      promote the e2e tier into CI

### The console

- [ ] **A session with a screen reader and a braille display** — the console
      is axe-clean in jsdom and checked by hand against its checklist; nothing
      has run with NVDA, VoiceOver or a display yet

### The wrist

- [ ] **Fill the `qemu-boot` IDF install step** — the CI skeleton's gated
      steps go live on the first green boot; then promote the job to blocking
      ([QEMU_SIMULATION_LADDER.md](QEMU_SIMULATION_LADDER.md) rung-2 discipline)
- [ ] **Rung-2 QEMU differ green in CI** — Espressif-QEMU boot capture vs the
      derived demo fixture (`tools/qemu_timeline.py`), the last rung before
      on-wrist work
- [ ] **Compile the band for the ESP32-S3** — everything under
      `firmware/band/esp/`, the I²C bus's device path and the FreeRTOS task
      are written against ESP-IDF 5.x and uncompiled
- [ ] **Import order lands** — 6× DRV2605L + the I²C mux, LRA motors
      ([HARDWARE_SHOPPING_GIGANEPAL.md](HARDWARE_SHOPPING_GIGANEPAL.md) tracks
      local vs import and every verified price)
- [ ] **On-wrist rung-H bring-up** — six-actuator validation against the
      feel-tool envelope ([HARDWARE_BRINGUP.md](HARDWARE_BRINGUP.md)); the
      first phone-vs-band comparison of the name mark, and the live relay's
      websocket (TLS) from a devkit
- [ ] **Braille-chord input on the band** — the 6-key keyboard decode
      producing `input.text`, with the 3-button fallback (read / stop /
      repeat) as the floor, not a footnote; the web renderer's compose box is
      the only reply path today

### The relay

- [ ] **Sender notifications** — `NotifySender` is a no-op today; senders
      poll `GET /utterances/{id}`. A subscription or webhook per sender, with
      the same content-free discipline as events
- [ ] **`ziv-relay check`** — a preflight for a running relay (health, a
      scheduled utterance fired and acknowledged by a device, TLS and token
      posture), replacing the gate that left with the old API
- [ ] **Retention and backup tooling** — a checkpointed copy of the database
      file, a per-table retention report, and a documented self-host recipe
      (systemd unit, TLS, the admin token) so the wearer's data stays under
      the wearer's control
- [ ] **A token-aware feel-tool path** — the hosted feel-tool stays offline
      and keyless; a path from the feel-tool to a wearer's own relay is open
- [ ] **First tagged release `0.1.0`** — when the channel is validated with at
      least one reader session and a renderer that works with the screen off
      ships

## Shipped

- [x] **The cutover** — `agent/` retired with its server-paced relay, PWA,
      JSON stores and 233-test suite; one generated Python table at
      `ziv/haptics/tables.py`; the root `.venv`; CI as three blocking jobs
      plus the `qemu-boot` skeleton; the hook checks spec, schemas, oracle and
      bench (`1a86c50`)
- [x] **The integration** — the relay serves `/client/` and `/console/`,
      `POST /compose` admits a body-pending utterance then composes (echo, the
      configured model, or a caller's own key used once), a hidden/muted/full
      nack re-offers, seven integration tests drive the headless device
      against a live relay; five browser tests written (`56f21b3`)
- [x] **The band speaks the wire** — utterance decoder, turn player
      conformant on both profiles, bounded persisted queue with
      acknowledgement, the relay protocol behind a frame vtable with
      hello-first, backoff and resume; proven against a fake relay on
      loopback; the mux control byte fixed to a one-hot mask (`80a60ff`)
- [x] **The sequencing relay** — pure core (outbox state machine, admission
      with the time budget, leased schedule, hashed credentials), SQLite in
      WAL with numbered migrations, `create_app` with no module state, scoped
      sender tokens, first-frame device auth, the composer protocol, a
      content-free events table and counts-only health, the `ziv-relay` CLI
      (`a188c50`)
- [x] **The console** — the accessible sender and caregiver surface, typed
      against the schemas, strict CSP, axe-core on every view, a mock relay
      that validates every body (`c425fe3`)
- [x] **The web device renderer** — local sequencing from `GET /spec`, a
      persisted queue, acknowledgement, the wearer's controls, `nack hidden`,
      and a conformance entry that matches the reference 12/12 on both
      profiles (`496bac4`)
- [x] **Spec v4, the reference renderer and the conformance harness** — the
      word gap, the kinds table, the two renderer profiles and the tolerance;
      `ziv/haptics/reference.py` as the oracle; twelve golden utterances with
      expected timelines, drift-guarded (`6635f37`)
- [x] **The contract** — the `ziv` package, `ziv.wire` as the single wire
      contract with JSON Schema in `schema/`, the generator writing the tables
      into the package (`14c59ce`)
- [x] **The target architecture written down** — [ARCHITECTURE.md](ARCHITECTURE.md)
      (`55bd8ac`)
- [x] **One generated timing source** — `docs/haptic-timing.json` → seven
      consumers, with a drift guard in the hook, the suite and CI
      (`pre-v0.1.26` onward)
- [x] **The feel-tool** — name marks, attention vocabulary, full alphabet,
      M1 session mode and blind A/B, offline, hosted
      (`pre-v0.1.24`–`pre-v0.1.27`)
- [x] **Firmware sequencer + bench** — `haptic_out` with the mock DRV2605L
      bus (`pre-v0.1.28`, `pre-v0.1.30`); 459 checks since the band work
- [x] **QEMU boot app (rung 1)** — the host-portable core of the ESP-IDF app
      that boots the real sequencer, proven against the derived 27-line HAP
      fixture (49 checks); the QEMU boot itself waits for an IDF install
- [x] **Community tooling** — Discussions, the "Tried it" feedback form, the
      outreach letters ([COMMUNITY_SETUP.md](COMMUNITY_SETUP.md))

Retired with the old tree (history in the CHANGELOG): the phone-as-band PWA,
the server-paced turn pump, the JSON inbox and schedule files, per-session
bands, the `free: true` close flag, the token-aware PWA item (the new client
authenticates in its first frame) and the `/inject/audio` seam (audio input is
a separate sender service in the architecture, out of scope for this
revision).

## How items get here

Pull from the plan or from what iteration and community reports surface. Each
item is one sentence naming the outcome; whoever implements it is free to
choose the approach. When an item ships, add a CHANGELOG entry, tick it here,
and tag a milestone if it's substantive.
