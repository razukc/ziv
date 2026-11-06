# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Ziv is a haptic message channel for deaf-blind wearers. A relay (`ziv/`) admits, orders and tracks *utterances*; a device renderer — the web client (`client/`, the reference device and a foreground demo), the native Android app (`android/`, emulator-proven) and the band firmware (`firmware/band/`, host-proven, built for the ESP32-S3 on ESP-IDF v5.5 and booted under QEMU, not yet on a board) — plays each one on its own clock and acknowledges it; an accessible console (`console/`) is the senders' and caregivers' surface. One generated timing spec and one reference renderer define correct playback for every renderer. The design is `docs/ARCHITECTURE.md`; the tree implements it. The README's "What is built / what is next" table draws a hard line between what is **built and proven** and what is **next**. Do not move a claim across that line in docs without the matching code/test, and make no clinical or efficacy claims anywhere.

## Commands

Python 3.12+ (CI uses 3.12), Node 24, a host C compiler for the firmware suites. Optional: JDK 17 and the Android SDK for `android/`; ESP-IDF v5.5 and Espressif's QEMU for the device builds. The package installs into `.venv` at the repo root; the hook, the band runner and the conformance harness look there first.

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

# the Python suite (the browser and device tiers are deselected by pyproject addopts)
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q tests/test_core_outbox.py                 # one module
.venv/bin/python -m pytest -q tests/test_relay_http.py::test_name       # one test
.venv/bin/python -m playwright install --with-deps chromium             # once: the -m e2e tier needs a Chromium that can launch
.venv/bin/python -m pytest -m e2e tests/e2e                             # browser tier; skips when Chromium cannot launch
.venv/bin/python -m pytest -m device tests/device                       # device tier; needs a booted emulator or an attached phone and the debug APK; skips otherwise

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

# Android (JDK 17; the SDK at ~/android-sdk: cmdline-tools, platform-tools, platforms;android-35, build-tools;35.0.0,
# emulator, system-images;android-35;google_apis;x86_64) — android/README.md has the full recipe
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 ANDROID_HOME=$HOME/android-sdk
(cd android && ./gradlew :core:test)                # the JVM core
(cd android && ./gradlew :core:installDist)         # the conformance player -> android/core/build/install/core/bin/core
.venv/bin/python conformance/run.py --player android/core/build/install/core/bin/core --profile single_actuator
(cd android && ./gradlew :app:assembleDebug)        # -> android/app/build/outputs/apk/debug/app-debug.apk
# the emulator needs the user in the kvm group (or an ACL on /dev/kvm) plus libxkbfile1 and libpulse0; headless boot ~138 s
$ANDROID_HOME/emulator/emulator -avd ziv -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect -memory 2048 &
.venv/bin/python -m pytest -m device tests/device   # installs the APK and drives it against a live relay

# ESP-IDF v5.5 + Espressif QEMU (install: docs/QEMU_WINDOWS_INSTALL.md, Linux/WSL2 section; ladder: docs/QEMU_SIMULATION_LADDER.md)
. ~/esp/esp-idf/export.sh
export PATH="$HOME/.espressif/tools/qemu-xtensa/esp_develop_9.0.0_20240606/qemu/bin:$PATH"   # QEMU is an optional tool; export.sh does not add it
(cd firmware/app/ziv_qemu && idf.py set-target esp32s3 && idf.py build)       # ziv_qemu.bin
(cd firmware/band/esp_project && idf.py set-target esp32s3 && idf.py build)   # ziv_band.bin; fetches esp_websocket_client 1.8.0
(cd firmware/app/ziv_qemu && python3 run_ziv_tests.py && ./host_demo --hap-log > bench_hap.log)   # the bench side of rung 2
QEMU_UNTIL="$(tail -1 firmware/app/ziv_qemu/bench_hap.log)" \
    firmware/qemu_capture.sh firmware/app/ziv_qemu firmware/app/ziv_qemu/qemu_boot.log   # bounded capture, -icount, ~40 s
python3 tools/qemu_timeline.py firmware/app/ziv_qemu/bench_hap.log firmware/app/ziv_qemu/qemu_boot.log   # PASS — 27 HAP events
QEMU_UNTIL='transport: connect failed' QEMU_UNTIL_COUNT=3 \
    firmware/qemu_capture.sh firmware/band/esp_project firmware/band/esp_project/qemu_boot.log   # the band's boot shape

