# haptic_out — ESP-IDF component (plan §5).
#
# Device build: the module + driver + FreeRTOS task.  The mock and the
# bench tests are intentionally excluded — they build with a host C
# compiler via run_tests.py, never on-device.
#
# drv2605_i2c_esp32.c uses driver/i2c_master.h (IDF 5.x; `driver` pulls in
# esp_driver_i2c on 5.3+).  UNVERIFIED: no IDF where this was written.
# The band app that links this component is firmware/band/esp.

idf_component_register(
    SRCS
        "haptic_out.c"
        "drv2605.c"
        "drv2605_i2c_esp32.c"
        "haptic_out_task.c"
    INCLUDE_DIRS "."
    REQUIRES
        freertos
        driver
)