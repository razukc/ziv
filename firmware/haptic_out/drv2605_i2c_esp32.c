/*
 * drv2605_i2c_esp32.c — ESP-IDF I2C bus for the haptic_out module.
 *
 * Sketch (not yet compiled on-device): implements the drv2605_bus vtable
 * over the ESP-IDF I2C driver so the bench-tested sequencer code runs
 * unchanged on the band.  Wire the driver first:
 *
 *     idf.py menuconfig -> Component config -> ESP I2C driver
 *     (I2C_PORT=0, I2C_MAIN_BUS_ENABLE=y), or use the legacy
 *     driver/i2c API (i2c_master_write_to_device / read_from_device).
 *
 * The six DRV2605L share address 0x5A, so each dot access is:
 *   1. select the channel on the TCA9548A (address 0x70, register 0x00)
 *   2. read/write that channel's DRV2605 register
 *
 * TODO(on hardware): choose the I2C driver flavour (new i2c_master vs
 * legacy), set the I2C port / SDA-SCL gpio in the component config, and
 * confirm the mux channel wiring (dot 1 = channel 0, ... dot 6 = channel 5).
 */
#include "drv2605_i2c.h"

#if defined(ESP_PLATFORM)
#include "driver/i2c.h"   /* ESP-IDF >= 5.x I2C driver (sketch) */
#endif

#define I2C_PORT 0

static haptic_err_t esp32_select(void *ctx, uint8_t ch)
{
    (void) ctx;
    if (ch >= DRV2605_DOT_COUNT) { return HAPTIC_ERR_INVALID_ARG; }
#if defined(ESP_PLATFORM)
    /* TCA9548A: select register bit n = channel n. */
    if (i2c_master_write_to_device(I2C_PORT, TCA9548_ADDR, &ch, 1) != ESP_OK) {
        return HAPTIC_ERR_IO;
    }
#else
    (void) ch;
#endif
    return HAPTIC_OK;
}

static haptic_err_t esp32_read(void *ctx, uint8_t addr, uint8_t reg, uint8_t *val)
{
    (void) ctx;
#if defined(ESP_PLATFORM)
    if (i2c_master_read_from_device(I2C_PORT, addr, &reg, 1, val, 1) != ESP_OK) {
        return HAPTIC_ERR_IO;
    }
#else
    (void) addr; (void) reg; (void) val;
#endif
    return HAPTIC_OK;
}

static haptic_err_t esp32_write(void *ctx, uint8_t addr, uint8_t reg, uint8_t val)
{
    (void) ctx;
#if defined(ESP_PLATFORM)
    uint8_t buf[2] = { reg, val };
    if (i2c_master_write_to_device(I2C_PORT, addr, buf, 2) != ESP_OK) {
        return HAPTIC_ERR_IO;
    }
#else
    (void) addr; (void) reg; (void) val;
#endif
    return HAPTIC_OK;
}

/* Build the bus for the band.  Call once at boot, then drv2605_init(). */
void drv2605_bus_esp32(drv2605_bus *bus)
{
    bus->select_channel = esp32_select;
    bus->read_reg = esp32_read;
    bus->write_reg = esp32_write;
    bus->ctx = NULL;
}