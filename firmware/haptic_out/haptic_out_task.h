/*
 * haptic_out_task.h — FreeRTOS task owning the haptic_out state machine.
 *
 * Device-only (FreeRTOS); the host never includes this.  See the .c file.
 */
#ifndef HAPTIC_OUT_TASK_H
#define HAPTIC_OUT_TASK_H

#include <stdint.h>
#include "drv2605_i2c.h"

/* Create the command queue and the task; drv2605_init() runs here. */
void haptic_out_task_init(drv2605_bus *bus);

/* App-side helpers (post-and-forget; a full queue drops the command). */
void haptic_post_mark(uint8_t mark_idx);
void haptic_post_pattern(uint8_t pattern_idx);
void haptic_post_word(const char *word);        /* a-z, up to HAPTIC_OUT_MAX_WORD_LEN letters */
void haptic_post_prefix(uint8_t tail_idx);
void haptic_post_pace(uint32_t cell_gap_ms);    /* clamped to the spec envelope by the sequencer */
void haptic_post_stop(void);

#endif /* HAPTIC_OUT_TASK_H */
