/*
 * drv2605.h — register-level DRV2605L driver (public API).
 *
 * Real-time playback (RTP) mode drives the actuator directly: write the
 * drive strength to RTPIN, the motor runs at that level until changed.
 * That is the right primitive for vibro-braille — one cell = ramp the six
 * channels to their levels, hold buzz_ms, ramp to zero, hold the gap —
 * and it sidesteps the 8-slot waveform sequencer entirely.
 *
 * Host-portable: compiles against the mock bus for bench tests and against
 * the ESP-IDF I2C bus on the band (see drv2605_i2c_esp32.c).
 */
#ifndef DRV2605_H
#define DRV2605_H

#include "drv2605_i2c.h"

/* RTP drive strength (0..127). 60 = ~1.2 Vrms into a 2.4 ohm LRA at
 * RATEDV 0x8E — a felt-but-comfortable default; tune per actuator. */
#define DRV2605_DRIVE_DEFAULT 60

haptic_err_t drv2605_init(drv2605_bus *bus);
haptic_err_t drv2605_set_drive(drv2605_bus *bus, uint8_t ch, uint8_t level);
haptic_err_t drv2605_set_all(drv2605_bus *bus, uint8_t level);
haptic_err_t drv2605_set_mode(drv2605_bus *bus, uint8_t ch, uint8_t mode);
haptic_err_t drv2605_set_ratedv(drv2605_bus *bus, uint8_t ch, uint8_t ratedv);
haptic_err_t drv2605_set_clampv(drv2605_bus *bus, uint8_t ch, uint8_t clampv);
haptic_err_t drv2605_set_lra(drv2605_bus *bus, uint8_t ch);
haptic_err_t drv2605_stop_all(drv2605_bus *bus);

#endif /* DRV2605_H */