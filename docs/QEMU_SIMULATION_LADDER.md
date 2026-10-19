# QEMU simulation ladder — the real binary, no board

**Purpose:** boot and exercise the *actual Ziv firmware binary* on the host inside
Espressif's QEMU fork (ESP32-S3 support: CPU, memory, flash, several peripherals —
[ESP-IDF guide](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-guides/tools/qemu.html)),
with every peripheral QEMU cannot emulate replaced by a seam backend. Complements
[HARDWARE_BRINGUP.md](./HARDWARE_BRINGUP.md): that doc is the physical bring-up;
this is the virtual bring-up that de-risks it. Implements plan §5.

**The rule that makes this work (already the repo's rule):** every peripheral sits
behind a seam. `haptic_out`/`drv2605` compile unchanged against a mock bus (bench),
an ESP-IDF I²C bus (band), and — new here — the same mock bus inside QEMU. QEMU's
gaps land exactly on seams we already own.

## The rungs

| Rung | What runs | What proves | Status |
|---|---|---|---|
| 0 | Bench suite: real sequencer, mock bus, virtual clock (`firmware/haptic_out/run_tests.py`) | timing tables + state machine produce exact dot-mask timelines | **shipped** (274 checks) |
| 1 | **QEMU boot app** (`firmware/app/ziv_qemu`): the real `haptic_out` + task loop inside an ESP-IDF app, haptic bus → the bench mock, keys/mic → injected/console events | the binary boots in QEMU, FreeRTOS runs it, and the scripted demo plays the correct timelines on the emulated chip | **core shipped** — `ziv_app` proven on the bench (49 checks, the full derived `HAP` fixture); QEMU boot pending an IDF install |
| 2 | **Equivalence harness**: same scripted sequence on bench (virtual clock) and in QEMU (wall clock); `tools/qemu_timeline.py` diffs the two `HAP` logs | QEMU firmware timelines ≡ bench timelines (order, masks, durations; wall-clock tolerance) | **differ shipped** — reads the *derived* fixture (generator cross-checked against the generated `k_demo_expected[]`); QEMU boot itself pending an IDF install; CI job skeleton in place (`qemu-boot`, continue-on-error — its one marked gap is the IDF install) |
| 3 | **Transport seam**: `ws_client` framing/reconnect/backoff behind a socket vtable; fake relay on host loopback; same vtable stubbed inside QEMU | relay round-trip logic is testable without WiFi — the code is exercised, the radio is not | speced |
| 4 | **Audio seam**: capture reads frames from an injectable source (canned WAV in QEMU/host; real I²S on band) | capture → Omni payload framing testable without a mic | speced |
| H | Hardware bring-up (HARDWARE_BRINGUP.md) | the one thing no simulator answers: does it *feel* right | gated on boards |

Rungs 0–4 share one property: hardware appears only at rung H, and everything
above it is CI-able.

## Rung 1 — the app skeleton

```
firmware/app/ziv_qemu/
  CMakeLists.txt            # normal IDF project; ../../haptic_out registered as a component
  main/
    CMakeLists.txt
    ziv_app.c               # app_main: init → scripted boot demo → console loop
    haptic_bus_log.c/.h     # HAP timeline lines from the sequencer's event stream
```

**The haptic backend is the bench mock bus, reused verbatim.** `mock_drv2605.c`
emulates the six register files behind the mux (with fault injection), and the app
links it exactly as the bench suite does. No second mock is written — QEMU and the
bench share one bus implementation, so rung-2 equivalence compares like with like.

**The observer split (who logs what):**

- *Register semantics* stay with the mock bus: `drv2605_init`'s
  MODE/RATEDV/CLAMPV/FEEDBACK writes, mux selects, RTPIN levels — validated in
  memory exactly as the bench does, faults surfacing via `last_err`.
- *Timeline lines* come from the real sequencer's own event stream: the app's
  playback loop receives `HAPTIC_OUT_EV_START / EV_BUZZ / EV_END` from
  `haptic_out_step()` — the same events a real motor would feel — and prints one
  machine-parseable line per event:

  ```
  HAP <at_ms> <evt:START|BUZZ|END> <mode:MARK|PATTERN|WORD|PREFIX> <mask_hex> <buzz_ms> <gap_ms> <seq>
  ```

  `at_ms` is `esp_timer_get_time()/1000` (monotonic). Silence is derivable
  (BUZZ end → next BUZZ start), so gaps are asserted, not logged. Because the
  lines originate in the event stream, they are the *real firmware's* testimony —
  not a parallel model of it.

**The playback loop** is the same pull model `haptic_out_task.c` uses
(`haptic_out_step(now)` → next deadline; delay until deadline). On the band the
loop body is a FreeRTOS task; here it is the same function called from `app_main`.

**Scripted boot demo** (runs automatically at boot — this is what rung 2 diffs):
the stage chain is defined once as the `DEMO_STAGES` table in
`tools/build_ziv_demo.py` — the same table that generates the app's
`k_demo_sequence[]` and the derived `HAP` fixture the bench asserts against —
and the generated block below is that single source rendered for humans.
That sequence exercises every mode (pattern, prefix, word) including both
lifecycle patterns added in spec v3.

<!-- haptic-demo-chain:begin (generated — do not edit; the stage table in this file is the single source; regenerate with tools/haptic_timing.py --write) -->

The scripted boot demo's stage chain, generated from the single source
of truth: the `DEMO_STAGES` table in `tools/build_ziv_demo.py` — the same
table that generates the app's `k_demo_sequence[]` and the derived
27-line `HAP` fixture the bench asserts against.

| Stage | Time span (ms) | Duration (ms) |
|---|---|---|
| ramp-up | 0-1270 | 1270 |
| prefix(message) | 1270-4130 | 2860 |
| word "ok" | 4130-5370 | 1240 |
| end-of-message | 5370-6630 | 1260 |
| heartbeat | 6630-7310 | 680 |

Total: 7310 ms across 27 HAP lines. Reordering or extending the demo means
editing `DEMO_STAGES` and regenerating (`tools/haptic_timing.py --write`):
the app's stage table, the bench fixture, and this table move together, and
`--verify` fails on any hand edit to this block.

<!-- haptic-demo-chain:end -->

**Console protocol** (ESP-IDF console component, stdio over the emulated UART):
`ziv play pattern <id>` · `ziv play word <letters>` · `ziv play mark <name>` ·
`ziv play prefix <tail>` · `ziv stop` · `ziv status`. The dispatch layer ships
now — `ziv_pattern_index` / `ziv_mark_index` / `ziv_tail_index` in `ziv_app.c`,
bench-verified — and the console-component wiring lands with the first QEMU
boot. Chord-key input is *not* simulated here: `braille_in` (plan §5) does not
exist yet, and its future host seam (console/GPIO-injected key events) is
designed when the module is — the console's command parser is the seam's
template.

**WiFi/mic are absent on purpose.** The rung-1 app performs no `esp_wifi` init and
no I²S setup — image stays small, boot stays fast, and nothing links a driver
QEMU cannot satisfy. The network and mic return at rungs 3–4 behind vtables.

**Running it** (after the one-time `python $IDF_PATH/tools/idf_tools.py install
qemu-xtensa`; on this machine see
[QEMU_WINDOWS_INSTALL.md](./QEMU_WINDOWS_INSTALL.md) — ESP-IDF + the QEMU fork
on Windows, with a smoke test whose pass criteria are the derived `HAP`
fixture (see the demo-chain block above — generated, not hand-counted):

```sh
idf.py qemu monitor        # interactive: console + HAP lines in the terminal
idf.py qemu                # capture stdout, Ctrl-A q to exit
```

## Rung 2 — equivalence

1. Bench emits the same `HAP` line format (a small serializer added to
   `test_haptic_out.c`'s harness — it already owns the timeline records; the
   events come from the identical `haptic_out_step()` stream).
2. `tools/qemu_timeline.py <bench.log> <qemu.log>` (shipped) compares: event order,
   dot masks, per-beat buzz/gap durations (from `at_ms` deltas), with a
   wall-clock tolerance (default ±10 ms, ~1 FreeRTOS tick) — mirroring how
   `tools/m1_summary.py` tolerates real-world jitter instead of pretending
   clocks don't drift. Its expected side is the **derived fixture**
   (`build_ziv_demo.demo_fixture_lines()`, cross-checked against the
   generated `k_demo_expected[]` — a stale generated file fails the differ
   with exit 2), so the boot check inherits the demo's single source of
   truth. The bench side is `host_demo --hap-log`: the same binary the C
   suite runs, printing its demo HAP stream.
   `run_ziv_tests.py` proves this plumbing every CI run by diffing the
   bench log against the fixture; the QEMU job reuses the identical
   invocation with the boot capture as the second log.
3. If jitter ever pollutes the diff beyond tolerance, the lever is QEMU's
   `icount` virtual-clock mode passed via
   `idf.py qemu --qemu-extra-args="..."` ⚠ (verify icount support in the
   Espressif fork before relying on it).

## Rungs 3–4 — the network and mic seams

Same vtable discipline as `drv2605_bus`, extracted before the relay exists:

- **Transport**: `ws_client` owns framing (text JSON vs binary audio), reconnect
  with bounded backoff, and state transitions. A `ziv_transport` vtable
  (`connect`/`send`/`poll`/`close`) lets a host test drive it against a fake
  relay on loopback (hermetic, fast, in pytest) and lets the QEMU app link a
  logging stub — so rung 2-style equivalence extends to the network *logic*
  even though QEMU has no WiFi.
- **Audio**: capture reads from a `ziv_audio_source` (`read_frames`) — canned WAV
  host-side, real I²S driver on band. The Omni payload framing (plan §11's
  open question) gets its first tests at this rung, with no mic and no network.

## CI shape (rung ≥ 1 lands)

GitHub Actions job `qemu-boot`: install Espressif QEMU prebuilt (x86_64 Linux),
`idf.py build`, boot headless ~30 s, then
`python tools/qemu_timeline.py bench_hap.log qemu.log` — the expected side
(the derived `k_demo_expected` fixture) and the comparison logic already
exist and are exercised on every CI run by the host suite's boot-check step,
so the job's only new work is producing `qemu.log`. The job now exists as a
skeleton (`qemu-boot`, `continue-on-error`): the bench side runs for real on
every push, and the only unfilled step is the marked ESP-IDF + Espressif QEMU
install — the boot-capture and differ steps are gated on its `available`
output and light up when the install lands, with nothing else to change.
After the first green run, make the job blocking — same promote-a-check
discipline as the drift guard.

## What this ladder does not answer

| Question | Rung that answers it |
|---|---|
| Does a 350 ms gap read as an ellipsis on skin? | H (feel is the product) |
| LRA auto-calibration, per-dot strength, mux electricals | H |
| Battery under WiFi bursts | H (rung 3 only proves the logic) |
| Real TCP/TLS behavior against Token Factory | rung 3 fake → then live relay on devkit |
| Omni audio payload acceptance | rung 4 framing → week-1 spike live |

## Verify at bring-up (⚠ carried per repo discipline)

- Exact QEMU machine name/args for S3 (`-M esp32s3 …`) per the fork's README at install time.
- GPIO emulation coverage (moot for rung 1 — no keys are wired yet — but bounds rung-H prep).
- `icount` determinism support (rung 2 lever, not a dependency).
- Flash-image merge behavior (`qemu_flash.bin` auto-generation) across IDF versions.
- Dual-core timing fidelity under TCG (the pull model is single-task; fine for this ladder, ⚠ for anything that later assumes SMP timing).
