# Hardware bring-up — haptic_out on the wrist

The bench suite proves the sequencer plays exactly what the timing spec says.
This checklist gets the same code buzzing real actuators, and ends where the
bench ends: **the first phone-vs-band comparison of the Ziv mark** (stage C).
Everything before that stage is plumbing; stage C is the milestone the whole
haptic trail has been building toward.

Code references: `firmware/haptic_out/` (see its
[README](../firmware/haptic_out/README.md) for architecture). Timings always
come from [`haptic-timing.json`](haptic-timing.json) — nothing in this doc
introduces a second clock.

---

## 1. Parts list

| Qty | Part | Why | Notes |
|---|---|---|---|
| 1 | ESP32-S3-DevKitC-1 (N8R2 or bigger) | WiFi+BLE for phone control later; USB for flashing | any ESP32/S3/C3 devkit works; pin numbers below assume S3 |
| 6 | DRV2605L breakout (Adafruit #2305 or equivalent) | one per braille dot; RTP mode driver | bare modules fine — check their I2C voltage handling yourself |
| 1 | TCA9548A I2C mux breakout (Adafruit #2717 or equivalent) | all six DRV2605L sit at fixed address 0x5A | mux at 0x70 (A0–A2 floating) |
| 6 | LRA actuator, 2–3 V rated (a 10 mm coin LRA or similar) | the dot | matches the driver's RATEDV/CLAMPV defaults (see §5); ERM coins work for a desk test but the driver is set for LRA |
| 2 | Breadboards | the chain outgrows one | |
| — | Jumper wires (M/M, M/F), silicone strap or cuff, hot-glue/heat-shrink | mounting the cell | |
| 1 | USB 5 V ≥ 3 A supply + cable | motor rail — see the power note | |
| opt | USB current meter | sanity-check the rail | |

**Power note — read before wiring.** A 2 Vrms / 2.4 Ω LRA draws ~0.8 A RMS,
and a 4-dot cell plays four at once (~3 A peaks). The devkit's 3V3 regulator
cannot supply that. Power the six DRV2605L breakouts' VIN from the external
5 V rail; the TCA9548A and the ESP32 run from the devkit's 3V3. **Common
ground across everything is mandatory.** The Adafruit breakouts level-shift
their I2C, so 3.3 V logic from the ESP32 is safe with 5 V VIN.

## 2. Wiring

```
ESP32-S3 DevKitC            TCA9548A (0x70)          DRV2605L ×6 (0x5A behind mux)
GPIO8  ──────────────────►  SDA                      CH0 ──► DRV #0 (dot 1) SDA/SCL
GPIO9  ──────────────────►  SCL                      CH1 ──► DRV #1 (dot 2)
3V3    ──────────────────►  VIN                      CH2 ──► DRV #2 (dot 3)
GND    ──────────────────►  GND                      CH3 ──► DRV #3 (dot 4)
                            CH4 ──► DRV #4 (dot 5)
5V rail ──► DRV #0..5 VIN   CH5 ──► DRV #5 (dot 6)
GND (all) ── common ground  each LRA ──► its DRV's OUT+/OUT−
```

- Dot n = mux channel n−1 = DRV #n−1. The bus vtable hard-codes this map
  (`DRV2605_DOT_COUNT`, `TCA9548_ADDR` in `drv2605_i2c.h`); wire to match, or
  re-map in code.
- **Cell layout (braille dot numbering):** two columns × three rows —
  1,2,3 down the left, 4,5,6 down the right:

  ```
  1 4
  2 5
  3 6
  ```

  12–15 mm spacing is a starting point for forearm/wrist skin; the marks'
  letter *shapes* only need the relative geometry. Mount on the strap, keep
  actuator polarity consistent per the breakout silkscreen.
- Keep the mux→DRV stubs short; a 12-device I2C chain is electrically long.

## 3. Firmware bring-up

1. **Install ESP-IDF 5.x** (Windows installer or the VS Code extension).
2. **Resolve the I2C TODO** in `drv2605_i2c_esp32.c`. The sketch uses the
   legacy `driver/i2c.h` API (`i2c_master_write_to_device`); that still
   compiles but is deprecated. Either keep it for bring-up or port to
   `driver/i2c_master.h` (recommended: register the mux once plus six device
   handles, then transmit/receive-dev). Either way: set `SDA=8`, `SCL=9`
   (common S3 default — any free GPIO works), `I2C_PORT=0`.
3. **Resolve the task TODOs** in `haptic_out_task.c`: verify
   `pdTicksToMs`/`pdMsToTicks` exist in your IDF version (some versions
   spell them `pdTICKS_TO_MS`/`pdMS_TO_TICKS`); queue length 8 and 4 KB
   stack are fine to start. Two small gaps to fill while you're there:
   the sketch declares no header — create `haptic_out_task.h` declaring
   `haptic_out_task_init` and the `haptic_post_*` helpers — and it has
   no prefix poster; add `haptic_post_prefix(uint8_t t)` mirroring
   `haptic_post_mark` with kind `'X'` (four lines, needed for stage E).
4. **Create the app**: an `app_main` that builds the bus and starts the
   task, then plays the boot demo (§4 stage B–E commands):

   ```c
   #include "freertos/FreeRTOS.h"
   #include "freertos/task.h"
   #include "haptic_out_task.h"   /* create in step 3: haptic_post_* */
   #include "drv2605_i2c.h"       /* drv2605_bus */
   #include "haptic_timing.h"     /* HAPTIC_TAIL_MESSAGE */
   extern void drv2605_bus_esp32(drv2605_bus *bus);  /* sketch has no header yet */
   void app_main(void) {
       drv2605_bus bus;
       drv2605_bus_esp32(&bus);
       haptic_out_task_init(&bus);
       /* boot demo — see §4 for the staged sequence */
       haptic_post_mark(0);          /* ziv mark */
       vTaskDelay(pdMS_TO_TICKS(3000));
       haptic_post_word("ziv");
       vTaskDelay(pdMS_TO_TICKS(3000));
       haptic_post_prefix(HAPTIC_TAIL_MESSAGE);
   }
   ```

   Wire the app's CMakeLists to the component
   (`EXTRA_COMPONENT_DIRS` → the repo's `firmware/haptic_out`).
5. **Build & flash**: `idf.py set-target esp32s3 && idf.py build` then
   `idf.py -p PORT flash monitor`.

## 4. Flash-and-feel test — six stages

Run the stages in order; each isolates one layer so a failure has exactly
one suspect.

### Stage A — I2C layer (no haptic code)

Flash a scanner: select each mux channel, probe every address on it.

```c
#include <stdio.h>
#include "driver/i2c.h"
void app_main(void) {
    i2c_config_t cfg = { .mode = I2C_MODE_MASTER, .sda_io_num = 8,
        .scl_io_num = 9, .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE, .master.clk_speed = 100000 };
    i2c_param_config(0, &cfg);
    i2c_driver_install(0, I2C_MODE_MASTER, 0, 0, 0);
    for (int ch = 0; ch < 6; ch++) {
        uint8_t sel = (uint8_t) (1u << ch);
        i2c_master_write_to_device(0, 0x70, &sel, 1, pdMS_TO_TICKS(50));
        printf("ch %d:", ch);
        for (uint8_t a = 0x03; a <= 0x77; a++) {
            i2c_cmd_handle_t cmd = i2c_cmd_link_create();
            i2c_master_start(cmd);
            i2c_master_write_byte(cmd, (uint8_t) (a << 1), true);
            i2c_master_stop(cmd);
            if (i2c_master_cmd_begin(0, cmd, pdMS_TO_TICKS(50)) == ESP_OK)
                printf(" 0x%02X", a);
            i2c_cmd_link_delete(cmd);
        }
        printf("\n");
    }
}
```

**Pass:** every channel prints `0x5A` (`0x70` also appears in every scan —
the mux itself is always on the main bus).

| Symptom | Usual suspect |
|---|---|
| nothing on main bus | SDA/SCL swapped, mux power, missing pull-ups |
| `0x70` OK, no `0x5A` anywhere | mux→DRV stub wiring, DRV VIN rail, common ground |
| one channel silent | that DRV's VIN/solder, or its LRA shorting OUT+/OUT− |

### Stage B — one dot

Flash the haptic app but post only `WORD "a"` (letter a = dot 1, one 110 ms
buzz). **Pass:** a single localized tick at the dot-1 position, on every
replay. Now sweep `DRV2605_DRIVE_DEFAULT` (try 30 / 60 / 90) and note the
lowest level you can clearly feel — that number is the first real datum the
bench couldn't produce.

### Stage C — the first phone-vs-band comparison

Post `WORD "ziv"` and play the feel-tool's Spell box (`ziv`, gap slider 420)
on the phone at the same time. Expect 290 · 170 · 290 ms cells (4 · 2 · 4
dots), 420 ms gaps, one tail gap of silence. **Pass:** the wrist rhythm is
indistinguishable from the phone rhythm by feel. If the band's cells feel
delayed by a few ms, that's the sequential mux writes
(12 I²C transactions per cell edge ≈ 4–5 ms at 100 kHz) — imperceptible in
principle; if you can sense smear, raise the bus to 400 kHz.

### Stage D — marks and the §4 attention table

Post `MARK 0` (ziv — must feel identical to stage C's word; the bench test
`test_word_ziv_equals_mark` guarantees the firmware agrees), then each
pattern: double-tap, ramp-up, heartbeat, long-buzz. **Pass:** the whole §4
table reads on the wrist. Short 70 ms ticks feeling softer than the phone is
expected — RTP ramp-up eats part of a short buzz; note it, don't fix it yet.

### Stage E — the prefix (who → why)

Post `PREFIX HAPTIC_TAIL_MESSAGE`: ziv mark, 550 ms breath, double-tap.
**Pass:** the "who is talking, then why" reading holds at wrist scale —
this is the interaction the whole naming thesis rests on.

### Stage F — fault drills

Unplug one DRV mid-quiet, replay: the play must fail with `HAPTIC_ERR_IO`
and the remaining dots must stay correct (the bench `test_bus_fault` path,
now with real NACKs). Re-plug and confirm recovery. `STOP` must silence
instantly.

## 5. After the stages pass

- Record: per-dot drive level, perceived distinctiveness notes
  (ziv vs tin/wiz — same arc by construction, does it *feel* same?),
  any timing smear, thermal comfort after a few minutes of looping.
- Expect to revisit `RATEDV`/`CLAMPV` per channel: an LRA's resonance
  varies part to part (the driver's init already notes per-dot calibration
  as a later step). Stage B's drive sweep is the entry point.
- The next milestone after bring-up is data, not features: take the strap
  to the M1 recognition protocol ([NAMING_VALIDATION_PROTOCOL.md](NAMING_VALIDATION_PROTOCOL.md))
  and collect the first on-skin reaction times.
