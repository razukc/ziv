# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Ziv is a haptic message channel for deaf-blind wearers. A relay (`ziv/`) admits, orders and tracks *utterances*; a device renderer — the web client (`client/`) today, the band firmware (`firmware/band/`) on the host, a native phone app next — plays each one on its own clock and acknowledges it; an accessible console (`console/`) is the senders' and caregivers' surface. One generated timing spec and one reference renderer define correct playback for every renderer. The design is `docs/ARCHITECTURE.md`; the tree implements it. The README's "What is built / what is next" table draws a hard line between what is **built and proven** and what is **next**. Do not move a claim across that line in docs without the matching code/test, and make no clinical or efficacy claims anywhere.

## Commands

Python 3.12+ (CI uses 3.12), Node 24, a host C compiler for the firmware suites. The package installs into `.venv` at the repo root; the hook, the band runner and the conformance harness look there first.

```bash
# install
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
# or: uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
(cd client && npm ci && npm run build)      # the relay serves client/dist at /client/
(cd console && npm ci && npm run build)     # and console/dist at /console/; GET / redirects there

# run the relay (settings from the environment or ./.env; everything has a default)
.venv/bin/ziv-relay init                        # creates the database, mints the admin token once
.venv/bin/ziv-relay run                         # http://127.0.0.1:8787; --host/--port/--allow-plain-http
.venv/bin/ziv-relay enroll-code                 # a short-lived device enrollment code
.venv/bin/ziv-relay sender add <label> --scopes send,read    # a scoped bearer token, shown once
.venv/bin/ziv-relay events --tail 50 [--kind K] # the content-free event log
# ZIV_DB_PATH, ZIV_HOST, ZIV_PORT, ZIV_ALLOW_PLAIN_HTTP (LAN bench only), ZIV_TLS_CERT/KEY, ZIV_ADMIN_TOKEN,
# ZIV_BUDGET_MS, ZIV_OUTBOX_CAP, ZIV_SCHEDULE_CAP, ZIV_RETENTION_DAYS, NEBIUS_API_KEY, NEBIUS_BASE_URL,
# ZIV_TEXT_MODEL … — the full list with defaults is ziv/relay/settings.py and the README's table.

# the Python suite (browser e2e and device-toolchain tests deselected by pyproject addopts)
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q tests/test_core_outbox.py                 # one module
.venv/bin/python -m pytest -q tests/test_relay_http.py::test_name       # one test
.venv/bin/python -m pytest -m e2e tests/e2e                             # browser tier; skips when Chromium cannot launch

# the timing spec and the contract
python3 tools/haptic_timing.py              # drift guard: spec vs all 7 generated consumers (exit 1 on drift)
python3 tools/haptic_timing.py --write      # regenerate consumers after editing docs/haptic-timing.json
.venv/bin/python -m ziv.wire schema/        # regenerate the JSON Schemas after editing ziv/wire.py
(cd console && npm run gen:types)           # then regenerate the console's TypeScript from schema/
(cd console && npm run gen:types -- --check)

# conformance (the cross-renderer oracle)
.venv/bin/python conformance/run.py --check                 # expected/ agrees with the reference
.venv/bin/python conformance/run.py --write                 # regenerate expected/ after a spec or reference change
.venv/bin/python conformance/run.py --player "node client/dist/conformance.js" --profile single_actuator
.venv/bin/python conformance/run.py --player "firmware/app/ziv_qemu/host_player" --profile six_actuator

# firmware (host C compiler required; exit 2 = no compiler)
python3 firmware/haptic_out/run_tests.py            # bench suite, mock DRV2605L
python3 firmware/app/ziv_qemu/run_ziv_tests.py      # rung-1 host demo + HAP fixture diff (not a QEMU boot)
python3 firmware/band/run_band_tests.py             # band unit tests, host_player conformance on both profiles, transport test

# front ends
(cd client && npm test && npm run typecheck)
(cd console && npm test && npm run typecheck)

# install the pre-commit hook once per clone (drift guard, schema diff, oracle check, bench)
git config core.hooksPath hooks
```

Last observed counts (2026-11-06): pytest `164 passed, 5 deselected`; drift guard 7 consumers in sync; oracle 12 utterances × 2 profiles; web renderer 12/12 on both profiles; bench 459; rung-1 49; band 636 + conformance 12/12 × 2 + transport 9; client 55; console 20. Quote counts only from a run you made.

CI (`.github/workflows/ci.yml`) runs three blocking jobs — `relay` (drift guard, schema diff, oracle check, client build, pytest), `renderers` (client and console typecheck/test/build, the web renderer against the reference on both profiles) and `firmware` (bench, rung-1, band) — plus the non-blocking `qemu-boot` skeleton that waits for an ESP-IDF install step.

Test harness notes: `ziv` is an installed package; `tests/conftest.py` does no `sys.path` work. Nothing in the suite sleeps for real time — anything that waits takes a clock (`ziv.relay.clock.FakeClock`), and the scheduler is driven by calling `tick(relay, now)`. `tests/relay_live.py` boots a real relay on a loopback port for the integration tests (which drive `client/dist/device-cli.js` on an instant clock) and for the e2e tier; both skip cleanly when `node`, the build or Chromium is missing.

