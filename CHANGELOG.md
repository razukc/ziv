# Changelog

All notable changes to SkillForge are tracked here, one entry per milestone
tag (see [CONTRIBUTING.md](CONTRIBUTING.md)). Format follows
[Keep a Changelog](https://keepachangelog.com/); the project is in the
pre-release phase, so milestones are tagged `pre-v0.1.x` until the public
`0.1.0`.

## [Unreleased]

- **The client renders a refusal instead of failing silently** — when the relay answers 429 (replay queue full), the dev-band PWA now shows a plain-language "wrist is busy — try after the current message" note in the header state, the wire log ("✋ refused … your text stays in the box"), and the Omni mic status, instead of one dim HTTP line. Honors the server contract that the wrist stays silent for a refusal: the note is visual only, no vibration is fired, and the drafted text remains in the input so the retry is one tap. Both send paths are covered (``/api/ziv/message`` and ``/inject/audio``), and the page's help text says what a refusal means.

- **Queue-rejection telemetry in health** — ``GET /api/ziv/health`` now carries ``queue_rejections`` (cumulative ``count``, a ``per_minute`` rate over the last 60 s, ``last_reason``, ``last_at``), so the operator can see the 429s the relay hands out instead of only the sender feeling them: every ``message:rejected`` the gate returns is counted with its reason and a wall-clock timestamp. The rate makes a spike visible at a glance — a growing total hides it in the middle digit; recent timestamps live in a bounded deque, lazily pruned on read (no background task). Cumulative by design (a lifetime signal, unlike the drain-on-read corrupt-store lists); reset by the test fixture like the rest of the process-wide relay state. Hermetic tests prove a zeroed snapshot before any refusal, count=2/``per_minute=2``/``queue_full`` after two overflowing posts, and that a refusal aged past the window drops out of the rate while the cumulative count keeps it.

## [pre-v0.1.44] — 2026-09-17 — Personal AI: the tracks separate, the demo single-sources, the seam hardens

- **Seam hardened against concurrent transports** — the last held-for-later idea, now landed. `MessageGate` is the seam's serialization point: every decision (`admit`/`begin_playback`/`close_event`/`playing`/`__len__`) is atomic under an internal reentrant lock, so websocket + HTTP + audio arrivals racing a turn queue, play, or are refused atomically — never lost, duplicated, or corrupted; the lock serializes *decisions*, not turns (the caller's turn lock still owns the channel). The replay queue is bounded (`MessageGate.MAX_QUEUED = 8`, plan §9 bounded-memory discipline, deliberately below the 20-entry day-scale inbox cap): a full queue answers `message:rejected` (`reason: queue_full`, `cap`) — the sender is told no loudly and the wrist feels nothing; the dev-band server maps it to HTTP 429. Real bug found and fixed on the way: `deliver_inbox_one` peeked the inbox *outside* the turn lock, so two concurrent deliveries could both play the same entry — the peek now happens under the lock, and an asyncio race test proves two deliveries pick two different messages. Proof, not prose: five threaded tests (a barrier-synchronized stampede queues every arrival with zero loss/duplication, a 20-thread overflow stampede queues exactly MAX_QUEUED and rejects the rest, reject-never-enters-queue, conservation under admit/close cycles — closed + still-queued == admitted, and a coherence watcher over racing players), plus the 429 mapping and no-frame-on-refusal tests. Ziv suite at 94, timing drift guard untouched, 49-check C bench green.

- **Ladder doc unified with the demo single source** — docs/QEMU_SIMULATION_LADDER.md's rung-1/rung-2 demo chain is now a generated consumer of the timing spec, the seventh behind the drift guard: `tools/build_ziv_demo.py` renders its `DEMO_STAGES` table into a per-stage markdown table (stage names, wall-clock spans, durations, total 7310 ms across 27 HAP lines) spliced between `haptic-demo-chain` markers, and `tools/haptic_timing.py --write` regenerates it while `--verify` fails on any hand edit to the block — the doc can no longer describe a demo the app does not play. The prose around the block was reworded to point at the single source instead of restating the chain, and the drift-guard test grew a dedicated consumer test (markers present, tamper → verify exit 1 → heal byte-identical, stage rows equal `DEMO_STAGES`, total equal to the fixture's final HAP timestamp) plus `LADDER_DOC_PATH` in its private-copy sandbox. Also cleaned: the generator carried a doubled `BANNER`/`_fixture_lines` block from an interrupted edit — one definition again, all seven consumers green.

- **Track separation** — SkillForge and Ziv now build, test, and run independently, meeting only at the shared primitives. The generic compose scaffold moved out of [agent/ports.py](agent/ports.py) into [agent/relay_compose.py](agent/relay_compose.py) (SkillForge-owned: `RelayResult`/`RelayConfig`/`RelayAdapter`/`relay_run_turn`), and ports.py keeps only common infra — retry (with the private `_sleep_with_backoff` now public as `sleep_with_backoff`, which [agent/reasoning_agent.py](agent/reasoning_agent.py) no longer imports as a private name), SSE, the telemetry ring, and the mock-mode switch. [agent/ziv_relay.py](agent/ziv_relay.py) is self-standing: it owns its `TurnEvent` vocabulary, `ZivRelayAdapter` has no base class and a duck-typed `run_turn`, and the e2e canned adapter drives the Ziv seam directly (`run_turn` → `TurnEvent`, no compose wrapper). The Ziv + timing suites live in [agent/tests_ziv/](agent/tests_ziv) with their own conftest so the SkillForge conftest's store/server fixtures never load for them; CI runs the two suites as separate steps so one track's failure is visible per-track. Isolation is proven, not prose: contract tests assert neither seam references the other track's modules, and fresh-process import probes show no leakage in either direction — both suites green (SkillForge 91, Ziv 85), the timing drift guard in sync across all six consumers, and the 49-check host bench passing.

## [pre-v0.1.43] — 2026-09-14 — Personal AI: the Omni spike is real — phone mic → Token Factory → braille

The week-1 spike's phone half no longer waits on hardware: the PWA records the mic with MediaRecorder (opus/webm, 10 s cap, mime negotiated and mapped to the API's format names) and posts the clip base64 to `/inject/audio`, where the relay transcribes it with **Nemotron-3-Nano-Omni** on Nebius Token Factory — the OpenAI-compatible chat-completions call with an `input_audio` content part, the same `NEBIUS_API_KEY`/base URL the repo's SkillForge agent already uses, temperature 0 and a transcribe-only prompt. The guard is honest by design: without a key the endpoint answers **503** with a hint to the keyless stub (health surfaces `omni.key_set`), provider failures answer **502** with the provider's words — the phone shows the failure, never a silent drop. The transcript takes the *same* turn a typed message takes (cue → ticks → cells → close → queue), so `source` now distinguishes `audio_omni` from `audio_stub`, and the `simulate` path stays hermetic. Tests mock the HTTP layer and assert the wire contract itself (URL, bearer, model id, `input_audio` shape) plus the failure paths — **23 server tests**; live check: a 157 kB webm clip captured in the preview, posted, and the 503 guard rendered verbatim on the phone UI, stub turn complete in 10.7 s.

## [pre-v0.1.42] — 2026-09-14 — Personal AI: relay v1 — the wearer's durable state (memory files + persistent inbox)

The dev-band relay keeps everything in process memory: a message that arrives with no band attached vanishes, and the wearer's playback pace resets on every restart. [agent/ziv_store.py](agent/ziv_store.py) gives the wearer two durable things. **`WearerMemory`** — per-wearer key/value files under `agent/ziv_data/` (gitignored: the wearer's data, not repo state), atomic writes (temp + `os.replace`, the pipeline-store discipline), corrupt files discarded and *reported* through health, never silently swallowed; the playback pace is the first stored preference, clamped into the spec's cell-gap envelope on every read — parameters personal, structure universal. **`MessageInbox`** — a capped (20) persistent inbox: with no band attached a message is stored, not dropped (409 → 200 `inbox:stored`), and on the next attach each pending message is delivered as its own full event (cue → cells → close) and only *then* marked delivered — the peek/mark split means a band vanishing mid-delivery leaves the message pending: redelivery is the failure mode, never loss. New endpoints: `GET/DELETE /api/ziv/inbox`, `GET/POST /api/ziv/prefs`; `hello` carries `inbox_pending`, and health reports inbox count, prefs, and store problems. 8 store tests + 6 server tests take the suite to **159 passing**; found while testing: the two v0-era "no band" tests still asserted the drop (409) — rewritten for the storage contract, including a real mid-turn band-vanish 409 via a `_push` monkeypatch.

