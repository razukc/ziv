# haptic_out — ESP-IDF component (plan §5).
#
# Device build: the module + driver + FreeRTOS task.  The mock and the
# bench tests are intentionally excluded — they build with a host C
# compiler via run_tests.py, never on-device.
#
# TODO(on hardware): pick the ESP-IDF I2C driver flavour in
# drv2605_i2c_esp32.c and add the component to the app's main CMakeLists.

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