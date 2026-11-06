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
#
# Paths are relative to THIS directory (the component), not the project:
# main/ -> ziv_qemu/ -> app/ -> firmware/, hence three ../ to haptic_out.
# (The host runner's "../../haptic_out" is relative to the project dir.)
idf_component_register(
    SRCS "ziv_demo_sequence.c"
         "ziv_app.c"
         "app_main.c"
         "../../../haptic_out/haptic_out.c"
         "../../../haptic_out/drv2605.c"
         "../../../haptic_out/mock_drv2605.c"
    INCLUDE_DIRS "."
                 "../../../haptic_out"
    PRIV_REQUIRES esp_timer
)
# The host builds' zero-warning discipline (run_ziv_tests.py: -Wall -Wextra
# -Werror) applies to our sources on the device toolchain too; IDF's own
# components keep their own flags.  IDF's defaults add -Wno-unused-parameter
# and -Wno-sign-compare (explicit, so a later -Wextra does not undo them);
# the host enforces both, so they are switched back on here.
target_compile_options(${COMPONENT_LIB} PRIVATE
    -Wall -Wextra -Werror -Wunused-parameter -Wsign-compare)