## [pre-v0.1.41] — 2026-09-14 — Personal AI: the phone is the dev band — relay v0 + the PWA client

The wrist pin does not exist yet, but the whole MVP loop now demos on hardware everyone already owns: [agent/ziv_server.py](agent/ziv_server.py) is relay v0 — a FastAPI WS relay (`/ws` device transport with optional `ZIV_RELAY_TOKEN` auth, one process-wide `MessageGate` so the queue-don't-interrupt invariant holds *across* HTTP calls, an asyncio turn lock) whose turn pump drives the real seam — the opening kind cue, `processing` ticks on the 2 s cadence while the fake model sleeps (`ZIV_FAKE_MODEL_SECONDS`), content spelled cell-by-cell at the generated module's cell gap, the `end-of-message` close, then any queued replays with their own full cue→cells→close journeys. The PWA client ([agent/ziv_client/index.html](agent/ziv_client/index.html)) renders every frame through the Vibration API and bootstraps **all** its timing from `GET /api/ziv/timing` — the serialized generated module, so phone, firmware header, and tests share one derivation with zero hand-copied numbers; cells highlight in sync with the server's playback dwell, and an unlock gesture satisfies Chrome's user-activation rule. `/inject/audio` is the week-1 Omni spike's seam: the same turn semantics a real mic → Token Factory call will produce, so the spike runs against the phone while hardware ships. Verified live on :8787 — WS round-trip cue→ticks→cells→close in 5 s, 8 frames on the wire; 12 new hermetic tests (journey order, queue+replay across threads, timing parity, audio stub, auth, health) take the suite to **145 passing**. Generator gains the playback envelope + spell cap in the Python consumer (four consumers re-synced).

## [pre-v0.1.40] — 2026-09-14 — Personal AI: the timing spec's fourth consumer — a generated Python module

The timing truth had three generated consumers (feel-tool JS block, firmware header, spec doc tables) but Python sides still re-derived numbers by hand: the e2e suite walked `docs/haptic-timing.json` with its own `_spec()`/`_cell_ms()`/`_expected_beats()` helpers, the exact class of informal drift the generator exists to kill elsewhere. `tools/haptic_timing.py` now emits [tools/haptic_timing_gen.py](tools/haptic_timing_gen.py) — constants, dot masks, cell durations, pattern beats, marks, and the prefix composition, in spec order (index == the C `HAPTIC_PAT_*` enum) — and the verify mode diffs it like every other consumer, so the drift guard holds all four. The e2e suite imports the module instead of re-deriving (`HapticTimelineMock` reads beats from it, the lifecycle-pattern test asserts its tuples, the relay-contract test resolves the seam's pattern names against it); `test_haptic_timing.py` gains a module-version guard and its sandbox learns `PY_PATH`, as does the rename tool's `-a` round trip. Two emitter bugs the fixtures caught: single-beat patterns emitted as a flattened pair (`((600, 420))` — now always a trailing comma), and a mark-cells join that would misshape a single-letter mark. Suite at **133 passing**.

## [pre-v0.1.39] — 2026-09-13 — Personal AI: the invariants become a state machine — TurnTimeline

The six early-years interaction invariants stop being prose and scattered pieces (`MessageGate` owns queueing, lifecycle kinds are constants) and become one tested artifact: `TurnTimeline` in [agent/ziv_relay.py](agent/ziv_relay.py), the turn as the wearer feels it — kind cue → `processing` ticks → playing → `end-of-message` close → gate release with any queued replays. The machine owns the ordering (a cue before content, the close before the release), the clock (`poll()` re-emits `processing` on the ~2 s cadence from the relay's natural loop tick — no timer thread — and never re-arms a finished turn), the gate (PLAYING engages `MessageGate`; `finish_playback` plays the close, then drains FIFO with prefixes), and the failure path (`long-buzz`: latency with an ending). Misuse is loud: out-of-order transitions raise in the seam instead of emitting a wrong-on-the-wrist sequence — invariant 5 enforced structurally. Five new e2e tests prove the journey in order, the 2 s cadence boundary (due at exactly 2/4/6 s), the queue release FIFO, the error path, and the rejection of skipped states; suite at **132 passing**. Found while testing: `MessageGate.__len__` makes a fresh gate falsy — `gate or MessageGate()` in a test helper silently swapped gates; now an explicit `is None` with a comment.

## [pre-v0.1.38] — 2026-09-13 — Personal AI: CI runs every suite — the health job closes the runner gap

CI had already drifted from the code: the workflow ran the drift check, the hermetic suite, and the haptic bench, but not the new `run_ziv_tests.py` (49 checks) — the exact class of gap the repo's "drift cannot be committed" story exists to prevent, hiding between suites. The workflow is now one `verify` job with four named surfaces (timing drift check → agent pytest → haptic bench → ziv_qemu host suite), so every suite that exists runs on every push. The ziv runner gained portability for the CI working directory (paths resolved from the script location, runnable from the repo root) and prefers the repo venv's ziglang over PATH probing, matching the bench suite's compiler on machines without a host gcc (the runner has gcc preinstalled; both compilers work). Repo root also gitignores the stray zig-cache dirs from the env-var experiment and the agent session state. All four surfaces verified green locally (drift check ok · 127 pytest passed · 274 + 49 checks, 0 failures).

## [pre-v0.1.37] — 2026-09-13 — Personal AI: the local QEMU install guide

[docs/QEMU_WINDOWS_INSTALL.md](docs/QEMU_WINDOWS_INSTALL.md): the one-time path from this Windows machine to ladder rung 1's actual boot — ESP-IDF install (managed Python, short `IDF_PATH`, the Git-Bash/PowerShell bridge), the Espressif QEMU fork via `idf_tools.py install qemu-xtensa` (and the upstream-shadowing check), then the `idf.py qemu monitor` smoke test on `firmware/app/ziv_qemu` whose pass criteria are the rung-1 fixture itself: the 27 `HAP` lines in order, wall-clock `at_ms` with the deltas as the assertion. Troubleshooting table first moves, CI-promotion and rung-2 capture as the after-steps; machine-specifics marked ⚠ per repo discipline. Ladder doc and app README point to it.

## [pre-v0.1.36] — 2026-09-13 — Personal AI: QEMU ladder rung 1 — the boot app's host-proven core

[firmware/app/ziv_qemu/](firmware/app/ziv_qemu/) exists: the ESP-IDF project that boots the real `haptic_out` sequencer in Espressif's QEMU fork (spec: [QEMU_SIMULATION_LADDER.md](docs/QEMU_SIMULATION_LADDER.md)). The haptic backend is the bench mock bus reused verbatim — one bus implementation shared by bench, QEMU, and these tests — and the `HAP` timeline lines are emitted from `haptic_out_step()`'s own event stream (`HAP <at> BUZZ <mode> <payload> <mask> <buzz> <gap> <seq>`), so the log is the firmware's testimony, not a parallel model. The host-portable core (`ziv_app.c`: sequencer + HAP emission + scripted boot demo + console name→index dispatch) is proven on this machine with **49 checks, 0 failures**: the scripted demo (`ramp-up → prefix(message) → word "ok" → end-of-message → heartbeat`) plays its complete 27-line fixture exactly — every start time, payload name, dot mask (mark cells carry the letter bitmasks, attention/lifecycle patterns step `00`), buzz duration, gap, and beat index. Two real bugs found by encoding the fixture: a comment typo broke the header for C compilers (`HAPTIC_PAT_*/` inside a block comment), and the demo's final END chained one step too far, emitting a spurious second END (now returns 0 when the demo just finished). `run_ziv_tests.py` mirrors the bench runner's zero-warning discipline (`-Wall -Wextra -Werror -std=c11`); rung 2 (the bench-vs-QEMU differ) now has its exact fixture locked. The IDF shell (`app_main.c`) is written to compile under ESP-IDF; the QEMU boot itself awaits an IDF/QEMU install. Both suites green (49 + 274 checks).

## [pre-v0.1.35] — 2026-09-12 — Personal AI: the QEMU simulation ladder

[docs/QEMU_SIMULATION_LADDER.md](docs/QEMU_SIMULATION_LADDER.md) specs how the real Ziv firmware binary runs on the host with no board: an ESP-IDF app (`firmware/app/ziv_qemu`) boots in Espressif's QEMU fork with the **bench mock bus reused verbatim** as the haptic backend (no second mock — rung-2 equivalence compares like with like), while the `HAP` timeline lines come from the sequencer's own `haptic_out_step()` event stream — the real firmware's testimony, not a parallel model. The scripted boot demo (ramp-up → prefix → word → end-of-message → heartbeat) exercises every mode including both spec-v3 lifecycle patterns; WiFi and the mic stay out of rung 1 on purpose and return at rungs 3–4 behind `ziv_transport`/`ziv_audio_source` vtables, the same seam discipline as `drv2605_bus`. CI shape: a `qemu-boot` job asserting the demo's `HAP` sequence, promoted to blocking after its first green run. Plan §5 points to the ladder; ROADMAP carries rung 1 as the next firmware item.

## [pre-v0.1.34] — 2026-09-12 — Personal AI: the early-years invariants — lifecycle patterns + the queue-don't-interrupt gate

The Sense UK early-years guidance (via Insight, sourced in the plan) turns into design law: plan §4 gains six **interaction invariants** — no content without a kind cue first; cues mark start *and* end; waiting is legible; queue, don't interrupt; structure universal, parameters personal; every state transition feelable — and the code grows the two patterns the invariants demanded.

- **Spec v3** — two lifecycle patterns join [docs/haptic-timing.json](docs/haptic-timing.json): `processing` (two ticks whose 350 ms middle gap is the ellipsis — double-tap's is 160, heartbeat's 120) and `end-of-message` (200→140→90→50, the exact mirror of ramp-up — until it plays, the silence after a last cell was indistinguishable from the gap before a next one). The validator learns the `fall` kind; consumers regenerated (feel-tool, firmware header, spec tables); the M1 distractor pool now draws 4 from 9 and the M3 confusion screen covers the lifecycle patterns; the bench suite re-passes (274 checks, 0 failures) against the regenerated header.
- **The first real relay behavior** — `MessageGate` in [agent/ziv_relay.py](agent/ziv_relay.py): while content plays, an incoming message gets its attention cue only (`attention:double-tap`) and queues its text; the wearer releases the queue by closing the event, and drained messages play FIFO with their full who→why prefix (invariant 1 holds for queued content too). The seam also exports the turn lifecycle kinds (accepted → `processing` → `playing` | `error`, `playback_done` closes), and the e2e test proves spec ↔ firmware header ↔ feel-tool name the same states. Four new hermetic tests take the suite to **127 passing**.
- **Docs** — plan §4 (invariants subsection + vocabulary rows), §7 (compose mode has no server-side timeout — chord composition is slow by design), §9 (vocabulary-crowding and motor-ability risks), §9 parked v2 ideas (per-contact people-marks; an on-device practice mode), §12 pitch line, the naming protocol's M1/M3 screens, and [DEVPOST_HAPTIC.md](DEVPOST_HAPTIC.md): a "Grounded in Deafblind Practice" section tells the invariants → patterns → gate story as evidence of user-grounded design (with the no-clinical-claims rule restated in place), plus supporting edits in Design Decisions, What's Next, uniqueness/challenges answers, and the demo outline (the queue rule gets its on-camera beat); a stale pre-rename "R-A-Z" reference fixed to Z-I-V.

## [pre-v0.1.33] — 2026-09-09 — Personal AI: rename candidates validated by the checker, not by hand

Option-B rename management becomes mechanical. `tools/rename_check.py <word>…` checks a candidate against the mark's dot-count arc through the same validation engine (`rename_word_problems`, extracted) the timing checker uses to self-validate the spec — so a candidate that fails never reaches the spec, and a hand-edited spec entry that fails fails the checker. Failure messages carry both shapes ("'nattin' spells 4-1-4-4-2-4 (heavy-light-heavy-…) — the 'ziv' mark is 4-2-4"); the mark's own word is rejected (option B changes the word), as are non-letters and words beyond the spell cap. `-a` adds passing words to `rename_examples` and regenerates all three consumers via the refactored `write_consumers()` path — refusing entirely if any listed word fails — and the drift guard + pre-commit hook then hold the spec and consumers together at commit time. The spell-box limit joined the spec (`ui.spell_max_letters`, generated into the page as SPELL_MAX; the firmware's 16-letter ceiling stays the stronger player). 13 new tests (engine rules, CLI exit codes, sandboxed add round-trip + refusal + idempotence) take the hermetic suite to 117 passing.

## [pre-v0.1.32] — 2026-09-09 — Personal AI: the M1 data-collection protocol and gate analyzer

The naming protocol's M1 measure becomes a defined data pipeline: §3a specifies the capture contract (the feel-tool session CSV), the session tiers (tier 1: 5 usable sessions — first gate; tier 2: 20 sessions across ≥ 4 participants — the evidence tier for the §5 rename conversation; tier 3: live rename-candidate pivot), the success gates (≥ 80% mark-only accuracy, no session below 3/4 mark rounds, zero M3 mark-vs-content confusions, pooled median RT ≤ 5 s), the failure-path triage (floor miss → retune the arc; RT/late failure with accuracy fine → short-cell rhythm problem; fast confident misses → arc confusion), and the analysis rules (the analyzer computes the gate, never the facilitator; CSVs are never rewritten; tiers are never pooled).

`tools/m1_summary.py` applies those gates deterministically (exit 1 on gate failure, 2 on unusable input) — per-session metrics (mark-only accuracy, median RT, late count, replays, M3 confusions, distractor false alarms), tier gates with per-check detail, `--json` output. The feel-tool session mode gained the one field the protocol needed: a 10 s answer deadline — an unanswered round is scored not-name and flagged `late:1` (unanswered is data, not a dropped round), with replay restarting the window and abort clearing the timer. 15 new analyzer tests take the hermetic suite to 104 passing.

## [pre-v0.1.31] — 2026-09-09 — Personal AI: the hardware bring-up checklist

[docs/HARDWARE_BRINGUP.md](docs/HARDWARE_BRINGUP.md): parts list (ESP32-S3 devkit, six DRV2605L breakouts behind a TCA9548A mux, 2–3 V LRAs, external 5 V motor rail with mandatory common ground), the dot-map wiring (dot n = mux channel n−1), and a six-stage flash-and-feel test — I2C scan, one dot, then the first phone-vs-band comparison of the Ziv mark, the full §4 attention table, the who→why prefix, and bus-fault drills. Every register, constant, and API name is verified against the module sources; writing it caught two gaps in the task sketch itself (no header, no `haptic_post_prefix`), both documented for the bring-up session.

## [pre-v0.1.30] — 2026-09-08 — Personal AI: the bench suite's first real compile

The haptic_out bench suite compiled and ran on this machine for the first time: `ziglang` installed into the agent venv (`pip install ziglang`, self-contained, no machine-wide changes), `run_tests.py` taught the `python -m ziglang cc` fallback. Result: **274 checks, 0 failures**, zero warnings under `-Wall -Wextra -Werror -std=c11`. The compile caught three real defects the hand-review had missed:

- **Module — gap ownership**: after a buzz ended, the sequencer took the following silence from the *next* beat's `gap_after_ms` instead of the beat that just buzzed. That stretched every inter-beat silence to the wrong value (the prefix's 550 ms breath landed one beat early, double-tap's second tick fired 260 ms late). The silence now comes from the buzzing beat's own gap — the same `gap_after` semantics the phone plays.
- **Module — stale deadline across plays**: `begin_play` reset the state flags but not `next_deadline`, so a play started right after another one waited out the previous play's leftover deadline before its first buzz. Fixed (would have stalled a prefix played back-to-back).
- **Test harness — contract violations**: `run_play` pre-initialised the event output (reading its own stale value on no-event returns) and treated a `0` return as end-of-play even though the *first* call legitimately returns 0 for the START event; `CHECK_EQ` mixed `uint32_t` with `int` literals (a `-Wsign-compare` trap). Plus one wrong hand-computed expectation (the raz timeline assumed Ziv's 170 ms `i` instead of `a`'s 110 ms).

Bench build artifacts are now gitignored.
## [pre-v0.1.29] — 2026-09-08 — Personal AI: the drift guard reaches CI

Repo commit: a GitHub Actions workflow ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs on every push — the hermetic suite (`agent: python -m pytest -q`, e2e deselected), the haptic timing verify (`python tools/haptic_timing.py`), and the haptic_out bench suite. The runner has gcc preinstalled, so the bench tests compile and run for real in CI even on machines without a C toolchain. Triggered on every branch push, with a manual `workflow_dispatch` for ad-hoc runs.

## [pre-v0.1.28] — 2026-09-08 — Personal AI: haptic_out firmware module — and drift can no longer be committed

Docs commit: the band's haptic channel gets its first real code — the cell sequencer + pattern player drafted around the generated header — and the spec's one-clock guarantee gets teeth: a pre-commit hook and a hermetic test refuse any commit that ships spec drift.

- **The module** — [firmware/haptic_out/](firmware/haptic_out/) drafts the plan §5 `haptic_out` unit: `haptic_out.c` is a pull-model state machine (the app calls `haptic_out_step(now_ms)` and gets the next deadline back — no blocking, no sleeps) that plays marks, attention patterns, arbitrary words, and the name-mark prefix (mark → 550 ms breath → tail) from the generated timing tables; `drv2605.c` is the register-level DRV2605L driver in real-time playback mode (one cell = six dot channels at their levels for `buzz_ms`, then zero); `drv2605_i2c.h` abstracts the bus behind a vtable so the same code runs on the bench and the band; `haptic_out_task.c` + `drv2605_i2c_esp32.c` + `CMakeLists.txt` sketch the ESP-IDF glue (TCA9548A mux, FreeRTOS task) pending real hardware.
- **Mock DRV2605L + bench suite** — `mock_drv2605.c` emulates six register files behind the mux with fault injection; `test_haptic_out.c` drives the real sequencer against it and asserts exact timelines (buzz start, duration, gap, dot bitmask per beat) against the generated tables — including the rename-arc property (tin/wiz spell the same arc as ziv) — plus a dead-dot-channel error path. `run_tests.py` builds and runs it with any host C compiler (auto-detected; skipped when none is installed).
- **Phone fix found by encoding the spec** — the prefix player placed the 550 ms breath *after* the tail's first tick instead of between the mark and the tail; the firmware work forced the exact semantics, the phone now matches (verified in the preview: mark → 550 → tail).
- **The guard** — [hooks/pre-commit](hooks/pre-commit) (install: `git config core.hooksPath hooks`) runs the timing verify + bench suite before every commit and blocks on drift; [agent/tests/test_haptic_timing.py](agent/tests/test_haptic_timing.py) runs the same verify in the hermetic suite and proves the checker itself detects drift (it caught a latent crash in the checker's own path handling — fixed). 89 hermetic tests pass.

## [pre-v0.1.27] — 2026-09-08 — Personal AI: spell any word — the full 26-letter vibro-braille alphabet in the feel-tool

Docs commit: the haptic feel-tool grows a **Spell any word** box — type any word (a–z, up to 12 letters) and feel it spelled one cell per letter, powered by the timing spec's full alphabet. This is the tool for the week-6 rename conversation (protocol §5): option B candidates can be felt live in the room.

- **Dot positions join the single source** — [docs/haptic-timing.json](docs/haptic-timing.json) v2 adds `letter_patterns` (dot positions 1–6 per letter, verified against the standard Grade-1 table) alongside the existing dot counts; the Unicode braille glyphs and the firmware's per-letter motor bitmask are now *derived* from them, not hand-written. The generator cross-checks counts against positions and validates the new `rename_examples` block.
- **The generated LETTERS table** — [docs/haptic-name-marks.html](docs/haptic-name-marks.html) no longer hand-writes the 8 letters the marks use; all 26 letters (dot count + glyph) are generated into the timing block, and the verifier checks them. A drift in the spec's alphabet now fails `tools/haptic_timing.py` instead of shipping silently.
- **Spell any word box** — text input with a–z normalization (case/punctuation stripped, 12-letter cap), per-letter cell rendering (glyph · dots · ms), playback through the shared sequencer (loop + gap slider respected), replay, and a one-row CSV log (word, per-letter dot counts and cell durations, gap, timestamp).
- **Rename-candidate quick fills** — the spec's `rename_examples` (protocol §5 option B: words that spell the same dot-count arc as Ziv — currently *tin*, *wiz*, arc-validated only) generate one-tap buttons on the page and are documented in [docs/HAPTIC_TIMING_SPEC.md](docs/HAPTIC_TIMING_SPEC.md).
- **Firmware gains the dot bitmask table** — `HAPTIC_LETTER_MASKS[26]` in [firmware/haptic_out/haptic_timing.h](firmware/haptic_out/haptic_timing.h) (bit n = dot n), the plan §5 cell → bitmask step, plus a `HAPTIC_RENAME_*` block mirroring the spec's rename examples.
- **Fix: abort race in session mode** — aborting inside the 600 ms answer-pause crashed the pending round transition (`sess` already nulled); guarded.

## [pre-v0.1.26] — 2026-09-08 — Personal AI: one clock for wrist and phone — haptic timing extracted into a generated spec

Docs commit: every buzz and silence the haptic channel plays now has exactly one source — [docs/haptic-timing.json](docs/haptic-timing.json) — and both players are generated from it, so the phone mock and the band can no longer drift apart.

- **Canonical spec** — constants (cell base/per-dot, cell-gap default + tuning envelope, tick, tick-gap, long buzz, tail gap, prefix breath), the full 26-letter Grade-1 dot table, the five candidate marks, the five attention patterns with each beat annotated by the constant it references, and the prefix composition (mark → 550 ms breath → tail). Feel-tool-only affordances (play lead-in, loop restart, slider step) are marked `ui`, so the firmware never inherits page quirks.
- **Generated consumers** — `tools/haptic_timing.py --write` rewrites the feel-tool's timing block and gap slider ([docs/haptic-name-marks.html](docs/haptic-name-marks.html)) and emits [firmware/haptic_out/haptic_timing.h](firmware/haptic_out/haptic_timing.h) — the plan §5 module's first artifact: compile-ready C with the beat struct, per-pattern tables, a dispatch enum + table, the 26-letter cell durations, and the mark letter-index arrays. The readable tables live in [docs/HAPTIC_TIMING_SPEC.md](docs/HAPTIC_TIMING_SPEC.md), generated too.
- **Drift is a failure** — `python tools/haptic_timing.py` in verify mode regenerates every consumer and diffs it against what is on disk (block text, slider envelope, the page's LETTERS/MARKS tables, the M1 distractor pool ids) and exits non-zero on any mismatch; the JSON itself self-validates (beat ranges, constant references, the tail rule, mark letters).
- **Behavior unchanged** — the generated block emits the same numbers the hand-written code had; `PREFIX_BREATH` replaces the hard-coded 550 ms in the prefix player, and PREFIX_TAILS look patterns up by id instead of array position, so reordering the JSON cannot silently swap a prefix tail.

## [pre-v0.1.25] — 2026-09-08 — Personal AI: the feel-tool's §4 attention vocabulary is complete — ramp up + heartbeat tick

Docs commit: the two remaining plan §4 patterns join the haptic feel-tool — the whole attention table can now be felt on the phone.

- **Ramp up = booting / connecting** — four quick ticks swelling in length (50 → 90 → 140 → 200 ms; the Vibration API has no amplitude control, so the ramp is duration), rendered as ▴ cells. Boot/reconnect only, never during playback.
- **Heartbeat tick = alive check** — a lub-dub of two 70 ms ticks 120 ms apart, ♥ cells; the card carries the plan §4 caveat verbatim: configurable, off by default, an occasional pulse rather than a metronome.
- Both patterns join the M1 session distractor pool (protocol M1: "Boaz / Razu / Buz arc / attention patterns" — the pool now draws 4 distractors from 7), which also strengthens the M3 mark-vs-content confusion check. The prefix card keeps its three content tails — booting and alive-check are lifecycle signals, not message reasons.

## [pre-v0.1.24] — 2026-09-08 — Personal AI: the feel-tool speaks the full interaction language — attention vocabulary, M1 session mode, blind A/B

Docs commit: [docs/haptic-name-marks.html](docs/haptic-name-marks.html) grows from a name-mark player into the whole interaction language, felt on the phone — the attention vocabulary now plays next to the marks, and the page runs its own measurements instead of only demonstrations.

- **Attention vocabulary (plan §4)** — the non-letter patterns as playable cards with beat visuals: double tap = new message arrived (two 70 ms ticks), triple pulse = reminder fired (three even ticks), long buzz = error / attention needed (one 600 ms buzz, deliberately unlike any braille cell). Plus the **name-mark prefix** card: Z-I-V plays first, then the attention pattern says why the device buzzed — three buttons play "+ new message", "+ reminder", "+ error". That is the §4 morning-brief moment, felt end to end: the device says who is talking before it says what.
- **Session mode (protocol M1)** — runs the [NAMING_VALIDATION_PROTOCOL.md](docs/NAMING_VALIDATION_PROTOCOL.md) M1 recognition test on the phone: 8 randomized rounds (4 × the Ziv mark, 4 × distractors drawn without replacement from the Boaz / Razu / Buz arcs and the attention patterns), big Name / Not-name answer buttons, per-round reaction time from end-of-pattern to tap (replays counted and logged, never hidden), no mid-session feedback, and the ≥ 80% working gate scored at the end. Results download as a CSV keyed to the logging sheet (participant label, session id, per-round stimulus / answer / rt / replays / gap).
- **Blind A/B mode** — a random candidate arc plays (Ziv / Boaz / Razu / Buz; an optional checkbox adds the retired-Raz twin, which differs from Ziv only in the middle beat — a = 1 dot vs i = 2), you guess which it was before the reveal; per-arc tallies and a round-by-round guess log separate recognition from preference, measuring which arc is actually recognized, not which one is liked. Log downloads as CSV.
- Protocol materials checklist now points at the new modes as the phone fallback's self-test layer.

## [pre-v0.1.23] — 2026-09-08 — Personal AI: week-6 naming-validation session script

Docs commit: the community-naming step now has a one-page facilitator script —
[docs/NAMING_VALIDATION_PROTOCOL.md](docs/NAMING_VALIDATION_PROTOCOL.md) — covering
how the Z-I-V mark is taught, what is measured, and how braille readers rename
the device if they want to.

- **Teach (braille first, rhythm second):** embossed Z-I-V card read
  conventionally, then the mark played, then a palm-tap per beat, then
  self-paced replays; exposures-to-got-it is logged (working gate: median ≤ 5).
  The mark anchors to a literacy participants already own.
- **Measure (M1–M4):** immediate recognition among distractors (≥ 80%),
  delayed recall across the §7 reading blocks (≥ 70%), zero confusions with the
  attention vocabulary, and an identity read ('someone calling' vs 'a
  message'). M3–M4 answer the plan's §11 question: if a letter-mark reads as
  content, the fallback is a pure-rhythm signature.
- **Rename (the community holds the pen):** keep / change the word / change
  both, preferences captured verbatim, no vote in the room; adoption only on
  cross-session majority convergence and re-passing M1–M4; otherwise Ziv stays
  working title. Includes communication-access prep (SSP/interpreter, braille
  consent forms) and carries the no-clinical-claims rule through debrief and
  follow-ups.
- **Competition section (Devpost draft)** — profiles the five nearest
  products — Neosensory (Buzz/Duo), RAZ Mobility, OrCam MyEye, Dot Inc.
  (Dot Watch / Dot Pad), Hable One — what each ships and the gap that leaves
  a deaf-blind wearer unserved: spoken output (OrCam, RAZ, Hable's screen
  reader), notification mirroring (Dot), or abstract vibration (Neosensory);
  none pairs haptic braille with a hearing, two-way agent. New grounding:
  OrCam pricing $2,450–$4,500 (dealer listings / AFB review); Dot Watch
  first generation discontinued Jun 2018 with a 4-cell display (AFB via
  Dot Inc. news).
- Cross-references: plan §7 (week-6 milestone) and §11 (naming-validation
  question) now link to the script.

## [pre-v0.1.22] — 2026-09-07 — Personal AI: collision sweep retires "Raz" — working title "Ziv", community holds naming authority

Docs commit: a trademark-collision sweep retires the word "Raz"; the
submission ships under the working title Ziv, and the naming principle and
community-authority rule are written into the plan.

- **Collision found** — the word "Raz" collides with RAZ Mobility
  (razmobility.com), an established US assistive-tech company for
  blind/low-vision users: RAZ Memory Cell Phone (sold by Verizon since
  Jul 2025), SmartVision 3, Lucia; founder Robert Felgar, previously founder
  of Odin Mobile, the first wireless carrier for blind users. Identical
  word, same industry, same channels — screening verdict: not safe as a
  product brand.
- **Sweep result (ten names)** — Ziv (cleanest), Boaz (clean), Razu (clean),
  Tov (TOV Furniture holds marks), Raz (critical: RAZ Mobility); later
  probes rejected — Viz (Viz.ai, $1.2B AI-healthcare company with
  FDA-cleared "Viz" products), Buz (Neosensory Buzz: a shipped haptic wrist
  wearable for deaf users — same category, same audience, phonetic twin),
  A2Z (on Amazon's own trademark list, next to the A-to-Z Guarantee;
  generic). Pattern: every sensory-feeling word is claimed inside this
  industry; arbitrary personal names stay clean. Screening only; formal
  USPTO clearance deferred until any commercial step.
- **Naming principle recorded** — the mark is the name; the word is a handle
  chosen by cost (legal cleanliness, sayability for the sighted-hearing
  buyers, braille agreement), not meaning. Z-I-V plays the identical
  heavy-light-heavy mark Raz would have — the wearer's experience is
  unchanged; the word exists for the rest of us.
- **Community naming authority** — name marks are given by communities, not
  self-declared: the submission ships as "Ziv (working title)", and the
  week-6 braille-reader sessions validate the mark and the word — or rename
  the device (replaces the old name-mark open question).
- **Docs updated** — plan doc (§1 naming trail, §4 mark spec Z-I-V, §11
  naming-validation question, §12 pitch, collision sources),
  [DEVPOST_HAPTIC.md](DEVPOST_HAPTIC.md) (working title throughout, naming
  challenge answer rewritten).
- **Mark feel-tool** — [docs/haptic-name-marks.html](docs/haptic-name-marks.html):
  a phone-first page that plays the candidate marks (Ziv, a retired-Raz
  reference, Boaz, Razu, Buz) through the Android Vibration API — each
  braille cell is one beat whose duration encodes its dot weight
  (duration = 50 + 60 × dot count), with a gap slider, loop toggle,
  play-all sequence, and a visual-cell fallback where vibration is
  unsupported (iOS/desktop).

## [pre-v0.1.21] — 2026-09-07 — Personal AI: named Raz + plan refinements + Devpost draft

Docs commit: the haptic companion gets its name, the project brief's refinements are folded into the plan, and the Devpost draft exists.

- **Named: Raz** — "Tact" withdrawn (too literal, and it named the feature from the sighted-hearing perspective). The word comes from the founder's own name; the name the wearer owns is the **haptic name mark** — R-A-Z spelled in vibro-braille (heavy-light-heavy, ends decisive), played at boot and as the prefix of every unsolicited message. Grounded in how Deaf/DeafBlind communities identify people by tactile name signs (sources added to the plan).
- **Plan refinements** — [docs/HAPTIC_COMPANION_PLAN.md](docs/HAPTIC_COMPANION_PLAN.md): the four demo-shaped user flows (morning brief, conversation, ambient check on demand, agent task); challenge→exercise→fallback ladders for six named challenges (incl. the 30-phrase fixed-vocabulary fallback if long-form temporal braille doesn't teach — learnability de-risking explicitly gated on the founder's call); §12 founder pitch; open questions for name-mark validation and target-population braille literacy.
- **Devpost draft** — [DEVPOST_HAPTIC.md](DEVPOST_HAPTIC.md) mirrors DEVPOST.md's format for the Personal AI track, with *(planned)* build-status markers and the no-clinical-claims rule carried over.

## [pre-v0.1.20] — 2026-09-07 — Personal AI direction: haptic AI companion for deaf-blind users

Docs commit: the second-submission direction is chosen and planned.

- **Decision recorded** — the Personal AI track entry is a **haptic AI
  companion for deaf-blind users**: an ESP32-S3 N16R8 wearable with 6
  vibromotors (DRV2605L, one per braille dot) + a 6-key braille chord
  keyboard + a push-to-talk mic. Nemotron-3-Nano-Omni (now on Nebius Token
  Factory, audio input natively) hears for the wearer; vibro-braille on the
  wrist speaks to them. ~$37–46 BOM against a $1,500–$12,000 device class.
- **Concept + MVP plan** — [docs/HAPTIC_COMPANION_PLAN.md](docs/HAPTIC_COMPANION_PLAN.md)
  (incl. a fine-tuning assessment from the Token Factory post-training
  catalog — Qwen3-0.6B/1.7B/4B as the v2 braille-style distillation lever,
  Nemotron stays served-not-tuned):
  problem brief (price-gap table, population figures), interaction design v0
  (haptic attention vocabulary + temporal vibro-braille, Grade 1),
  architecture (firmware modules → thin self-hosted relay → Token Factory
  model routing), Assemble/Secure/Run mapping, 8-week milestones with a
  week-1 spike gate (mic clip → Omni → vibro-braille end-to-end), demo
  script, risks, and open questions.
- **Why the pivot beats the general pin** — removing the speaker removes
  AEC, wake word, and the TTS pipeline (the old Route C's hard problems);
  Omni's native audio input removes the separate STT service; the haptic
  channel is the privacy story ("private by physics").
- **Cross-references** — CAPABILITIES.md §6 and MIMICLAW_PIPIN_RESEARCH.md
  §7 now point to the plan; the research note's "submit B" recommendation is
  marked superseded with its carry-overs named.

## [pre-v0.1.19] — 2026-09-04 — grounding disclosure + opt-out in the UI

Feature commit: `0957156` (surface registry grounding per compose and let
users opt out of the tools).

- **Grounding disclosure** — the compose-timing strip under the task bar now
  reports how grounded each live compose was: `🔧 verified via N registry
  lookups` when the decompose agent used the tools, `prompt-based — no
  registry lookups` when it answered from the prompt (count comes from the
  done event and is persisted on history entries, so reopening a pipeline
  keeps the disclosure).
- **Grounding toggle in the compose box** (live mode) — default ON follows
  the measured auto-policy (fresh composes verify via registry tools, seeded
  variations stay prompt-only); OFF sends `tools_enabled: false` on the
  wire so every compose runs prompt-only and fast (~30s vs ~60-100s).
- **API** — `TaskRequest.tools_enabled` (None = auto, False = prompt-only,
  True = force grounding) threads through `/api/compose`, `/api/compose/silent`,
  and the SSE stream to the agent.
- **Tests** — hermetic 84 → **86** (opt-out reaches the agent: `tool_calls`
  0 on compose and stream, no tool lines; default keeps the fake's two
  lookups); browser E2E 9 → **10** — `test_grounding_e2e` stubs the stream
  with `tool_calls: 4` then 0: the verified line renders, the toggle flip
  renders the prompt-based line, and the wire bodies prove the grounded
  default omits `tools_enabled` while the opt-out sends `false`.

## [pre-v0.1.18] — 2026-09-04 — measured tool policy for compose

Feature commits: `82a5e9e` (tool prompt tuning) + `c60924f` (seed-aware tool
default) — registry tool use measured live and scoped to where it pays.

- **Live A/B on seeded form-factor crossings** — 12 real seeded G1→Go2
  variations (perception-flavored patrol and a sharp manipulation-flavored
  push task): the capability gate rejected **0/12 with or without tools**,
  and the model swapped the seed's arm skill (`motion-generation`) for the
  quadruped-class `legged-manipulation` in every run. The old 1/3
  copy-rate is gone — the quadruped catalog + variation rules matured — so
  tools add no measured gate benefit on the seeded path.
- **Tuning** — grounded composes cost ~3× latency (54–78s vs 21–27s)
  because the model re-read catalog rows already in its system prompt, one
  `get_skill` round at a time (21 calls on a fresh compose). The model
  cannot emit parallel tool calls on this endpoint (probed), so the rules
  now forbid re-reading the catalog and limit calls to
  `check_capability` on doubtful anatomy only. Fresh unseeded compose
  dropped **21 → 2 calls** with the same valid result.
- **Seed-aware default** — `decompose_task` auto-selects the path: fresh
  decomposes keep the tools (grounding is real there); seeded variations
  run prompt-only and stay fast. Verified live: seeded Go2 push variation
  composes in ~36s with `tool_calls: 0`, still swapping correctly.
  `tools_enabled` forces either path for future A/B.
- **Tests** — hermetic suite 83 → **84**: seeded decomposes send no tool
  schemas by default while fresh decomposes keep them.

## [pre-v0.1.17] — 2026-09-04 — registry tool use in compose

Feature commit: `9c0473e` (the decompose agent queries skill/robot registries
as structured tools, grounding plans in registry data).

- **Registry tools** — the compose round-trip now offers the agent four
  structured tools backed by the exact registries the capability gate
  validates against: `list_skills` (compact rows), `get_skill`, `get_robot`,
  and `check_capability` (does this skill's required anatomy exist on this
  robot?). Tool calls execute in a bounded loop (max 12 rounds, escaped via
  a hard cap) and results feed back as tool messages before the final JSON.
- **Grounding instead of memory** — the model can verify costs, GPU needs,
  and anatomy mid-decomposition rather than trusting the catalog text baked
  into the prompt. The catalog stays in the prompt as a safety net, so
  providers that reject tool definitions (HTTP 400/404/422) degrade to the
  prompt-only path instead of failing the compose.
- **Observability** — every registry lookup surfaces in the reasoning stream
  as a `🔧 queried …` line, and every compose response (stream done event,
  `/api/compose`, `/api/compose/silent`) reports its `tool_calls` count.
  `live_check journey` hard-checks the field and prints how grounded the
  compose was.
- **Resilience fixes found live** — tool round-trips inflate the context the
  model must answer over; output budget raised 2000 → 4000 tokens (empty
  content + `finish=length` after a large tool payload) and `list_skills`
  returns compact rows so the round-trip stays lean.
- **Tests** — hermetic suite 77 → **83**: executor grounded in the
  registries (go2 × motion-generation → incompatible), the tool loop feeds
  results back and reports every call, a provider rejecting tools degrades
  cleanly, the loop is bounded, the default budget covers a 9-round
  verification-heavy plan, and the stream surfaces tool lines + the done
  event's `tool_calls`.

## [pre-v0.1.16] — 2026-09-04 — dry-run verdicts on history cards

Feature commit: `2098369` (persist the last simulation dry-run verdict so a
reopened pipeline shows its test result without re-running).

- **Dry-run verdict persistence** — every completed simulation dry-run is
  recorded onto the history entry being displayed (scenario seed, compressed
  elapsed time, per-step pass/fail verdicts). History cards gain a badge:
  `🧪 pass · 14s · 0x0007` (green) or `🧪 fail · …` (red), with a tooltip
  naming the pass count and seed.
- **Instant restore on reopen** — reopening a pipeline and running sim
  dry-run renders the stored verdict immediately ("last run · completed in
  14s …") with the same seed chip, instead of replaying the ~14s run. The
  stored view is only honored while it matches the current plan: if steps
  were edited after the run, the stale record is discarded and the panel
  auto-replays live, so a verdict can never be shown for a different plan.
- **Tests** — browser E2E (9 total): the new dry-run persistence test
  asserts the card badge appears after a run, reopening renders the stored
  verdict within 3s with the "last run" framing and the same seed, and
  replaying from the stored state reproduces the identical summary.

## [pre-v0.1.15] — 2026-09-04 — simulation dry-run panel

Feature commit: `6b21fa4` (replay a pipeline step-by-step with simulated
pass/fail against skill metadata).

### Added
- **Simulation dry-run** — the results view gains a "▶ sim dry-run" action
  next to edit/variation that replays the composed pipeline step-by-step
  with real wall-clock pacing and per-step verdicts derived from skill
  metadata. Structural checks (robot anatomy vs skill requirements; step
  ordering — validation or deployment before any training step, data
  generated after training already started, deployment not last) fail
  deterministically; every remaining step carries a small seeded execution
  risk (training can diverge, validation can fall short). Same plan + same
  seed = same outcome; "🎲 new scenario" rerolls the execution risk.
- **Honest framing** — the panel header states it is a metadata replay, not
  Isaac Sim; a preflight scan announces structural issues before the replay
  starts; the run halts at the first failing step and only executed steps
  charge cost; the seed chip makes results reproducible.
- **Replay controls** — pause/resume freezes the real clock mid-step, replay
  re-runs the identical scenario, and closing/reopening rolls a fresh seed.
- **Tests** — new browser E2E composes a mock pipeline, asserts the replay
  completes with verdict chips, pause freezes the elapsed clock, a same-seed
  replay reproduces the identical summary, and an edit that moves
  policy-validation ahead of every training step halts the replay at step 1
  with the structural reason. Suite counts: 77 hermetic, 8 browser E2E.

## [pre-v0.1.14] — 2026-09-04 — compose time on history cards

Feature commit: `bd6db86` (surface compose wall time on live history cards).

### Added
- **Live history entries keep their compose stats** — the history snapshot
  for every live compose (fresh or seeded variation) persists its wall time,
  retry count, and per-phase breakdown alongside the pipeline, so the info
  survives reloads and Redis refreshes.
- **Cards show it** — the meta row of a live card gains "⏱ 11s · retried
  1×" (warn-colored when the compose healed retries, with a full tooltip);
  mock cards and older entries without stats show nothing extra.
- **Reopen restores the disclosure** — "open in editor" on a live card now
  restores the compose-timing line under the task bar (total + per-phase
  breakdown, with the retry disclosure), so a user returning to a slow
  pipeline still sees how long its compose took — previously the strip only
  appeared for fresh composes.
- **Tests** — the retry-note browser E2E now asserts the newest card's badge
  reads "11s" with the right retry count (1× then 3×) and that reopening the
  card re-renders the full timing line. Suite counts unchanged: 77 hermetic,
  7 browser E2E.

## [pre-v0.1.13] — 2026-09-04 — compose telemetry on /api/health

Feature commit: `f678071` (expose rolling compose latency/retry telemetry
on /api/health).

### Added
- **Rolling compose telemetry ring** — every finished compose
  (`/api/compose`, `/api/compose/silent`, `/api/compose/stream`) appends its
  wall time and healed-retry count to a thread-safe in-process ring of the
  last 20, so ops can see live-mode health without standing up external
  metrics.
- **`compose_stats` on /api/health** — `samples`, `avg_seconds`, `p95_seconds`,
  `avg_retries`, `retried_composes`, and the tail of the ring (last 10
  entries with endpoint / seconds / retries / timestamp); `{samples: 0}`
  before the first compose of a process.
- **`live_check journey` prints it** — the health section now shows
  `compose_stats: samples / avg / p95 / retried` from the running server.
- **Tests** — 3 new hermetic tests: health reports sane aggregates + the
  stream entry after a real (fake-agent) compose; a retried stream compose
  shows up with `retries: 1`; and the ring stays capped at 20 entries.
  Suite counts: 77 hermetic, 7 browser E2E.

## [pre-v0.1.12] — 2026-09-04 — slow-compose warning

Feature commit: `60f1904` (warn when a compose beats the session's moving
time baseline).

### Added
- **Moving-baseline slow detector** — live compose wall times accumulate per
  tab session (`sf-session-compose-times`, capped at 6); once two composes
  have established a baseline, any compose that clears a 12s floor and is
  2×+ the session's recent **median** triggers a warn note: "compose took
  60s — 4.6× slower than your recent typical (13s). retry, or simplify the
  task." Because the baseline is the session's own median, the threshold
  adapts to how long composes normally take here instead of a fixed
  constant.
- **Mirrors the frequent-blip hint** — same amber strip styling and
  placement (beside the compose-mode switch in the input view and in the
  results view), cleared by the next normal compose and by switching to
  mock mode. Unaffected by (and complementary to) the per-compose timing
  strip and the auto-retry disclosures.
- **Tests** — seventh browser E2E: seeds a two-compose session baseline
  (12s/14s), reloads same-tab, intercepts the compose stream with a 60s
  done event and asserts the note reads "4.6× slower than your recent
  typical (13s)", then a normal (10s) compose clears it and the session
  history records both runs. Suite counts: 74 hermetic, 7 browser E2E.

## [pre-v0.1.11] — 2026-09-04 — per-phase compose timing

Feature commit: `62f8c9c` (break compose timing into decompose/explain/logs
phases).

### Added
- **Per-phase wall times on the done event** — the SSE compose stream times
  each round-trip group separately and the `done` event carries
  `phases: {decompose, explain, logs}` (seconds, each including its own
  retry backoff; `logs` is the simulated execution stream). The whole-run
  `seconds` total is unchanged.
- **Breakdown in the results view** — the compose-timing strip now shows a
  second, fainter line under the total: "decompose 19s · explain 5s · logs
  7s" — users see that the model round-trips (not the UI) dominate instead
  of one opaque number.
- **Tests** — the clean and retried compose-stream hermetic tests assert the
  done event's `phases` dict names exactly the three keys with `logs > 0`
  (the simulated stream always takes real time); the retry-note browser E2E
  stub now carries phases and asserts the breakdown line renders for both
  the retries=1 and retries=3 composes. Suite counts unchanged: 74 hermetic,
  6 browser E2E.

## [pre-v0.1.10] — 2026-09-04 — retry counts on request/response endpoints

Feature commit: `72804ed` (report auto-retry counts on
compose/silent/improve responses).

### Added
- **`retries` on non-stream responses** — `/api/compose` (summed across its
  decompose + explain round-trips), `/api/compose/silent`, and
  `/api/improve` now carry `retries` in their JSON (0 on clean calls), so
  request/response API clients see healed LLM blips the same way the SSE
  stream's `done` event reports them — previously the count existed only on
  the streaming path the UI uses.
- **`live_check` reports it** — the journey command checks that compose
  responses carry the count and prints "auto-retried N× during this compose
  (healed on its own)" when N > 0; the share-links bonus compose prints the
  same note.
- **Tests** — 4 new hermetic tests: clean compose / compose-silent / improve
  all report `retries: 0`, compose sums retries across both round-trips,
  silent reports multi-retry decomposes, and improve reports healed
  suggestion round-trips. Suite counts: 74 hermetic, 6 browser E2E.

## [pre-v0.1.9] — 2026-09-04 — live compose latency visibility

Feature commit: `4f27a0f` (show compose wall time so slow LLM calls read as
slow, not stuck).

### Added
- **Compose wall time on the wire** — the SSE compose stream times the whole
  run (LLM round-trips + retry backoff + streaming) and the `done` event now
  carries `seconds` and `retries`, so API clients and the UI both learn how
  long a compose actually took.
- **Ticking elapsed while processing** — a live compose shows "⏱ compose
  running — Ns elapsed" under the task bar, ticking each second, so a slow
  LLM round-trip reads as slow instead of stuck (mock composes keep their
  animated progress and show nothing).
- **"compose took Xs" results line** — when the compose completes, the line
  becomes "⚡ compose took 23s", or "↻ compose took 23s (auto-retried 1×,
  healed on its own)" in the warn palette when round-trips had to be
  retried — folding the pre-v0.1.4 standalone auto-retry note into one
  latency + retry disclosure. Clean live composes and mock composes show
  nothing extra.
- **Tests** — the clean and retried compose-stream tests now assert the
  `done` event reports `seconds > 0` and the correct `retries` (0 clean / 1
  after a healed retry). Suite counts unchanged: 70 hermetic, 5 browser E2E.

## [pre-v0.1.8] — 2026-09-04 — session auto-retry awareness

Feature commit: `7a888d3` (warn when live composes auto-retry often in a
session).

### Added
- **Session auto-retry tally** — every healed retry a live compose reports is
  accumulated for the tab session (`sf-session-retries` in sessionStorage, so
  the count survives reloads), instead of each compose being treated as an
  isolated event.
- **Frequent-blip hint** — once the model has auto-retried 3+ times in the
  session, the UI shows a nudge — "model auto-retried N times this session —
  if it keeps blipping, try mock mode or a simpler task" — beside the
  compose-mode switch in the input view and in the processing/results view
  (only when that section is on screen). Switching to mock mode clears the
  tally, since that is the suggestion being taken.
- **Tests** — fifth browser E2E: seeds the sessionStorage tally, reloads in
  the same tab, and asserts the hint stays hidden in mock mode, appears on
  switching to live, and clears (with the storage) when mock is chosen
  again — no compose, backend, or credits needed. Suite counts:
  70 hermetic, 5 browser E2E.

## [pre-v0.1.7] — 2026-09-04 — visible adaptation reasoning

Feature commit: `a1c6339` (explain per-step adaptation on seeded variation
results).

### Added
- **"🧬 adaptation — how this plan changed" card** — whenever a variation
  lands (fresh compose, reopen from history, or share-link restore), the
  results view now shows why each step of the new plan differs from the
  seed: variation steps are tagged **still applies** (carried over
  unchanged), **kept + reworded** (adapted for the new task), or **new**
  (added for the new task/robot), matched to the original by skill id; and
  every original step that didn't survive is listed with the reason — the
  new robot's anatomy ("Unitree R1 has no arm, and policy-training-gr00t
  needs it to work") or the reworded task dropping it.
- **Deterministic, LLM-free diff** — `diffAdaptation` compares the seed and
  the result purely client-side (no extra credits), mirroring the backend
  robot/skill anatomy tables so drops are explained even offline in mock
  mode. The report is persisted with the history entry, so reopening a
  variation later shows the notes again.
- **Tests** — the variation browser E2E now switches robot G1 → R1 (the
  armless compact) and asserts the card explains the arm-skill drops with
  the anatomy reason, marks the locomotion step as new, and words the kept
  steps as still applying. Suite counts: 70 hermetic, 4 browser E2E.

## [pre-v0.1.6] — 2026-09-04 — quadruped-class skills

Feature commit: `9cc9303` (add quadruped-class skills).

### Added
- **`legged-manipulation`** (Isaac Lab / Isaac Sim, ~$1.20) — push, carry,
  and reposition objects with the body and legs; no arm required
  (requires legs + cameras).
- **`terrain-adaptation`** (SONIC / Isaac Lab, ~$1.00) — gaits and recovery
  that adapt to rough, slippery, or uneven ground (requires legs).
- Both skills carry anatomy tags, so they pass the capability gate for
  Go2-class and other legs-only robots (which previously had no way to
  interact with objects or plan for rough ground), and the catalog grows to
  11 skills — surfaced automatically in the skill browser and the LLM
  prompt. `get_skills_for_task_type` mappings updated to match.
- **Plain-words coverage** — everyday sentences for both ids, plus keyword
  rules ordered so body-level "push / carry / legged" phrasing beats the
  generic arm-handling rule and terrain/rough-slip phrasing beats the
  locomotion catch-all (with a word-boundary so "through" can't trigger
  "rough").
- **Tests** — catalog-list test now asserts 11 skills incl. both new ids;
  gate tests prove the new skills are legal for go2/r1 and that legged
  manipulation still needs legs. Suite counts: 70 hermetic, 4 browser E2E.

## [pre-v0.1.5] — 2026-09-04 — robot capability gate

Feature commit: `3253805` (gate every compose against the robot's anatomy).

### Added
- **Skills declare the anatomy they need** — every catalog skill now carries
  `requires` (arm / legs / cameras); scene creation, data synthesis,
  validation, and packaging work for any body, while GR00T and motion
  planning require an arm, SONIC requires legs, and perception / world
  models require cameras.
- **Robot registry** — `robot_registry.py` profiles the robots the API
  accepts (`unitree-g1` bipedal humanoid, `unitree-r1` compact legged,
  `1x-neo` humanoid, `unitree-go2` quadruped) with their anatomy. Robot
  strings are no longer free-form.
- **Compose gate** — every LLM-composed pipeline (fresh or a seeded
  variation) is validated against the *requested* robot before it is
  stored: a plan that asks an armless robot to train arm skills is
  rejected with a clear 422 naming the offending steps, instead of the
  model's output being trusted. Unregistered robot slugs fail before any
  LLM call. The SSE stream surfaces rejections as an error event; nothing
  incompatible is ever stored.
- **Tests** — 12 new hermetic tests: registry consistency, mock-pipeline
  compatibility, arm/legs/camera requirement logic, unknown-robot
  messaging, and API-level 422s on compose/silent plus the SSE error
  event. Suite counts: 68 hermetic, 4 browser E2E.

### Fixed
- `test_compose.py`'s stream-variation test targeted `unitree-r1` with an
  arm-skill seed — now correctly a humanoid (`1x-neo`) under the gate.

## [pre-v0.1.4] — 2026-09-04 — visible auto-retry

Feature commit: `b0b7e5a` (surface auto-retried live composes in the UI).

### Added
- **Auto-retry is now visible** — when a live compose has to retry a
  transient LLM blip, the UI shows a small note under the task bar
  ("↻ model hiccup — auto-retried once / N times, compose healed on its
own"), so a slow-but-recovered call is no longer indistinguishable from
  a hang. Mock composes and clean live composes show nothing.
- **Agent reports healed retries** — the LLM methods accept an optional
  `on_retry(attempt, error)` callback invoked after each failed attempt
  that is retried; the SSE compose stream counts these across decompose
  and explanation and emits a `notice` event before `done`.
- **Tests** — 5 new hermetic tests: on_retry fires per healed attempt with
  1-based numbering, stays silent on clean calls and on calls that fail
  for good, and the stream emits a `notice` event (retries=1) after a
  stubbed failure while clean streams carry none. Suite counts:
  56 hermetic, 4 browser E2E.

## [pre-v0.1.3] — 2026-09-04 — resilient live composes

Fix commit: `3a49325` (fix: retry LLM round-trips so flaky live composes
can't hard-fail).

### Fixed
- **Bounded retry on every LLM round-trip** — a shared retry helper now runs
  decompose, seeded-variation, and explain prompts up to 3 attempts with
  backoff, rejecting empty/`null` content and retrying malformed (incl.
  fenced) JSON. Discovered live: the seeded-variation path 500'd with
  `'NoneType' object has no attribute 'strip'` when Nemotron returned empty
  content; with no retry, one flaky response was a hard, cryptic failure.
  A meaningful error is raised only after all attempts fail.
- **Tests** — 6 new hermetic unit tests with a stubbed OpenAI client (no
  API key or network): retry after empty responses and truncated/fenced
  JSON, give-up after max attempts, seed preserved across retries, and
  explain retries on empty content. Suite counts: 51 hermetic,
  4 browser E2E.

## [pre-v0.1.2] — 2026-09-03 — seeded variations

Feature commit: `cede1d9` (feat: compose seeded pipeline variations).

### Added
- **Create variation flow** — a "🧬 create variation" action on the pipeline
  header opens a composer prefilled with the displayed plan's task and robot;
  rewording the task or switching robots composes a NEW pipeline. Each
  variation lands as its own history entry; the original stays available.
- **Seeded compose (backend)** — optional `seed_pipeline` field on
  `/api/compose`, `/api/compose/silent`, and `/api/compose/stream`; the agent
  prompt now produces a VARIATION, keeping steps/skills that still apply and
  adapting or dropping the rest for the new task/robot.
- **Tests** — 3 hermetic tests for seed propagation (compose + stream),
  plus a browser E2E for the mock variation flow. Suite counts: 45 hermetic,
  4 browser E2E.

## [pre-v0.1.1] — 2026-09-03 — iterable pipelines

Feature commit: `cb3dbc8` (Make composed pipelines iterable).

### Added
- **Persisted pipeline history** — composed pipelines survive reloads:
  localStorage snapshots for mock pipelines (the only record of them), Redis
  pipeline ids for live ones; entries deduped by id and capped at 30
  (`sf-history-v1`).
- **"↪ open in editor" on history cards** — restores the full results view
  (task, robot, summary, timeline, export) and the `#p=` URL hash. Live
  entries refresh from the store on reopen, falling back to the stored
  snapshot when the 7-day TTL has expired.
- **Robust LLM-free re-export after reopen** — exports treat the inline
  pipeline as authoritative when no valid server id exists, so stale ids
  can't make the backend re-export the wrong original.
- **History provenance badges** on cards (`live · p…` vs `mock · local`).
- Third browser E2E test: persist → reopen → edit → re-export.

### Changed
- `HistoryItem` gains `kind: "mock" | "live"` and an optional `pipelineId`.
- README: history feature bullet and E2E test count updated (3 E2E tests).

## [pre-v0.1.0] — 2026-09-03 — initial baseline

Root commit: `4da586d`. The first committed state of the whole project.

### Added
- **Compose** — plain-English task → costed NVIDIA skill pipeline, via mock
  mode (no backend) or the live Nebius LLM API (SSE stream: thinking →
  pipeline → explanation), with a mock/live switch in the compose box.
- **Share links** — pipelines stored by id (Upstash Redis when configured,
  local file fallback); `/#p=<id>` restores any pipeline client-side.
  Cross-instance share-link E2E + rate limiting on link resolution.
- **ROS2 export + validation** — buildable packages (package.xml, CMakeLists,
  launch files) exported server-side or client-side, validated with
  structural checks (100/100 scorer).
- **Human-editable pipeline view** — reorder/swap/remove steps and re-export
  LLM-free.
- **Plain-words layer** — "what this plan does" summary card + glossary
  tooltips so results read clearly to non-robotics users; layered fallback
  rewrites arbitrary step names.
- **Design system** — token-based dark/light themes (OS-following default +
  manual toggle), WCAG-contrast-audited light palette.
- **Ops surface** — `/api/health` reports store backend (redis/memory), entry
  count, Redis connectivity; `live_check.py` CLI consolidates the live
  verification scripts (share-links / journey / edit).
- **Tests** — 42 hermetic pytest tests + 2 browser E2E tests at this tag.

### Notes
- Working title "SkillForge" — rename decision deferred until the public
  repo / 0.1.0 (tracked in `docs/ROADMAP.md`).
