/*
 * mock_drv2605.c — bench mock of the DRV2605L bus (tests only).
 *
 * The mux is modelled as the chip behaves: a control byte with exactly one
 * bit set routes the bus to that channel.  select_channel() encodes the
 * channel through tca9548_select_byte() and a write_reg() to TCA9548_ADDR
 * delivers a raw control byte; both land in mux_apply(), which refuses any
 * byte that is not exactly one set bit within the six channels.  The
 * accepted channel index is kept in mux_select (readable at
 * TCA9548_ADDR/0x00 as the control byte), and every subsequent DRV2605
 * read/write hits that channel's register file.
 */
#include "mock_drv2605.h"

/* The one place the mux contract is enforced.  Independent of the encoder
 * in drv2605_i2c.h on purpose: decoding here catches an encoder that
 * regresses to writing the channel number. */
static haptic_err_t mux_apply(mock_drv *m, uint8_t control)
{
    if (control == 0 || (control & (uint8_t) (control - 1)) != 0) {
        m->mux_rejects++;          /* zero or several bits: not one channel */
        return HAPTIC_ERR_IO;
    }
    uint8_t ch = 0;
    while ((control >> ch) != 1u) { ch++; }
    if (ch >= DRV2605_DOT_COUNT) {
        m->mux_rejects++;          /* a bit past the last wired channel */
        return HAPTIC_ERR_IO;
    }
    m->mux_select = ch;
    return HAPTIC_OK;
}

static haptic_err_t mock_select(void *ctx, uint8_t ch)
{
    if (ch >= DRV2605_DOT_COUNT) { return HAPTIC_ERR_INVALID_ARG; }
    mock_drv *m = (mock_drv *) ctx;
    return mux_apply(m, tca9548_select_byte(ch));
}

static haptic_err_t mock_read(void *ctx, uint8_t addr, uint8_t reg, uint8_t *val)
{
    mock_drv *m = (mock_drv *) ctx;
    if (m->fault_ch >= 0 && (int) m->mux_select == m->fault_ch && (int) reg == m->fault_reg) {
        return HAPTIC_ERR_IO;
    }
    if (addr == TCA9548_ADDR) {
        *val = mock_mux_control_byte(m);   /* the chip reads back its control byte */
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
        if (reg != TCA9548_REG_SELECT) { return HAPTIC_ERR_IO; }
        return mux_apply(m, val);   /* a raw control byte: must be exactly one set bit */
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
    m->mux_rejects = 0;
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

uint8_t mock_mux_control_byte(const mock_drv *m)
{
    return (uint8_t) (1u << m->mux_select);
}