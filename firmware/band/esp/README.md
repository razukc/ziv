# firmware/band/esp — the band's ESP-IDF glue (compiled, QEMU-booted; board unverified)

Everything in this directory is written against **ESP-IDF v5.5** and, as of
this branch, **compiles against it and boots under Espressif QEMU**:
`firmware/band/esp_project` builds this directory as one component
(`ziv_band.bin` 0xe24d0 bytes, 40% of the 1.5 MB factory slot free) with the
repo's host discipline (`-Wall -Wextra -Werror -Wunused-parameter
-Wsign-compare`), fetching `espressif/esp_websocket_client` 1.8.0 from the
component registry. Every file here is still under `#if defined(ESP_PLATFORM)`,
so the host proofs in `../run_band_tests.py` cannot be affected by it.

| File | Role |
|---|---|
| `band_main.c` | `app_main`: NVS → the haptic bus (mock or I²C per `CONFIG_ZIV_BAND_HAPTIC_MOCK`) → the sequencer → the turn → the queue (NVS blob, loaded at boot) → the transport (websocket adapter) → Wi-Fi station if an SSID is configured; then the loop task: the boot ramp-up on the sequencer (HAP lines in the rung-1 format), then `transport_step` → `transport_wait`, backing off while the link is down |
| `transport_ws_esp.c` | the `band_frame_io` adapter on `esp_websocket_client`: text frames in a FreeRTOS queue, blocking `recv_frame` with a timeout, `hello` goes out as the first frame (never a key in the URL); a **link gate** — `connect()` fails fast until the station has an IP, so the protocol layer backs off instead of opening a socket on a stack with no interface |
| `queue_nvs_esp.c` | the `band_queue_store` adapter on NVS: one blob under namespace `ziv`, key `queue` |
| `CMakeLists.txt` | the IDF component: the band sources, the haptic_out sources, **both** buses (`drv2605_i2c_esp32.c` and the bench mock) and `haptic_out_task.c`, so the device paths are type-checked on every build whichever one boots; `json` is IDF's own cJSON |
| `idf_component.yml` | the component manifest: `espressif/esp_websocket_client` from the registry (`esp_project/dependencies.lock` pins 1.8.0) |
| `Kconfig` | `menuconfig` → "Ziv band": the haptic mock switch, Wi-Fi credentials, the relay URI, the device key, the profile, the I²C pins |

## Building and booting

```sh
cd firmware/band/esp_project
idf.py set-target esp32s3     # sdkconfig.defaults already names the target, 4 MB flash, the large single-app table
idf.py build                  # proven: ziv_band.bin binary size 0xe24d0 bytes
```

`esp_project/CMakeLists.txt` is the smallest IDF project that wraps this
directory (`EXTRA_COMPONENT_DIRS ../esp`, `COMPONENTS esp` — this directory IS
the component, IDF names it after the folder); there is no `main/`, `app_main`
lives in `band_main.c`. `build/`, `sdkconfig` and `managed_components/` are
ignored; `dependencies.lock` and `qemu_boot.log` are tracked.

**QEMU** (default Kconfig: `ZIV_BAND_HAPTIC_MOCK=y`, empty SSID — there is no
radio and no I²C peripheral traffic to verify in QEMU anyway):

```sh
QEMU_UNTIL='transport: connect failed' QEMU_UNTIL_COUNT=4 \
    ../../qemu_capture.sh . qemu_boot.log      # from esp_project; or idf.py qemu monitor
```

The committed [`qemu_boot.log`](../esp_project/qemu_boot.log) is that capture:
NVS ready → the mock bus and `DRV2605 x6 initialised` → the turn → `queue: 0
held` → the websocket client created → the two WARN lines (no device key; `wifi:
unavailable — no SSID configured … the transport stays offline and backs off`)
→ the ramp-up's six `HAP` lines → `loop: transport offline, link down` →
`transport: connect failed` at the protocol's exponential backoff with jitter,
no panic, no reboot. That is the expected shape wherever there is no network.

**A board** (`idf.py menuconfig` → Ziv band): `ZIV_BAND_HAPTIC_MOCK=n`,
SSID/password, the relay URI (`wss://…/ws`), the device key; then
`idf.py build flash monitor`. Never commit credentials — they are Kconfig
options with empty defaults, not entries in `sdkconfig.defaults`.

## What the host already proved, and what this adds

The band logic this glue wires up — the decoder, the queue image, the turn,
the protocol, the backoff — is the code `../run_band_tests.py` runs on the
host (unit tests, the conformance player on both profiles, the transport
over loopback against `../host/fake_relay.py`). The adapters here are thin
on purpose: the websocket does the framing, NVS stores one blob, and the
loop is `transport_step` → `transport_wait`, the same pull model as the
bench and the rung-1 app.

Compiling and booting on the device toolchain added: the IDF 5.5 API
spellings (`driver/i2c_master.h`, `esp_websocket_client` 1.8 events and
config, NVS, `esp_wifi`/`esp_netif`/`esp_event`) are right; the FreeRTOS,
NVS and websocket-client objects are created without error; the sequencer
runs on the emulated chip; the transport's offline path paces itself.

## Still unverified — a board answers these

- The real I²C bus: `drv2605_i2c_esp32.c` compiles and links, but QEMU boots
  the mock, so no `i2c_master` transaction has executed. Mux wiring, pins,
  pull-ups, the TCA9548A reset pin: `docs/HARDWARE_BRINGUP.md`.
- Real motors (the feel — ladder rung H).
- Real Wi-Fi and a live relay: the station code path and the websocket adapter
  are compiled but have never carried a frame; `hello`/`hello.ack` over TLS
  against the running relay is the first thing to watch on a devkit.
- Timing on silicon: the ramp-up's HAP deltas under QEMU wall-clock mode show
  the tick-based wait in `play_boot_ramp` is good to a tick (the rung-1 app
  moved to an `esp_timer` wake for rung 2's millisecond diff; the band's
  utterance timeline is driven by the turn and will want the same on a board
  if the diff is ever run there).