# front ends
(cd client && npm test && npm run typecheck)
(cd console && npm test && npm run typecheck)

# install the pre-commit hook once per clone (drift guard, schema diff, oracle check, bench)
git config core.hooksPath hooks
```

Last observed counts (2026-11-06, Ubuntu on WSL2): pytest `166 passed` with the 5 browser and 3 device tests deselected; browser tier `5 passed in 63.19s`; device tier `3 passed in 82.67s` on the `ziv` AVD (Android 15, KVM); drift guard 7 consumers in sync; oracle 12 utterances × 2 profiles; the web renderer, the band's `host_player` and the Android core each 12/12 on both profiles; bench 459; rung-1 49; band 636 + transport 9; client 55; console 20; Android core 46, debug APK 7.6 MB; ESP-IDF v5.5 builds `ziv_qemu.bin` (0x30dd0 bytes) and `ziv_band.bin` (0xe24d0 bytes) at `-Wall -Wextra -Werror`; QEMU rung 2 `PASS — 27 HAP events matched within tolerance`, zero drift. Quote counts only from a run you made.

CI (`.github/workflows/ci.yml`) has five jobs — `relay` (drift guard, schema diff, oracle check, client build, pytest), `renderers` (client and console typecheck/test/build, the web renderer against the reference on both profiles), `browser` (`playwright install --with-deps chromium`, both front ends built, `pytest -m e2e`) and `firmware` (bench, rung-1, band), all blocking, plus `qemu-boot`, a real build-boot-diff of both images on the `espressif/idf:v5.5` container that is `blocking since its first green run on GitHub. All five jobs ran green on GitHub on 2026-11-06 (run 42213019259).

Test harness notes: `ziv` is an installed package; `tests/conftest.py` does no `sys.path` work. Nothing in the suite sleeps for real time — anything that waits takes a clock (`ziv.relay.clock.FakeClock`), and the scheduler is driven by calling `tick(relay, now)`. `tests/relay_live.py` boots a real relay on a loopback port for the integration tests (which drive `client/dist/device-cli.js` on an instant clock), for the e2e tier and for the device tier; all skip cleanly when `node`, the build, Chromium, `adb`, the APK or a booted device is missing. `tests/device/test_android_renderer.py` installs the debug APK on whatever `adb` sees, launches the activity with the relay URL (`10.0.2.2` from the emulator) and an enroll code as debug extras, and waits for `played` on the relay side; `pm clear` resets runtime grants, so the harness re-grants `POST_NOTIFICATIONS` after clearing — otherwise the permission dialog from the first launch stays on top of the task and a relaunch never recreates the activity under it.

## Architecture

The tree is the architecture in `docs/ARCHITECTURE.md`; read that first. The map:

**The wire contract — `ziv/wire.py`, schemas in `schema/`.** Every type that crosses a process boundary is defined here and nowhere else: the `Utterance` (words and intent, never milliseconds), the device frames both ways (`hello`, `hello.ack`, `utterance.open`, `utterance.body`, `utterance.cancel`, `pref.set`, `progress`, `played`, `nack`, `input.text`, `control`, `pref.changed`, `ping`/`pong`), the sender HTTP bodies and views, and the `Reason` enum every refusal carries. Models are `extra="forbid"` with hard sizes. `python -m ziv.wire schema/` emits the JSON Schemas the console's generated types (`console/src/generated/wire.ts`), the client's checks and the firmware decoder tests build against.

**The timing spec — `docs/haptic-timing.json` → seven consumers.** `tools/haptic_timing.py` generates and verifies the feel-tool's JS block (`docs/haptic-name-marks.html`), `firmware/haptic_out/haptic_timing.h`, `ziv/haptics/tables.py` (which also embeds the raw spec the relay serves at `GET /spec`), the tables in `docs/HAPTIC_TIMING_SPEC.md`, `firmware/app/ziv_qemu/main/ziv_demo_sequence.{h,c}` and the demo-chain block in `docs/QEMU_SIMULATION_LADDER.md`. Spec v4 added the word gap (520 ms), the working cadence (2000 ms), the kind → cue/tail table, the two renderer profiles and the conformance tolerance (10 ms).

**The reference renderer — `ziv/haptics/reference.py`.** `timeline(utterance, profile, pace_ms)` is the definition of correct playback; `duration_ms` is the time budget admission charges; `diff` judges a player's timeline. It adds structure only; every number is read from `tables.py` at call time.

