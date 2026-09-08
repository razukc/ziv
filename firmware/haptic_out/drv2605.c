/*
 * drv2605.c — register-level DRV2605L driver.
 *
 * RTP mode: write level to RTPIN (0..127), the actuator runs at that level
 * until the register changes.  Silence = level 0.  Per-dot control rides on
 * the mux: select a channel, write its RTPIN.
 */
#include "drv2605.h"

haptic_err_t drv2605_set_mode(drv2605_bus *bus, uint8_t ch, uint8_t mode)
{
    haptic_err_t err = bus->select_channel(bus->ctx, ch);
    if (err != HAPTIC_OK) { return err; }
    return bus->write_reg(bus->ctx, DRV2605_ADDR, DRV2605_REG_MODE, mode);
}

haptic_err_t drv2605_init(drv2605_bus *bus)
{
    /* Rated voltage / clamp for a 2.4 ohm LRA (Adafruit 2305 defaults):
     * RATEDV 0x8E = 2.0 Vrms, CLAMPV 0x93 = 2.4 V.  Per-channel — an LRA's
     * resonance varies part to part, so the band calibrates per dot later. */
    static const uint8_t ratedv = 0x8E, clampv = 0x93;

    for (uint8_t ch = 0; ch < DRV2605_DOT_COUNT; ch++) {
        haptic_err_t err = drv2605_set_mode(bus, ch, DRV2605_MODE_REALTIME);
        if (err != HAPTIC_OK) { return err; }
        err = drv2605_set_lra(bus, ch);
        if (err != HAPTIC_OK) { return err; }
        err = drv2605_set_ratedv(bus, ch, ratedv);
        if (err != HAPTIC_OK) { return err; }
        err = drv2605_set_clampv(bus, ch, clampv);
        if (err != HAPTIC_OK) { return err; }
        err = drv2605_set_drive(bus, ch, 0);   /* start silent */
        if (err != HAPTIC_OK) { return err; }
    }
    return HAPTIC_OK;
}

haptic_err_t drv2605_set_drive(drv2605_bus *bus, uint8_t ch, uint8_t level)
{
    if (level > 127) { return HAPTIC_ERR_INVALID_ARG; }
    haptic_err_t err = bus->select_channel(bus->ctx, ch);
    if (err != HAPTIC_OK) { return err; }
    return bus->write_reg(bus->ctx, DRV2605_ADDR, DRV2605_REG_RTPIN, level);
}

haptic_err_t drv2605_set_all(drv2605_bus *bus, uint8_t level)
{
    for (uint8_t ch = 0; ch < DRV2605_DOT_COUNT; ch++) {
        haptic_err_t err = drv2605_set_drive(bus, ch, level);
        if (err != HAPTIC_OK) { return err; }
    }
    return HAPTIC_OK;
}

haptic_err_t drv2605_set_ratedv(drv2605_bus *bus, uint8_t ch, uint8_t ratedv)
{
    haptic_err_t err = bus->select_channel(bus->ctx, ch);
    if (err != HAPTIC_OK) { return err; }
    return bus->write_reg(bus->ctx, DRV2605_ADDR, DRV2605_REG_RATEDV, ratedv);
}

haptic_err_t drv2605_set_clampv(drv2605_bus *bus, uint8_t ch, uint8_t clampv)
{
    haptic_err_t err = bus->select_channel(bus->ctx, ch);
    if (err != HAPTIC_OK) { return err; }
    return bus->write_reg(bus->ctx, DRV2605_ADDR, DRV2605_REG_CLAMPV, clampv);
}

haptic_err_t drv2605_set_lra(drv2605_bus *bus, uint8_t ch)
{
    haptic_err_t err = bus->select_channel(bus->ctx, ch);
    if (err != HAPTIC_OK) { return err; }
    uint8_t fb = 0;
    err = bus->read_reg(bus->ctx, DRV2605_ADDR, DRV2605_REG_FEEDBACK, &fb);
    if (err != HAPTIC_OK) { return err; }
    fb |= (1u << 5);   /* bit 5: 1 = LRA, 0 = ERM */
    return bus->write_reg(bus->ctx, DRV2605_ADDR, DRV2605_REG_FEEDBACK, fb);
}

haptic_err_t drv2605_stop_all(drv2605_bus *bus)
{
    return drv2605_set_all(bus, 0);
}
