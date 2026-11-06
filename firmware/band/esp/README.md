# firmware/band/esp — the band's ESP-IDF glue (UNVERIFIED)

Everything in this directory is written against the **ESP-IDF 5.x** APIs
(`esp_websocket_client`, `nvs_flash`, `esp_wifi`, `esp_timer`, FreeRTOS)
and is **not compiled here**: no ESP-IDF is installed where the band
module was written, so these files have never been through `idf.py build`.
Every one of them is under `#if defined(ESP_PLATFORM)` (or excluded from
host builds by never being listed in a host build), so the host proofs in
`../run_band_tests.py` cannot be affected by them, and the first board
build will surface whatever this directory gets wrong. Expect to fix
includes, Kconfig symbol names and the websocket event enum spellings
against the IDF version you install.

| File | Role |
|---|---|
| `band_main.c` | `app_main`: NVS, Wi-Fi station, the I²C bus (`drv2605_bus_esp32_init`), the sequencer, the turn, the queue (NVS store, loaded at boot), the transport (websocket adapter), the pull-model loop task, HAP log lines on the UART |
| `transport_ws_esp.c` | the `band_frame_io` adapter on `esp_websocket_client`: text frames in a FreeRTOS queue, blocking `recv_frame` with a timeout, `hello` goes out as the first frame (never a key in the URL) |
| `queue_nvs_esp.c` | the `band_queue_store` adapter on NVS: one blob under namespace `ziv`, key `queue` |
| `CMakeLists.txt` | the IDF component: the band sources, the haptic_out sources and the ESP bus; `json` is IDF's own cJSON (the host builds the vendored copy in `firmware/third_party/cJSON`) |
| `idf_component.yml` | the component manifest: `espressif/esp_websocket_client` from the component registry |
| `Kconfig` | `menuconfig` → "Ziv band": Wi-Fi credentials, the relay URI, the device key, the profile, the I²C pins |

## Building (when an IDF is at hand)

Any IDF project can pull this in as an extra component; the smallest is:

```cmake
# <somewhere>/ziv_band/CMakeLists.txt
cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS "<repo>/firmware/band/esp")
set(COMPONENTS esp)         # this directory IS the component (IDF names it after the folder)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ziv_band)
```

```sh
idf.py set-target esp32s3
idf.py menuconfig            # Ziv band → SSID, password, relay URI (wss://…/ws), device key
idf.py build flash monitor
```

`app_main` lives in `band_main.c`, so the project needs no `main/`.

## What the host already proved

The band logic this glue wires up — the decoder, the queue image, the turn,
the protocol, the backoff — is the code `../run_band_tests.py` runs on the
host (unit tests, the conformance player on both profiles, the transport
over loopback against `../host/fake_relay.py`). The adapters here are thin
on purpose: the websocket does the framing, NVS stores one blob, and the
loop is `transport_step` → `transport_wait`, the same pull model as the
bench and the rung-1 app. What a board adds is the radio, the real clock
and the real motors (ladder rungs 3–H in `docs/QEMU_SIMULATION_LADDER.md`).