## Architecture

The tree is the architecture in `docs/ARCHITECTURE.md`; read that first. The map:

**The wire contract — `ziv/wire.py`, schemas in `schema/`.** Every type that crosses a process boundary is defined here and nowhere else: the `Utterance` (words and intent, never milliseconds), the device frames both ways (`hello`, `hello.ack`, `utterance.open`, `utterance.body`, `utterance.cancel`, `pref.set`, `progress`, `played`, `nack`, `input.text`, `control`, `pref.changed`, `ping`/`pong`), the sender HTTP bodies and views, and the `Reason` enum every refusal carries. Models are `extra="forbid"` with hard sizes. `python -m ziv.wire schema/` emits the JSON Schemas the console's generated types (`console/src/generated/wire.ts`), the client's checks and the firmware decoder tests build against.

**The timing spec — `docs/haptic-timing.json` → seven consumers.** `tools/haptic_timing.py` generates and verifies the feel-tool's JS block (`docs/haptic-name-marks.html`), `firmware/haptic_out/haptic_timing.h`, `ziv/haptics/tables.py` (which also embeds the raw spec the relay serves at `GET /spec`), the tables in `docs/HAPTIC_TIMING_SPEC.md`, `firmware/app/ziv_qemu/main/ziv_demo_sequence.{h,c}` and the demo-chain block in `docs/QEMU_SIMULATION_LADDER.md`. Spec v4 added the word gap (520 ms), the working cadence (2000 ms), the kind → cue/tail table, the two renderer profiles and the conformance tolerance (10 ms).

**The reference renderer — `ziv/haptics/reference.py`.** `timeline(utterance, profile, pace_ms)` is the definition of correct playback; `duration_ms` is the time budget admission charges; `diff` judges a player's timeline. It adds structure only; every number is read from `tables.py` at call time.

**The pure core — `ziv/core/`.** No I/O, no clocks of its own. `outbox.py` is the per-wearer state machine — `pending → sent → playing → played`, with `failed`, `expired` and `cancelled`; failover and `device_gone` return an entry to `pending`; a nack for `hidden`, `muted` or `queue_full` re-offers, every other nack fails. Every function takes a slice of state, an event and `now` and returns the new slice plus effects (`SendOpen`, `SendBody`, `SendCancel`, `NotifySender`, `LogEvent`). `admission.py` normalises text to words (digits become words, punctuation dropped, unencodable refused unless `allow_lossy`) and refuses over the budget; `schedule.py` claims due rows under a lease; `credentials.py` hashes keys and tokens and compares in constant time. A Hypothesis state machine in `tests/test_core_outbox.py` proves no loss, no duplication, bounded depth.

**The store — `ziv/store/`.** One SQLite file, WAL, numbered migrations (`migrations/0001_init.sql`: wearers, devices, senders, utterances, schedule, prefs, replies, events, enroll_codes, meta), one transaction per transition, `BEGIN IMMEDIATE` around claims, an integrity check at start reported into `events`, retention by `RetentionPolicy`.

**The relay app — `ziv/relay/`.** `create_app(settings, clock=, store=, composer=, byok=)` is the only place the relay is assembled; there is no module state, and a test builds its own app. `service.Relay` is one unit of work per method: load the slice, call the core, write in one transaction, dispatch effects. `http.py` is the sender surface (bearer tokens scoped `send`/`read`/`admin`, every refusal JSON with a `reason`, status by `STATUS_FOR_REASON`); `ws.py` is the device socket (`/ws`; the first frame must be `hello` with the device key within the hello timeout or the socket closes 4401; a reader and a bounded writer per device); `scheduler.tick` claims, fires, expires, fails over, times out bodies, assigns and prunes; `composer.py` is `compose(intent, budget) -> words` behind one protocol with `Echo` (whole words dropped from the end until it fits, never letters), `Fake` and `Nebius` implementations, each measured with the same function admission uses; `static.py` serves the built front ends with hashed assets immutable and index pages `no-store`. `NotifySender` is accepted and ignored: senders poll `GET /utterances/{id}`.

**The renderer contract and the two profiles.** A renderer holds a bounded queue, plays one utterance at a time in the reference's order (prefix when present, cue, working pattern while `body_pending`, words with the pace inside a word and the word gap between, tail gap, close), reports `progress` at the cue, each word and the close, sends `played` when the close has finished on the actuator, and `nack`s with a reason when it cannot play. `six_actuator` drives a cell's dots together; `single_actuator` plays six 50 ms slots in dot order with a 30 ms slot gap and an 80 ms column break (530 ms per cell, provisional). Controls (stop, replay, replay word, skip, advance), pace and the advance mode (`auto`/`tap`) live on the device and sync through the relay as prefs.