**The pure core — `ziv/core/`.** No I/O, no clocks of its own. `outbox.py` is the per-wearer state machine — `pending → sent → playing → played`, with `failed`, `expired` and `cancelled`; failover and `device_gone` return an entry to `pending`; a nack for `hidden`, `muted` or `queue_full` re-offers, every other nack fails. Every function takes a slice of state, an event and `now` and returns the new slice plus effects (`SendOpen`, `SendBody`, `SendCancel`, `NotifySender`, `LogEvent`). `admission.py` normalises text to words (digits become words, punctuation dropped, unencodable refused unless `allow_lossy`) and refuses over the budget; `schedule.py` claims due rows under a lease; `credentials.py` hashes keys and tokens and compares in constant time. A Hypothesis state machine in `tests/test_core_outbox.py` proves no loss, no duplication, bounded depth.

**The store — `ziv/store/`.** One SQLite file, WAL, numbered migrations (`migrations/0001_init.sql`: wearers, devices, senders, utterances, schedule, prefs, replies, events, enroll_codes, meta), one transaction per transition, `BEGIN IMMEDIATE` around claims, an integrity check at start reported into `events`, retention by `RetentionPolicy`.

**The relay app — `ziv/relay/`.** `create_app(settings, clock=, store=, composer=, byok=)` is the only place the relay is assembled; there is no module state, and a test builds its own app. `service.Relay` is one unit of work per method: load the slice, call the core, write in one transaction, dispatch effects. `http.py` is the sender surface (bearer tokens scoped `send`/`read`/`admin`, every refusal JSON with a `reason`, status by `STATUS_FOR_REASON`); `ws.py` is the device socket (`/ws`; the first frame must be `hello` with the device key within the hello timeout or the socket closes 4401; a reader and a bounded writer per device); `scheduler.tick` claims, fires, expires, fails over, times out bodies, assigns and prunes; `composer.py` is `compose(intent, budget) -> words` behind one protocol with `Echo` (the whole intent, else the intent without function words with the view marked lossy, else `over_budget` — never a cut-off prefix; `fit()` refuses an unfittable intent at schedule time, not when it fires), `Fake` and `Nebius` (one real call observed: 2.5 s, the three-attempt fit loop) implementations, each measured with the same function admission uses; `static.py` serves the built front ends with hashed assets immutable and index pages `no-store`. `NotifySender` is accepted and ignored: senders poll `GET /utterances/{id}`.

**The renderer contract and the two profiles.** A renderer holds a bounded queue, plays one utterance at a time in the reference's order (prefix when present, cue, working pattern while `body_pending`, words with the pace inside a word and the word gap between, tail gap, close), reports `progress` at the cue, each word and the close, sends `played` when the close has finished on the actuator, and `nack`s with a reason when it cannot play. `six_actuator` drives a cell's dots together; `single_actuator` plays six 50 ms slots in dot order with a 30 ms slot gap and an 80 ms column break (530 ms per cell, provisional). Controls (stop, replay, replay word, skip, advance), pace and the advance mode (`auto`/`tap`) live on the device and sync through the relay as prefs.

