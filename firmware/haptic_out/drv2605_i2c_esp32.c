/*
 * drv2605_i2c_esp32.c — ESP-IDF I2C bus for the haptic_out module.
 *
 * UNVERIFIED ON HARDWARE (no ESP-IDF where this was written): implements
 * the drv2605_bus vtable over the ESP-IDF 5.x driver/i2c_master API so the
 * bench-tested sequencer runs unchanged on the band.  The legacy
 * driver/i2c.h calls (i2c_master_write_to_device) are gone: that API is
 * deprecated in IDF 5 and gets removed in 6.
 *
 * The six DRV2605L share address 0x5A, so each dot access is:
 *   1. select the channel on the TCA9548A — ONE control byte, a bitmask:
 *      tca9548_select_byte(ch) == 1 << ch (drv2605_i2c.h).  The earlier
 *      sketch wrote the raw channel number, which selects the wrong dot
 *      (or, for channel 0, nothing); the bench mock now refuses that.
 *   2. read/write that channel's DRV2605 register through the one shared
 *      device handle at 0x5A.
 *
 * Only the select byte is cached: the mux keeps its control register, so a
 * repeated select of the same channel is skipped (12 transactions per cell
 * edge become 7 — HARDWARE_BRINGUP.md §4 stage C).
 *
 * TODO(on hardware): confirm the mux channel wiring (dot 1 = channel 0 …
 * dot 6 = channel 5), the pins (bring-up default SDA 8 / SCL 9) and whether
 * the TCA9548A needs its RESET pin held high on your breakout.
 */
#include "drv2605_i2c_esp32.h"

#if defined(ESP_PLATFORM)
#include "driver/i2c_master.h"
#include "esp_err.h"

#define ESP32_I2C_TIMEOUT_MS  50   /* bus transaction timeout; not a haptic duration */

static i2c_master_bus_handle_t s_bus;
static i2c_master_dev_handle_t s_mux;    /* TCA9548A */
static i2c_master_dev_handle_t s_drv;    /* the shared DRV2605L address behind the mux */
static int s_selected = -1;              /* mux channel currently routed; -1 = unknown */
#endif

static haptic_err_t esp32_select(void *ctx, uint8_t ch)
{
    (void) ctx;
    if (ch >= DRV2605_DOT_COUNT) { return HAPTIC_ERR_INVALID_ARG; }
#if defined(ESP_PLATFORM)
    if (s_selected == (int) ch) { return HAPTIC_OK; }
    uint8_t control = tca9548_select_byte(ch);   /* bit n enables channel n */
    if (i2c_master_transmit(s_mux, &control, 1, ESP32_I2C_TIMEOUT_MS) != ESP_OK) {
        s_selected = -1;
        return HAPTIC_ERR_IO;
    }
    s_selected = (int) ch;
#endif
    return HAPTIC_OK;
}

static haptic_err_t esp32_read(void *ctx, uint8_t addr, uint8_t reg, uint8_t *val)
{
    (void) ctx;
#if defined(ESP_PLATFORM)
    i2c_master_dev_handle_t dev = (addr == TCA9548_ADDR) ? s_mux : s_drv;
    if (addr != TCA9548_ADDR && addr != DRV2605_ADDR) { return HAPTIC_ERR_IO; }
    if (addr == TCA9548_ADDR) {
        /* the mux has one register and no register address byte */
        if (i2c_master_receive(dev, val, 1, ESP32_I2C_TIMEOUT_MS) != ESP_OK) { return HAPTIC_ERR_IO; }
        return HAPTIC_OK;
    }
    if (i2c_master_transmit_receive(dev, &reg, 1, val, 1, ESP32_I2C_TIMEOUT_MS) != ESP_OK) {
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
    if (addr == TCA9548_ADDR) {
        /* a raw control byte: the mux has one register and no address byte */
        if (reg != TCA9548_REG_SELECT) { return HAPTIC_ERR_IO; }
        if (i2c_master_transmit(s_mux, &val, 1, ESP32_I2C_TIMEOUT_MS) != ESP_OK) {
            s_selected = -1;
            return HAPTIC_ERR_IO;
        }
        s_selected = -1;   /* the caller chose the byte; forget the cache */
        return HAPTIC_OK;
    }
    if (addr != DRV2605_ADDR) { return HAPTIC_ERR_IO; }
    uint8_t buf[2] = { reg, val };
    if (i2c_master_transmit(s_drv, buf, 2, ESP32_I2C_TIMEOUT_MS) != ESP_OK) {
        return HAPTIC_ERR_IO;
    }
#else
    (void) addr; (void) reg; (void) val;
#endif
    return HAPTIC_OK;
}

void drv2605_bus_esp32(drv2605_bus *bus)
{
    bus->select_channel = esp32_select;
    bus->read_reg = esp32_read;
    bus->write_reg = esp32_write;
    bus->ctx = NULL;
}

haptic_err_t drv2605_bus_esp32_init(drv2605_bus *bus, const drv2605_esp32_pins *pins)
{
#if defined(ESP_PLATFORM)
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = pins->port,
        .sda_io_num = pins->sda_gpio,
        .scl_io_num = pins->scl_gpio,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,   /* breakouts carry their own; harmless */
    };
    if (i2c_new_master_bus(&bus_cfg, &s_bus) != ESP_OK) { return HAPTIC_ERR_IO; }

    i2c_device_config_t mux_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = TCA9548_ADDR,
        .scl_speed_hz = pins->scl_hz,
    };
    if (i2c_master_bus_add_device(s_bus, &mux_cfg, &s_mux) != ESP_OK) { return HAPTIC_ERR_IO; }

    i2c_device_config_t drv_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = DRV2605_ADDR,
        .scl_speed_hz = pins->scl_hz,
    };
    if (i2c_master_bus_add_device(s_bus, &drv_cfg, &s_drv) != ESP_OK) { return HAPTIC_ERR_IO; }
    s_selected = -1;
#else
    (void) pins;
#endif
    drv2605_bus_esp32(bus);
    return HAPTIC_OK;
}
