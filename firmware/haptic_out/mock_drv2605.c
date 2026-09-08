/*
 * mock_drv2605.c — bench mock of the DRV2605L bus (tests only).
 *
 * The mux is implicit in the register addressing: select_channel() stores
 * the channel in mux_select (visible at TCA9548_ADDR/0x00), and every
 * subsequent DRV2605 read/write hits that channel's register file.
 */
#include "mock_drv2605.h"

static haptic_err_t mock_select(void *ctx, uint8_t ch)
{
    if (ch >= DRV2605_DOT_COUNT) { return HAPTIC_ERR_INVALID_ARG; }
    mock_drv *m = (mock_drv *) ctx;
    m->mux_select = ch;
    return HAPTIC_OK;
}

static haptic_err_t mock_read(void *ctx, uint8_t addr, uint8_t reg, uint8_t *val)
{
    mock_drv *m = (mock_drv *) ctx;
    if (m->fault_ch >= 0 && (int) m->mux_select == m->fault_ch && (int) reg == m->fault_reg) {
        return HAPTIC_ERR_IO;
    }
    if (addr == TCA9548_ADDR) {
        *val = m->mux_select;
        return HAPTIC_OK;
    }
    if (addr != DRV2605_ADDR) { return HAPTIC_ERR_IO; }
    *val = m->regs[m->mux_select][reg];
    return HAPTIC_OK;
}

static haptic_err_t mock_write(void *ctx, uint8_t addr, uint8_t reg, uint8_t val)
{
    mock_drv *m = (mock_drv *) ctx;
    if (m->fault_ch >= 0 && (int) m->mux_select == m->fault_ch && (int) reg == m->fault_reg) {
        return HAPTIC_ERR_IO;
    }
    if (addr == TCA9548_ADDR) {
        return HAPTIC_ERR_IO;   /* the mux is not writable in this mock */
    }
    if (addr != DRV2605_ADDR) { return HAPTIC_ERR_IO; }
    m->regs[m->mux_select][reg] = val;
    m->writes++;
    return HAPTIC_OK;
}

void mock_init(mock_drv *m)
{
    for (int ch = 0; ch < DRV2605_DOT_COUNT; ch++) {
        for (int r = 0; r < 256; r++) { m->regs[ch][r] = 0; }
    }
    m->mux_select = 0;
    m->fault_ch = -1;
    m->fault_reg = -1;
    m->writes = 0;
}

void mock_fault(mock_drv *m, int ch, int reg)
{
    m->fault_ch = ch;
    m->fault_reg = reg;
}

void mock_clear_fault(mock_drv *m)
{
    m->fault_ch = -1;
    m->fault_reg = -1;
}

void mock_bus(drv2605_bus *bus, mock_drv *m)
{
    bus->select_channel = mock_select;
    bus->read_reg = mock_read;
    bus->write_reg = mock_write;
    bus->ctx = m;
}

uint8_t mock_drive(const mock_drv *m, uint8_t ch)
{
    return m->regs[ch][DRV2605_REG_RTPIN];
}