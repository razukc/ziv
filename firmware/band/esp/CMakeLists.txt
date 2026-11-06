# firmware/band/esp — the band firmware as one ESP-IDF component.
#
# Compiled against ESP-IDF v5.5 (esp32s3) from firmware/band/esp_project and
# booted under Espressif QEMU with the mock bus and no radio; a real board,
# real motors and real Wi-Fi are still unverified — see README.md.
#
# The band sources and the haptic_out sequencer are compiled from their own
# directories (the same files the host proofs build), plus the three ESP
# adapters in this directory.  Both haptic buses are compiled — the real I2C
# bus (drv2605_i2c_esp32.c) and the bench mock (mock_drv2605.c) — and
# CONFIG_ZIV_BAND_HAPTIC_MOCK picks which one band_main.c wires up, so the
# device path is type-checked on every build even when QEMU boots the mock.
# haptic_out_task.c (the bring-up console surface, HARDWARE_BRINGUP.md §4) is
# compiled for the same reason although the band's utterance path goes
# through the turn, not that queue.  Every host/ file is excluded.  cJSON comes from IDF's `json` component, not
# the vendored host copy.
idf_component_register(
    SRCS
        "band_main.c"
        "transport_ws_esp.c"
        "queue_nvs_esp.c"
        "../utterance.c"
        "../turn.c"
        "../queue.c"
        "../transport.c"
        "../../haptic_out/haptic_out.c"
        "../../haptic_out/drv2605.c"
        "../../haptic_out/drv2605_i2c_esp32.c"
        "../../haptic_out/mock_drv2605.c"
        "../../haptic_out/haptic_out_task.c"
    INCLUDE_DIRS
        "."
        ".."
        "../../haptic_out"
    REQUIRES
        json
        nvs_flash
        esp_wifi
        esp_netif
        esp_event
        esp_timer
        driver
        freertos
        esp_websocket_client
)
# The host builds' zero-warning discipline (run_band_tests.py: -Wall -Wextra
# -Werror) applies to our sources on the device toolchain too; IDF's own
# components keep their own flags.  IDF's defaults add -Wno-unused-parameter
# and -Wno-sign-compare (explicit, so a later -Wextra does not undo them);
# the host enforces both, so they are switched back on here.
target_compile_options(${COMPONENT_LIB} PRIVATE
    -Wall -Wextra -Werror -Wunused-parameter -Wsign-compare)
