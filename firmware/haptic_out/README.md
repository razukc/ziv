# haptic_out — the band's haptic channel (plan §5)

Every buzz and silence the Ziv band plays comes from one clock:
[`docs/haptic-timing.json`](../../docs/haptic-timing.json) → the generated
[`haptic_timing.h`](./haptic_timing.h) → this module. The phone feel-tool
(`docs/haptic-name-marks.html`) is generated from the same JSON, so the
pattern you feel on the phone is the pattern the motors play — by
construction, not by convention.

## What is here

| File | Role | Runs on |
|---|---|---|
| `haptic_timing.h` | **generated** timing tables (constants, patterns, alphabet, marks, prefix tails) | bench + band |
| `drv2605_i2c.h` | bus abstraction: module error codes, DRV2605L register map, I2C vtable | bench + band |
| `drv2605.h` / `.c` | register-level DRV2605L driver (RTP mode, per-dot drive) | bench + band |
| `haptic_out.h` / `.c` | cell sequencer + pattern player (the state machine) | bench + band |
| `mock_drv2605.h` / `.c` | bench mock of the DRV2605L bus (register files + fault injection) | bench only |
| `test_haptic_out.c` | bench tests: exact timelines vs the generated tables | bench only |
| `run_tests.py` | build + run the bench tests with a host C compiler | bench only |
| `drv2605_i2c_esp32.h` / `.c` | ESP-IDF I2C bus on `driver/i2c_master.h` (TCA9548A mux, one-hot select) — **compiles against ESP-IDF v5.5**, never executed (QEMU boots the mock; **unverified on hardware**); compiles to stubs on the host | band (stubs on bench) |
| `haptic_out_task.h` / `.c` | FreeRTOS task owning the sequencer — **compiles against ESP-IDF v5.5** (linked into the band image, not started by it; **unverified on hardware**) | band |
| `CMakeLists.txt` | ESP-IDF component build (excludes bench-only files) — not used by either project yet (the band compiles these sources directly, the QEMU app compiles them with the mock); kept as the standalone-component shape | band |

The band's utterance path — decoder, queue, turn, transport — lives in
[`firmware/band/`](../band/README.md) and drives this module through
`haptic_out_play_beats()`.

## The design

**Pull model.** The module never blocks. The app (or the test harness) calls
`haptic_out_step(now_ms)` and gets back the monotonic deadline of the next
state change; the bus writes inside the step (dots up at buzz start, all
silent at buzz end) are the only I/O. On the band a FreeRTOS task owns the
loop; on the bench the tests drive it against a virtual clock — identical
code path, so the bench results transfer to the wrist.

