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
| 1 | **QEMU boot app** (`firmware/app/ziv_qemu`): the real `haptic_out` + task loop inside an ESP-IDF app, haptic bus → the bench mock, keys/mic → injected/console events | the binary boots in QEMU, FreeRTOS runs it, and the scripted demo plays the correct timelines on the emulated chip | **proven** — builds with ESP-IDF v5.5 (`ziv_qemu.bin` 0x30dd0 bytes), boots in Espressif QEMU 9.0.0 (esp32s3), plays all 27 `HAP` lines; capture committed as `firmware/app/ziv_qemu/qemu_boot.log`. Bench proof unchanged (49 checks) |
| 2 | **Equivalence harness**: same scripted sequence on bench (virtual clock) and in QEMU (icount virtual clock, or wall clock interactively); `tools/qemu_timeline.py` diffs the two `HAP` logs | QEMU firmware timelines ≡ bench timelines (order, masks, durations; ±10 ms) | **proven** — `PASS — 27 HAP events matched within tolerance`, zero drift under `-icount shift=5,sleep=off` (three runs); the `qemu-boot` CI job builds both images, boots both, diffs (still continue-on-error until its first green run on GitHub) |
| 3 | **Transport seam** (`firmware/band`): the relay protocol — hello/ack, utterance open/body/cancel, progress/played/nack, prefs, ping/pong, reconnect with backoff and jitter, resume by `last_acked`+held — behind a frame vtable; on the host newline-JSON over TCP against `firmware/band/host/fake_relay.py`, on the band `esp_websocket_client` | relay round-trip logic is testable without WiFi — the code is exercised, the radio is not | **host-proven, device-compiled, QEMU-booted** — `firmware/band/run_band_tests.py`: unit tests against a scripted adapter, the loopback run against the fake relay (every up frame validated with `ziv.wire`, order asserted), plus the conformance player on both profiles (12/12); the band builds against ESP-IDF v5.5 with the registry's `esp_websocket_client` (`firmware/band/esp_project`, `ziv_band.bin` 0xe24d0 bytes) and boots in QEMU with the mock bus and no radio: NVS, the queue, the websocket client created, the transport backing off (`firmware/band/esp_project/qemu_boot.log`). A live relay over real Wi-Fi is still unverified |
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

  `at_ms` is `esp_timer_get_time()/1000` (monotonic), rebased to the demo's
  start on the device so both logs share the bench's epoch (boot time is not
  part of the timeline). Silence is derivable
  (BUZZ end → next BUZZ start), so gaps are asserted, not logged. Because the
  lines originate in the event stream, they are the *real firmware's* testimony —
  not a parallel model of it.

**The playback loop** is the same pull model `haptic_out_task.c` uses
(`haptic_out_step(now)` → next deadline; wait until deadline). On the band the
loop body is a FreeRTOS task; here it is a FreeRTOS task started from `app_main`,
pinned to CPU0. The wait is an `esp_timer` one-shot armed at the absolute
deadline plus a task notification, not `vTaskDelay()`: under QEMU the emulated
periodic tick loses whole ticks when the host is late, and because the
sequencer schedules each beat from `now`, a tick-based wait turned every slip
into permanent drift (measured +84 ms over the demo on a quiet host). Two
other things the first boot taught: a 50 ms idle poll must not step an idle
sequencer (its contract reports END on every idle step — `ziv_app_step` now
owes exactly one END per play), and the component's source paths are relative
to `main/`, not the project.

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
bench-verified — and the console-component wiring is still pending: the first
QEMU boot landed without it (the demo needs no input), so today the UART is
output-only. Chord-key input is *not* simulated here: `braille_in` (plan §5) does not
exist yet, and its future host seam (console/GPIO-injected key events) is
designed when the module is — the console's command parser is the seam's
template.

**WiFi/mic are absent on purpose.** The rung-1 app performs no `esp_wifi` init and
no I²S setup — image stays small, boot stays fast, and nothing links a driver
QEMU cannot satisfy. The network returns at rung 3 behind the `band_frame_io`
vtable (`firmware/band`, host-proven) and the mic at rung 4 behind its own.

