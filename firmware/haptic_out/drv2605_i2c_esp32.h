/*
 * drv2605_i2c_esp32.h — the band's I2C bus (ESP-IDF 5.x driver/i2c_master).
 *
 * UNVERIFIED ON HARDWARE: written against the ESP-IDF 5.x i2c_master API
 * (i2c_new_master_bus / i2c_master_bus_add_device / i2c_master_transmit /
 * i2c_master_transmit_receive) but no ESP-IDF is installed where this was
 * written, so the device path has not been compiled.  Everything ESP-IDF
 * is under #if defined(ESP_PLATFORM); the host build sees only stubs.
 */
#ifndef DRV2605_I2C_ESP32_H
#define DRV2605_I2C_ESP32_H

#include <stdint.h>
#include "drv2605_i2c.h"

/* Pins and clock for the band's bus (HARDWARE_BRINGUP.md §2 wiring). */
typedef struct {
    int port;          /* I2C controller: 0 or 1 */
    int sda_gpio;      /* bring-up default: 8 */
    int scl_gpio;      /* bring-up default: 9 */
    uint32_t scl_hz;   /* 100000 to start; 400000 if cell edges smear (§4 stage C) */
} drv2605_esp32_pins;

/* Create the master bus, the mux device handle (TCA9548_ADDR) and the one
 * shared DRV2605 device handle (DRV2605_ADDR — the six drivers share the
 * address behind the mux), then fill the vtable.  Call once at boot, then
 * drv2605_init().  Returns HAPTIC_OK or HAPTIC_ERR_IO. */
haptic_err_t drv2605_bus_esp32_init(drv2605_bus *bus, const drv2605_esp32_pins *pins);

/* Fill the vtable only (the bus must already be initialised).  Kept for the
 * bring-up doc's app_main sketch. */
void drv2605_bus_esp32(drv2605_bus *bus);

#endif /* DRV2605_I2C_ESP32_H */