**RTP mode, not the waveform sequencer.** Each dot channel is one DRV2605L
behind a TCA9548A mux (the chip's I2C address is fixed at 0x5A). Real-time
playback mode writes a drive level (0..127) to `RTPIN`; that is the right
primitive for vibro-braille — one cell = the six channels at their levels
for `buzz_ms`, then zero for the gap — and it sidesteps the 8-slot
waveform sequencer entirely.

**Playback surfaces** (all from the generated tables):

- `haptic_out_play_mark(i)` — candidate name mark (protocol §0)
- `haptic_out_play_pattern(p)` — attention pattern (plan §4)
- `haptic_out_play_word("ziv")` — any word, one cell per letter
- `haptic_out_play_prefix(tail)` — mark → `PREFIX_BREATH_MS` → attention tail
  (the §4 morning-brief moment: who is talking, then why)
- `haptic_out_play_beats(beats, n)` — any compiled timeline: a caller-owned
  list of `{dot_mask, buzz_ms, gap_after_ms}` beats, emitting the same
  START/BUZZ/END events (the band's turn module compiles an utterance
  segment into one of these; the bench proves a list reproduces a word play
  beat for beat)

**The pace is a runtime variable.** `haptic_out_set_cell_gap_ms()` sets the
silence between cells inside a mark, word or prefix play, clamped to
`[CELL_GAP_MIN_MS, CELL_GAP_MAX_MS]` and defaulting to `CELL_GAP_DEFAULT_MS`;
patterns and beat lists carry their own gaps.

Every play ends with the tail gap of silence before the END event, matching
the phone's cadence so back-to-back plays never merge.

## Running the bench tests

The module is host-portable (no ESP-IDF types in the core), so the exact
code that will run on the band compiles and runs on a laptop:

```sh
python firmware/haptic_out/run_tests.py
```

The runner auto-detects `cc`/`gcc`/`clang`/`tcc`/`zig` (or a real WSL
install) and builds with `-Wall -Wextra -Werror -std=c11`. The suite drives
the mock bus and asserts exact timelines — buzz start times, durations,
gaps, and dot bitmasks — against the generated tables, plus fault
injection (a dead dot channel), the rename-arc property (tin/wiz spell
the same arc as ziv), the mux control-byte contract, the runtime pace at
the envelope's edges, and the beat mode reproducing a word and a pattern
beat for beat.

No compiler on this box? `winget install w64devkit` (Windows) or
`sudo apt install gcc` (WSL), then re-run.

## Wiring the band (compiled and QEMU-booted; unverified on hardware)

1. `drv2605_bus_esp32_init(&bus, &pins)` creates the `i2c_master` bus, the
   mux device handle and the one shared DRV2605 handle, and fills the
   vtable (`drv2605_bus_esp32()` fills the vtable alone).
2. `haptic_out_task_init(&bus)` creates the FreeRTOS task and command queue;
   the app posts `MARK` / `PAT` / `WORD` / `PREFIX` / `PACE` / `STOP`
   commands (`haptic_out_task.h`). The band's utterance path does not go
   through this queue — `firmware/band` owns its own `haptic_out`.
3. The task drives `haptic_out_step()` on the FreeRTOS tick; `END` is where
   the app decides what happens next.

**The mux contract.** The TCA9548A control byte is a bitmask — bit n
enables channel n — and exactly one bit must be set to reach one DRV2605L
(`tca9548_select_byte(ch) == 1 << ch`). The first sketch wrote the raw
channel number; the bench mock now refuses any control byte that is not
one-hot (`test_mux_select_contract`), so that regression fails on the bench
before it reaches a board.

**Where this stands.** The sequencer and driver run on the emulated chip:
`firmware/app/ziv_qemu` boots them in Espressif QEMU on the mock bus and
their 27-line demo timeline matches the bench exactly
(`docs/QEMU_SIMULATION_LADDER.md`, rungs 1–2 proven). `drv2605_i2c_esp32.c`
and `haptic_out_task.c` compile against ESP-IDF v5.5 with `-Wall -Wextra
-Werror -Wunused-parameter -Wsign-compare` as part of the band image
(`firmware/band/esp_project`) — the IDF 5.x `i2c_master` API, FreeRTOS tick
macros and queue calls are spelled right — but no `i2c_master` transaction
has executed and no motor has moved: QEMU emulates no I²C peripheral worth
trusting and the band boots with `CONFIG_ZIV_BAND_HAPTIC_MOCK=y`. The
register map and the sequencer are what the bench locks down; the bus is
what a board verifies. One finding from the emulated chip that matters on
silicon: a deadline wait built on the FreeRTOS tick (`vTaskDelay`, as
`haptic_out_task.c` does) is good to one tick and drifts if ticks are lost;
the QEMU app moved to an `esp_timer` one-shot wake for a millisecond-exact
timeline — do the same here if the HAP diff is ever run against a board.
Parts, wiring, and the staged flash-and-feel test live in
[HARDWARE_BRINGUP.md](../../docs/HARDWARE_BRINGUP.md).

## Change discipline

Never tune a duration in this module — edit `docs/haptic-timing.json`,
run `python tools/haptic_timing.py --write`, re-run the bench tests, then
re-feel on the phone. The generated header is one artifact with the phone
feel-tool; they drift together or not at all.