**Running it** (install: [QEMU_WINDOWS_INSTALL.md](./QEMU_WINDOWS_INSTALL.md),
whose Linux/WSL2 section is the recipe that was executed). Pass criteria are
the derived `HAP` fixture (the demo-chain block above — generated, not
hand-counted):

```sh
cd firmware/app/ziv_qemu
idf.py set-target esp32s3 && idf.py build     # proven: ziv_qemu.bin binary size 0x30dd0 bytes
idf.py qemu monitor                           # interactive: console + HAP lines in the terminal
# bounded, deterministic capture of UART0 to a file (what rung 2 and CI use):
QEMU_UNTIL="$(tail -1 bench_hap.log)" ../../qemu_capture.sh . qemu_boot.log
```

`sdkconfig.defaults` carries only the target; `build/`, `sdkconfig` and
`managed_components/` are ignored, `qemu_boot.log` is tracked as evidence.

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
3. **Proven.** With the esp_timer wake (above) and `firmware/qemu_capture.sh`
   (`-icount shift=5,sleep=off`):

   ```
   PASS — 27 HAP events matched within tolerance
   ```

   with no within-tolerance notes at all — every one of the 27 timestamps
   equals the bench's (0, 0, 140, 350, 650, 1270, … 6820, 7310), three runs
   out of three, including one under load average 13. The jitter lever
   turned out to be a necessity, not an option; what was measured on the
   way (WSL2, 8 cores):

   | Mode | Max drift over the 27 events | Note |
   |---|---|---|
   | wall clock, tick-based wait (`vTaskDelay`) | +10 ms on a semi-idle host, **+84 ms** quiet, **+1039 ms** at load 13 | whole-tick slips (+10/+20/+30): the emulated periodic alarm loses ticks when the host is late; each slip shifts the rest of the timeline because the sequencer schedules from `now` |
   | wall clock, esp_timer wait, task unpinned | +80…+210 ms per wait in a 1.3–5 s window after boot | cross-core wake of a halted vCPU under multi-threaded TCG |
   | wall clock, esp_timer wait, pinned to CPU0 | **+2 ms** (PASS) in one run, one **+95 ms** slip in the next | usable interactively; not for a gate |
   | `-icount shift=auto` | +75 ms by 1.3 s | auto raises the shift until each guest instruction costs ms of virtual time |
   | `-icount shift=5,sleep=off` | **0 ms**, three runs | deterministic; ROM start-up loop costs ~35 s of host time, then the demo takes 4 s |
   | `-icount shift≤3,sleep=off` | — | never got past the ROM's start-up loop in 20 s (host time ∝ 2⁻ˢʰⁱᶠᵗ) |

   Two gaps found on the way, both outside the firmware: the differ's
   boot-chatter filter (`BOOT_CHATTER_RE` in `tools/qemu_timeline.py`) knows
   `I (…)` lines but not the ROM's own (`Build:`, `rst:`, `SPIWP:`, `mode:`,
   `load:`, `entry`) nor `W (…)`/`E (…)` levels, so on a real capture it
   exits 2 (`Unrecognized HAP line: 'Build:Mar 27 2021'`); until it learns
   them the differ is fed `grep '^HAP '` of the capture (the saved log keeps
   everything). And `run_ziv_tests.py` deletes the `bench_hap.log` it makes,
   so the CI job emits it again with `host_demo --hap-log`.

## Rungs 3–4 — the network and mic seams

Same vtable discipline as `drv2605_bus`, extracted before the relay exists:

