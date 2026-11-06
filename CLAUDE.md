# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Ziv is a haptic message channel for deaf-blind wearers: a FastAPI relay (`agent/ziv_server.py`) pushes turn events over WebSocket to a phone PWA (`agent/ziv_client/index.html`) that plays them as vibro-braille via the Vibration API. The same timing numbers also drive the (not-yet-flashed) ESP32-S3 firmware in `firmware/`. The README's "What is built / what is next" table draws a hard line between what is **built and proven** and what is **next**. Do not move a claim across that line in docs without the matching code/test, and make no clinical or efficacy claims anywhere.

## Commands

Python 3.10+ (CI uses 3.12). Deps live in `agent/requirements.txt`; `pytest` and `playwright` come from `agent/requirements-dev.txt`. A venv at `agent/venv/` is what the hooks and scripts look for first (it may carry the `ziglang` pip package as the C compiler).

```bash
# run the relay (port 8787; PWA at http://127.0.0.1:8787/ziv_client/index.html)
cd agent && python ziv_server.py          # no key needed; without NEBIUS_API_KEY the model path is text_echo

# hermetic suite (browser e2e deselected by pytest.ini addopts)
cd agent && python -m pytest -q
cd agent && python -m pytest -q tests/test_ziv_server.py                  # one module
cd agent && python -m pytest -q tests/test_ziv_store.py::test_name        # one test

# browser tier (Playwright + a system Chrome/Edge; in-process uvicorn; ~75 s)
cd agent && python -m pytest -m e2e

# timing drift guard: spec vs all 7 generated consumers (exit 1 on drift)
python tools/haptic_timing.py
python tools/haptic_timing.py --write     # regenerate consumers after editing docs/haptic-timing.json

# firmware (host C compiler required: cc/gcc/clang/tcc, zig cc, or `pip install ziglang`; exit 2 = no compiler)
python firmware/haptic_out/run_tests.py           # bench suite, mock DRV2605L
python firmware/app/ziv_qemu/run_ziv_tests.py     # rung-1 host demo + HAP fixture diff (not a QEMU boot)

# PWA service-worker cache guard
python scripts/ziv_client_cache.py --check        # fails if the client shell changed without a cache bump
python scripts/ziv_client_cache.py --bump         # vN -> vN+1 in ziv_sw.js + record fingerprint

# relay hand-over gate: refuses a relay whose schedule loop cannot fire a reminder
bash scripts/relay_preflight.sh                   # ZIV_RELAY=<origin> for a hosted relay

# install the pre-commit hook once per clone (timing verify + bench + staged cache check)
git config core.hooksPath hooks
```

CI (`.github/workflows/ci.yml`) runs: cache `--check`, the hermetic suite with `-m "not e2e"`, `tools/haptic_timing.py`, and `run_ziv_tests.py`. The `qemu-boot` job is informational (`continue-on-error`) until an ESP-IDF install step is filled in.

Test harness notes: `agent/tests/conftest.py` puts both `agent/` and `tools/` on `sys.path`, so pytest works from `agent/` or the repo root, and tests import runtime modules by bare name (`ziv_relay`, `ziv_server`, `haptic_timing_gen`). Every test runs under a `faulthandler` watchdog (default 90 s, `ZIV_TEST_TIMEOUT_S` or `@pytest.mark.timeout(n)`); a hang writes `agent/tests/pytest-hang.txt` and exits non-zero.

## Architecture

This section describes the tree as it is. The target shape, and the order of work to reach it, is `docs/ARCHITECTURE.md`; new work should move toward it rather than extend the current server-paced design.

**Three layers share one generated timing source.**

