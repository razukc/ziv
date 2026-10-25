# ziv_qemu — the QEMU boot app (simulation ladder rung 1)

Boots the **real Ziv firmware** — the same `haptic_out` sequencer the band
runs — inside Espressif's QEMU fork, with the bench mock bus as the haptic
backend. Spec: [docs/QEMU_SIMULATION_LADDER.md](../../../docs/QEMU_SIMULATION_LADDER.md).

```
CMakeLists.txt        ordinary ESP-IDF project (idf.py set-target esp32s3)
main/
  ziv_app.c/.h        the host-portable core: the real sequencer + HAP line
                      emission from its own event stream + the scripted
                      boot demo + console name lookups
  app_main.c          the IDF shell: esp_timer clock, UART sink, FreeRTOS loop
  host_demo.c         the bench proof: walks the demo on a virtual clock and
                      asserts the complete 27-line HAP fixture
run_ziv_tests.py      builds/runs the host proof (same compiler discipline
                      as firmware/haptic_out/run_tests.py)
```

## The HAP log (one line per sequencer event)

```
HAP <at_ms> START <mode> <payload>
HAP <at_ms> BUZZ <mode> <payload> <mask_hex> <buzz_ms> <gap_ms> <seq>
HAP <at_ms> END
```

`mode` = MARK | PATTERN | WORD | PREFIX; `payload` = the spec id
(`ramp-up`, `message`, `ziv`, spelled word, ...); `mask_hex` = which dot
motors are up (`00` for whole-device attention/lifecycle patterns); `gap_ms`
= the silence *after* this buzz. Silence is derivable from `at_ms` deltas —
gaps are asserted, never logged.

The lines come from `haptic_out_step()`'s events — the same events a real
motor would feel — so the log is the firmware's testimony, not a parallel
model. Rung 2 (`tools/qemu_timeline.py`, speced) diffs the QEMU boot's HAP
output against the bench fixture.

## Run it

Host (no ESP-IDF needed — the proof runs here):

```sh
python run_ziv_tests.py     # in the agent venv (ziglang) or any host gcc
```

QEMU (after `python $IDF_PATH/tools/idf_tools.py install qemu-xtensa` —
on this Windows machine: [docs/QEMU_WINDOWS_INSTALL.md](../../../docs/QEMU_WINDOWS_INSTALL.md)):

```sh
idf.py set-target esp32s3
idf.py qemu monitor         # the scripted demo's HAP lines on the UART
```

Pass criteria: the 27 `HAP` lines above, in order (wall-clock `at_ms` —
the *deltas* are the assertion).

The scripted boot demo plays automatically at boot:
`ramp-up → prefix(message) → word "ok" → end-of-message → heartbeat` —
every playback mode, including both spec-v3 lifecycle patterns.

WiFi and the mic are absent **on purpose** (no `esp_wifi`, no I²S driver) —
they return at ladder rungs 3–4 behind the `ziv_transport` /
`ziv_audio_source` vtables. The console command protocol
(`ziv play pattern <id>` · `ziv play word <letters>` · `ziv stop` ·
`ziv status`) lands with the IDF console-component wiring; the dispatcher it
will call (`ziv_pattern_index` and friends) is in `ziv_app.c`, exercised by
the host tests.
