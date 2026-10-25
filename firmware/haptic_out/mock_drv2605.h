/*
 * mock_drv2605.h — bench mock of the DRV2605L bus (tests only).
 *
 * Emulates six DRV2605L devices behind a TCA9548A mux exactly as the band
 * wires them: each dot channel has its own 256-byte register file, and the
 * mux select register decides which file the next read/write touches.
 * RTP semantics: writing RTPIN sets the actuator drive level (0..127),
 * which the test reads back to assert what the wearer would feel.
 *
 * Fault injection: mock_fault(ch, reg) makes the next bus call on that
 * channel/register fail with HAPTIC_ERR_IO, so the sequencer's error path
 * is testable without hardware.
 */
#ifndef MOCK_DRV2605_H
#define MOCK_DRV2605_H

#include <stdint.h>
#include "drv2605_i2c.h"

typedef struct {
    uint8_t regs[DRV2605_DOT_COUNT][256];   /* per-channel register files */
    uint8_t mux_select;                     /* TCA9548A select register */
    int16_t fault_ch;                       /* -1 = no fault */
    int16_t fault_reg;
    uint32_t writes;                        /* count of bus writes (sanity) */
} mock_drv;

void mock_init(mock_drv *m);
void mock_fault(mock_drv *m, int ch, int reg);   /* ch or reg = -1 disables */
void mock_clear_fault(mock_drv *m);

/* Build the drv2605_bus vtable on top of a mock. */
void mock_bus(drv2605_bus *bus, mock_drv *m);

/* Convenience: the drive level (RTPIN) of one dot channel. */
uint8_t mock_drive(const mock_drv *m, uint8_t ch);

#endif /* MOCK_DRV2605_H */