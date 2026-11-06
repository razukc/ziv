# firmware/band/esp — the band firmware as one ESP-IDF component (UNVERIFIED:
# written against ESP-IDF 5.x, not built here — see README.md).
#
# The band sources and the haptic_out sequencer are compiled from their own
# directories (the same files the host proofs build), plus the three ESP
# adapters in this directory.  The mock bus and every host/ file are
# excluded: on the band the real I2C bus (drv2605_i2c_esp32.c) drives the
# six DRV2605L.  cJSON comes from IDF's `json` component, not the vendored
# host copy.
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