- **Transport** — shipped on the host as `firmware/band/transport.c`. The
  protocol layer (hello first, the ack's prefs and resend list, utterance
  open/body/cancel, progress/played/nack, pref.set/pref.changed, ping/pong,
  exponential backoff with jitter, resume by `last_acked` + held ids) sits
  behind a `band_frame_io` vtable (`connect`/`send_frame`/`recv_frame`/
  `close`), so framing is the adapter's job: `host/frame_tcp_host.c` speaks
  newline-delimited JSON over TCP to `host/fake_relay.py`, and
  `esp/transport_ws_esp.c` (unverified, no IDF here) hands the same frames
  to `esp_websocket_client`. `firmware/band/run_band_tests.py` is the rung's
  runner: the unit tests drive the protocol against a scripted in-memory
  adapter (frame shapes, order, nack reasons, backoff bands, resume), the
  loopback test runs the real TCP path with the haptics on a virtual clock,
  and the fake relay validates every up frame against the wire models and
  asserts progress(cue) → progress(word…) → progress(close) → played in
  queue order. The same runner builds `firmware/app/ziv_qemu/host_player`
  and holds it to the reference renderer on both profiles — the band's
  decoder + turn + sequencer are conformant before any radio exists. What
  remains for QEMU is linking the vtable to a logging stub inside the image
  (the code is the same; only the adapter changes).
- **Audio**: capture reads from a `ziv_audio_source` (`read_frames`) — canned WAV
  host-side, real I²S driver on band. The Omni payload framing (plan §11's
  open question) gets its first tests at this rung, with no mic and no network.

## CI shape (rung ≥ 1 lands)

GitHub Actions job `qemu-boot` (filled in): runs in the `espressif/idf:v5.5`
container, installs `libsdl2-2.0-0 libslirp0` and
`idf_tools.py install qemu-xtensa`, builds `ziv_qemu`, captures its boot with
`firmware/qemu_capture.sh` (icount, sentinel = the bench log's last line),
runs `tools/qemu_timeline.py` on the capture's HAP lines, then builds
`firmware/band/esp_project`, boots it the same way and asserts the band's
boot shape (app_main reached, "wifi: unavailable", the ramp-up's HAP lines,
≥2 "transport: connect failed", no panic, exactly one reset line). Both logs
are uploaded as artifacts. It is still `continue-on-error: true` because this
branch has never been pushed; after its first green run on GitHub, make it
blocking — same promote-a-check discipline as the drift guard.

## What this ladder does not answer

| Question | Rung that answers it |
|---|---|
| Does a 350 ms gap read as an ellipsis on skin? | H (feel is the product) |
| LRA auto-calibration, per-dot strength, mux electricals | H |
| Battery under WiFi bursts | H (rung 3 only proves the logic) |
| Real TCP/TLS behavior against the relay | rung 3 fake (shipped: `firmware/band/host/fake_relay.py`) → then the live relay's websocket on a devkit |
| Omni audio payload acceptance | rung 4 framing → week-1 spike live |

## Verify at bring-up (⚠ carried per repo discipline)

- ✓ QEMU machine args for S3: `-M esp32s3`, efuse device `nvram.esp32c3.efuse` (sic — the fork reuses the C3 class), `-nic user,model=open_eth`; taken from IDF 5.5's `tools/idf_py_actions/qemu_ext.py` and reproduced in `firmware/qemu_capture.sh`. The `timer.esp32s3.timg … wdt_disable` global `idf.py qemu` passes is rejected by QEMU 9.0.0 ("invalid class name") — harmless so far (no watchdog fired in any capture), kept for parity.
- GPIO emulation coverage (moot for rung 1 — no keys are wired yet — but bounds rung-H prep).
- ✓ `icount`: supported by the fork; `shift=5,sleep=off` is deterministic and exact (rung 2 above), with the ROM start-up cost noted there.
- ✓ Flash-image merge: `esptool merge_bin --fill-flash-size <CONFIG_ESPTOOLPY_FLASHSIZE> @flash_args`, as `idf.py qemu` does; 2 MB (ziv_qemu) and 4 MB (band) both boot.
- Dual-core timing fidelity under TCG: the unpinned-task result above is the first data point (cross-core wakes are slow in wall-clock mode); the ladder's loops are now pinned to CPU0. ⚠ for anything that later assumes SMP timing.