**The web renderer — `client/`.** `device.ts` is the state machine, `sequencer.ts` the pure timeline (the reference's model, label for label), `player.ts` the deadline scheduler (drift never accumulates), `queue.ts` the persisted queue, `transport.ts` hello-first with backoff and resume, `spec.ts` the durations resolved from `GET /spec`. Two Node entries: `dist/conformance.js` (the player for `conformance/run.py`) and `dist/device-cli.js` (the headless device the integration tests drive). It refuses to play while hidden and says so (`nack hidden`). Foreground only, by the browser's nature.

**The console — `console/`.** Plain-DOM TypeScript against the generated types, esbuild with content-hashed assets, a strict same-origin CSP, a mock relay that validates bodies with Ajv, axe-core over every view. Accessibility is the acceptance criterion; the checklist is in its README. It never plays haptics.

**The conformance harness — `conformance/`.** The cross-renderer oracle: twelve golden utterances, their expected timelines on both profiles (generated by `run.py --write`, drift-guarded by `--check`), and `--player "<command>" --profile P` for any renderer that reads an utterance on stdin and prints `{"t_ms","dot_mask","buzz_ms","label"}` lines. Same beat count, exact mask and buzz, start within ±10 ms. The reference player, the web renderer and the band's `host_player` all pass 12/12 on both profiles.

**The firmware — `firmware/`.** `haptic_out/` is the host-portable C11 pull-model sequencer with a runtime pace and a generic beat mode, a mock DRV2605L bus and the bench. `band/` adds the utterance decoder (vendored cJSON, every schema cap a distinct error, nothing truncated), `turn.c` (one segment at a time into `haptic_out_play_beats`, matching the reference on both profiles), the bounded persisted queue with `last_acked`, and `transport.c` (the protocol behind a frame vtable: hello-first, backoff with jitter, resume by id, offline playback). What the runners prove: the bench (mock bus timings), rung 1 (the real sequencer's HAP log against the derived 27-line fixture on the host), the band suite (unit tests, `host_player` conformance, a loopback transport test against `host/fake_relay.py`, which validates every up frame with `ziv.wire`). What is unverified: everything under `firmware/band/esp/`, the device path of `drv2605_i2c_esp32.c` and the FreeRTOS task — written against ESP-IDF 5.x, never compiled (no IDF here); any QEMU boot; the feel on skin.

## Rules that bind here

- **Never hand-edit a generated file.** `ziv/haptics/tables.py`, `firmware/haptic_out/haptic_timing.h`, the fenced blocks in `docs/haptic-name-marks.html`, `docs/HAPTIC_TIMING_SPEC.md` and `docs/QEMU_SIMULATION_LADDER.md`, `ziv_demo_sequence.{h,c}`, everything in `schema/`, `console/src/generated/wire.ts` and `conformance/expected/`. Edit the source (`docs/haptic-timing.json`, `tools/build_ziv_demo.py`'s `DEMO_STAGES`, `ziv/wire.py`), regenerate, commit source and output together. The hook, the suite (`tests/test_timing_guard.py`, `tests/test_conformance.py`) and CI all fail on drift.
- **When `ziv/wire.py` changes:** `python -m ziv.wire schema/`, then `cd console && npm run gen:types`, then commit all three. The console build refuses stale types by hash.
- **No module state, injected clocks, no real sleeping in tests.** Build the app with `create_app`; take `Clock`; drive `FakeClock` and `tick(relay, now)`. A test that sleeps for real time is a bug.
- **Every refusal carries a `Reason`.** New refusals add to `ziv.wire.Reason` (and `STATUS_FOR_REASON` when they reach HTTP); the console's `describeReason()` must then name it or its typecheck fails.
- **No words in logs, events or health.** `events` rows and `Health` carry counts, states, reasons and durations only. The wire log on the client and the band shows frame types and ids. A bring-your-own-key credential reaches no log, event, row or response.
- **Bounded and loud.** Every queue has a cap; every drop is counted; a missing key or a failed compose is labelled on the wire (`source: echo`, `reason: compose_failed`), never papered over.
- **The 12-vs-16 asymmetry stays.** The feel-tool's `spell_max_letters` = 12 (page affordance) and the firmware's `HAPTIC_OUT_MAX_WORD_LEN` = 16 (runtime ceiling) are different settings for different layers; the drift guard checks both. Do not unify them.
- **The device renders; the relay sequences.** Nothing in `ziv/` may sleep through playback or carry a millisecond on the wire.

## Branches

The `main` branch still carries the hackathon-era tree (the server-paced relay, the PWA, the demo and recording material). The `product` branch is the product direction described here; do not reintroduce that material there.

## Conventions

- Conventional Commits, scopes `relay|client|console|firmware|spec|conformance|tools|docs|infra` (`server` in older history); subject ≤ ~72 chars, imperative; body says why. One logical change per commit. Details in `CONTRIBUTING.md`.
- Behavior changes get a `CHANGELOG.md` entry under `[Unreleased]`; README/CHANGELOG test counts must match a real run (the repo treats stale counts as a documentation bug).
- Design principles that recur in code review here: bounded memory everywhere (every queue has a cap, every drop is logged and counted); no silent fallback (a missing key or failed model call is labelled on the wire, not papered over); the channel is serial, so nothing may cut into a playing utterance — an arrival mid-play gets its cue and waits.
- `CHANGELOG.md` is history and keeps its old wording (track prefixes, SkillForge-era entries); only `[Unreleased]` is edited.