**The web renderer — `client/`.** `device.ts` is the state machine, `sequencer.ts` the pure timeline (the reference's model, label for label), `player.ts` the deadline scheduler (drift never accumulates), `queue.ts` the persisted queue, `transport.ts` hello-first with backoff and resume, `spec.ts` the durations resolved from `GET /spec`. Two Node entries: `dist/conformance.js` (the player for `conformance/run.py`) and `dist/device-cli.js` (the headless device the integration tests drive). It refuses to play while hidden and says so (`nack hidden`). Foreground only, by the browser's nature. The five browser tests in `tests/e2e/` drive the page and the console in headless Chromium against a live relay.

**The native phone renderer — `android/`.** `core/` is pure Kotlin/JVM with no Android dependency: `Spec.kt` (the v4 spec as `GET /spec` serves it; the web client's v3 fallbacks are not ported), `Wire.kt`, `Sequencer.kt` (the reference's model, label for label — `SequencerGoldenTest` holds it to `conformance/expected/` text for text), `Player.kt` (a deadline scheduler over injectable timers), `Device.kt` (the state machine ported from the web client), `Transport.kt` (hello-first, backoff, resume by `last_acked` + held), `QueueStore.kt`, `Words.kt` and `Main.kt`, the conformance player (`./gradlew :core:installDist`). `app/` is a foreground service (`RendererService.kt`) that owns the socket, the queue in SQLite, the Vibrator with amplitude waveforms, enrollment by code and backoff with a fresh hello, plus a Views-based screen with large labelled controls and live regions for TalkBack. The activity starts the renderer before it asks for the notification permission, so the channel never waits on a dialog. Debug builds allow cleartext to the emulator host and private ranges only; release is TLS only. Proven on the emulator by the three device tests; no real phone has run it.

**The console — `console/`.** Plain-DOM TypeScript against the generated types, esbuild with content-hashed assets, a strict same-origin CSP, a mock relay that validates bodies with Ajv, axe-core over every view. Accessibility is the acceptance criterion; the checklist is in its README. It never plays haptics.

**The conformance harness — `conformance/`.** The cross-renderer oracle: twelve golden utterances, their expected timelines on both profiles (generated by `run.py --write`, drift-guarded by `--check`), and `--player "<command>" --profile P` for any renderer that reads an utterance on stdin and prints `{"t_ms","dot_mask","buzz_ms","label"}` lines. Same beat count, exact mask and buzz, start within ±10 ms. The reference player, the web renderer and the band's `host_player` all pass 12/12 on both profiles.

**The firmware — `firmware/`.** `haptic_out/` is the host-portable C11 pull-model sequencer with a runtime pace and a generic beat mode, a mock DRV2605L bus and the bench. `band/` adds the utterance decoder (vendored cJSON, every schema cap a distinct error, nothing truncated), `turn.c` (one segment at a time into `haptic_out_play_beats`, matching the reference on both profiles), the bounded persisted queue with `last_acked`, and `transport.c` (the protocol behind a frame vtable: hello-first, backoff with jitter, resume by id, offline playback). What the host runners prove: the bench (mock bus timings), rung 1 (the real sequencer's HAP log against the derived 27-line fixture on the host), the band suite (unit tests, `host_player` conformance, a loopback transport test against `host/fake_relay.py`, which validates every up frame with `ziv.wire`). What the device toolchain proves (`acb67fb`): both images build on ESP-IDF v5.5 for the ESP32-S3 at `-Wall -Wextra -Werror` — `firmware/app/ziv_qemu` (`ziv_qemu.bin` 0x30dd0 bytes) and `firmware/band/esp_project` (`ziv_band.bin` 0xe24d0 bytes, `esp_websocket_client` 1.8.0 from the registry), so the band's websocket, NVS, Wi-Fi and I²C glue compile against the real headers; under Espressif QEMU the demo's 27 HAP events match the bench with zero drift under `-icount shift=5,sleep=off` (rung 2, `tools/qemu_timeline.py`, which accepts the raw capture since `74cd273`), and the band boots, initialises NVS and six mock drivers, plays the boot ramp-up, logs that no Wi-Fi is configured and backs off its transport without a panic or a reboot. Six defects the host build could not see were fixed there: a component-relative include path, an END event repeated on every idle step after the demo, a boot-relative HAP epoch the differ could never match, tick-based deadline waits that lose whole ticks under emulation (now `esp_timer` one-shots), cross-core wakes on an unpinned task, and a band main loop that blocked forever without Wi-Fi. `firmware/qemu_capture.sh` is the bounded capture (CI, docs and local runs alike); both `qemu_boot.log` files are committed evidence. What is unverified: a real ESP32-S3 board — no I²C transaction has executed, no motor has moved, and no real Wi-Fi or TLS frame has been carried by the band; the feel on skin.

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

- Conventional Commits, scopes `relay|client|android|console|firmware|spec|conformance|tools|docs|infra` (`server` in older history); subject ≤ ~72 chars, imperative; body says why. One logical change per commit. Details in `CONTRIBUTING.md`.
- Behavior changes get a `CHANGELOG.md` entry under `[Unreleased]`; README/CHANGELOG test counts must match a real run (the repo treats stale counts as a documentation bug).
- Design principles that recur in code review here: bounded memory everywhere (every queue has a cap, every drop is logged and counted); no silent fallback (a missing key or failed model call is labelled on the wire, not papered over); the channel is serial, so nothing may cut into a playing utterance — an arrival mid-play gets its cue and waits.
- `CHANGELOG.md` is history and keeps its old wording (track prefixes, SkillForge-era entries); only `[Unreleased]` is edited.
