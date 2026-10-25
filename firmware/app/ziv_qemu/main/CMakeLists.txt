# ziv_qemu — QEMU ladder rung 1 (docs/QEMU_SIMULATION_LADDER.md).
#
# The haptic backend is the BENCH MOCK BUS reused verbatim: haptic_out's own
# sources and mock_drv2605.c are compiled into this component — one bus
# implementation shared by bench, QEMU, and the host tests (run_ziv_tests.py).
# The real ESP-IDF I2C bus (drv2605_i2c_esp32.c) replaces the mock only at
# hardware bring-up (ladder rung H).
#
# No esp_wifi and no I2S driver are linked on purpose: WiFi and the mic
# return at ladder rungs 3-4 behind their vtables.
idf_component_register(
    SRCS "ziv_demo_sequence.c"
         "ziv_app.c"
         "app_main.c"
         "../../haptic_out/haptic_out.c"
         "../../haptic_out/drv2605.c"
         "../../haptic_out/mock_drv2605.c"
    INCLUDE_DIRS "."
                 "../../haptic_out"
)
