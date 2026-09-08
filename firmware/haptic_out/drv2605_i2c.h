/*
 * drv2605_i2c.h — bus abstraction for the haptic_out module.
 *
 * The DRV2605L has a fixed I2C address (0x5A), so the six dot-channels
 * (one per braille dot) sit behind an I2C mux (TCA9548A at 0x70).  The
 * sequencer and register-level driver are written against this vtable and
 * compile unchanged on the bench (mock bus) and on the band (ESP-IDF I2C).
 *
 * Register names follow the Adafruit DRV2605 library map (verified against
 * the datasheet memory map; see README.md for the reference).
 */
#ifndef DRV2605_I2C_H
#define DRV2605_I2C_H

#include <stdint.h>

/* Module-wide error codes (host-portable — no ESP-IDF types in this layer). */
typedef enum {
    HAPTIC_OK = 0,
    HAPTIC_ERR_INVALID_ARG,   /* bad mark/pattern index, non-letter in a word */
    HAPTIC_ERR_TOO_LONG,      /* word exceeds HAPTIC_OUT_MAX_WORD_LEN */
    HAPTIC_ERR_IO,            /* bus write/read failed (mock: injected fault) */
    HAPTIC_ERR_ABORTED        /* playback cancelled by haptic_out_stop() */
} haptic_err_t;

/* --- DRV2605L device --- */
#define DRV2605_ADDR            0x5A   /* fixed by the chip, hence the mux */
#define DRV2605_REG_STATUS      0x00
#define DRV2605_REG_MODE        0x01
#define DRV2605_MODE_REALTIME   0x05   /* real-time playback: RTPIN = drive */
#define DRV2605_REG_RTPIN       0x02   /* real-time playback input (0..127) */
#define DRV2605_REG_RATEDV      0x16
#define DRV2605_REG_CLAMPV      0x17
#define DRV2605_REG_FEEDBACK    0x1A   /* bit 5 = LRA actuator mode */

/* --- TCA9548A I2C mux --- */
#define TCA9548_ADDR            0x70
#define TCA9548_REG_SELECT      0x00   /* bit n enables channel n */

#define DRV2605_DOT_COUNT       6      /* braille dots 1..6, channels 0..5 */

/* One dot channel = one DRV2605L behind the mux. */
typedef struct {
    haptic_err_t (*select_channel)(void *ctx, uint8_t ch);          /* mux to channel 0..5 */
    haptic_err_t (*read_reg)(void *ctx, uint8_t addr, uint8_t reg, uint8_t *val);
    haptic_err_t (*write_reg)(void *ctx, uint8_t addr, uint8_t reg, uint8_t val);
    void *ctx;
} drv2605_bus;

#endif /* DRV2605_I2C_H */