- `docs/haptic-timing.json` is the only hand-edited home for every buzz/gap constant, the Grade-1 letter dot table, the 7 attention/lifecycle patterns, the 5 candidate name marks, and the prefix composition.
- `tools/haptic_timing.py` generates and verifies 7 consumers: the JS block in `docs/haptic-name-marks.html` (the feel-tool), `firmware/haptic_out/haptic_timing.h`, `tools/haptic_timing_gen.py` (Python module used by the relay and tests), the tables in `docs/HAPTIC_TIMING_SPEC.md`, `firmware/app/ziv_qemu/main/ziv_demo_sequence.{h,c}` (via `tools/build_ziv_demo.py`'s `DEMO_STAGES`), and the demo-chain block in `docs/QEMU_SIMULATION_LADDER.md`. Generated regions are fenced with `haptic-timing:begin/end` markers.
- **Never hand-edit a generated consumer.** Edit the JSON (or `DEMO_STAGES`), run `--write`, commit JSON + regenerated files together. The hook, the hermetic suite (`agent/tests/test_haptic_timing.py`) and CI all fail on drift.
- `agent/haptic_timing_gen.py` is a tracked copy identical to `tools/haptic_timing_gen.py`; the server's `sys.path` puts `tools/` first, and only the `tools/` copy is drift-guarded. Treat the `agent/` copy as generated too.
- Intentional asymmetry: the feel-tool spell box caps at 12 letters (`spell_max_letters`, page affordance) while firmware accepts 16 (`HAPTIC_OUT_MAX_WORD_LEN`, runtime ceiling). Do not unify them; the guard checks both.

**Relay (`agent/`).**

- `ziv_relay.py` is the stdlib-only seam: `MessageGate` (queue-don't-interrupt; bounded at `MAX_QUEUED`=8, overflow is a visible `message:rejected`/HTTP 429, never a silent drop; thread-safe), `TurnTimeline` (every turn: kind cue → `processing` ticks → braille cells → `end-of-message` close → release → drain queued replays), lifecycle pattern constants, `TelemetryRing`. `ZivRelayAdapter` is a labelled placeholder, not what the server calls.
- `ziv_server.py` owns transport and HTTP: `/ws` (one JSON frame per wearer-visible event, `{"type":"haptic","pattern":...,"ms":[...]}`), `/api/ziv/message`, `/api/ziv/compose`, `/api/ziv/schedule` (+ a background `schedule_loop`), `/inject/audio` (held as asset, 503 unless configured), `/api/ziv/inbox|prefs|timing|health|ready|model/check|control/*`, and the static PWA routes. `?session=<id>` on `/ws` and `session` in bodies give each band its own `RelaySession` (hub, gate, turn lock) via `SessionRegistry`. The turn runs through `run_message_turn`; `free: true` rides the last close so a redial never fires into a draining message.
- Auth: setting `ZIV_RELAY_TOKEN` requires `?token=` on WS and `Authorization: Bearer` on content routes via the single `AUTHENTICATED` dependency list. New content-carrying routes must use it; `/api/ziv/timing`, `/api/ziv/health` and the client page stay open by design.
- Model path: `compose_reminder_line` → `compose_with_nebius` (OpenAI-compatible client against Nebius Token Factory, Nemotron, `enable_thinking: false`). Without `NEBIUS_API_KEY` the intent fires verbatim and the wire says `source: text_echo`; with a key, `text_live`. Failures are loud and labelled, never silently substituted. `/api/ziv/compose` is the bring-your-own-key (BYOK) variant: the key in `X-Nebius-Key` is used once, never stored or logged, and scrubbed from errors.
- `ziv_store.py`: `WearerMemory`, `MessageInbox` (cap 20), `ScheduledReminders` (cap 64), one atomic JSON file per key under gitignored `agent/ziv_data/`. Corrupt files are discarded and surfaced through `take_corrupt_files()` into `/api/ziv/health`; cap evictions are logged and counted, never silent.
- Config comes from `agent/.env` (see `.env.example`): `ZIV_PORT`, `ZIV_FAKE_MODEL_SECONDS`, `ZIV_RELAY_TOKEN`, `NEBIUS_*`, `ZIV_TEXT_MODEL`, `ZIV_OMNI_MODEL`. Everything has a default; the server runs with nothing set.

**Client (`agent/ziv_client/`).** One self-contained `index.html` (band screens + operator console in one page, inline script), `ziv_sw.js` (cache-first shell, `const CACHE = "ziv-phone-band-vN"`), `ziv_manifest.json` (served as `manifest.json`). Several hermetic tests (`test_client_*_contract.py`) parse the client's inline JS as text and pin wire contracts against the server (health keys the badge reads, redial, busy-sheet, no dead controls). Renaming a health key or a client function will fail those tests on purpose; update both sides. **Any change to a file in the SW `SHELL` list needs `scripts/ziv_client_cache.py --bump` and the bumped `ziv_sw.js` + `scripts/ziv_client_shell_cache.json` staged in the same commit**, or installed PWAs keep the old page forever.

**Firmware (`firmware/`).** `haptic_out/` is a host-portable C11 sequencer (pull model: `haptic_out_step(now_ms)` returns the next deadline; RTP mode on one DRV2605L per dot behind a TCA9548A mux) with a mock bus for the bench; the ESP-IDF I2C bus and FreeRTOS task are sketches. `app/ziv_qemu/` is the ESP-IDF boot app whose core (`ziv_app.c`) runs on the host and emits `HAP <at_ms> START|BUZZ|END ...` lines asserted against the derived 27-line fixture; `tools/qemu_timeline.py` diffs HAP logs (also used by the drift guard in self-check mode). Builds use `-Wall -Wextra -Werror -std=c11`. The simulation ladder (rungs 0–4, H) is in `docs/QEMU_SIMULATION_LADDER.md`.

**Feel-tool (`docs/haptic-name-marks.html`).** Offline page, no relay; the hosted copy is deployed from `sites/feel-tool/` by copying it to `sites/feel-tool/public/index.html` (see `sites/feel-tool/SITE.md`). `tools/m1_summary.py` and `tools/rename_check.py` implement the naming protocol gates from `docs/NAMING_VALIDATION_PROTOCOL.md`; "Ziv" is a working title.

## Conventions

- Conventional Commits, scopes `server|client|firmware|tools|docs|infra`; subject ≤ ~72 chars, imperative; body says why. One logical change per commit. Details in `CONTRIBUTING.md`.
- Behavior changes get a `CHANGELOG.md` entry under `[Unreleased]`; README/CHANGELOG test counts must match a real run (the repo treats stale counts as a documentation bug).
- Design principles that recur in code review here: bounded memory everywhere (every queue/inbox/schedule has a cap, every drop is logged and counted); no silent fallback (a missing key or failed model call is labelled on the wire, not papered over); the channel is serial, so nothing may cut into a playing turn.
- The `main` branch still carries the hackathon-era material (Devpost drafts, judge repro, demo-VM deploy scripts, recording scripts). The `product` branch is the product-only direction; do not reintroduce that material there.
- `CHANGELOG.md` is history and keeps its old wording (track prefixes, SkillForge-era entries); only `[Unreleased]` is edited.
