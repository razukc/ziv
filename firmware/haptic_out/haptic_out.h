/*
 * haptic_out.h — public API of the haptic_out module (plan §5).
 *
 * Five playback surfaces, all driven by the generated timing tables
 * (haptic_timing.h) so the band plays exactly what the phone mock plays:
 *
 *   haptic_out_play_mark(mi)      a candidate name mark (protocol §0)
 *   haptic_out_play_pattern(pi)   an attention pattern (plan §4)
 *   haptic_out_play_word(word)    any word, spelled one cell per letter
 *   haptic_out_play_prefix(tail)  mark → PREFIX_BREATH_MS → attention tail
 *   haptic_out_play_beats(b, n)   any compiled timeline: a caller-owned list
 *                                 of {dot_mask, buzz_ms, gap_after_ms} beats
 *                                 (the band's turn module compiles an
 *                                 utterance segment into one of these)
 *
 * The silence between cells inside MARK / WORD / PREFIX plays is the
 * wearer's pace: a runtime variable, haptic_out_set_cell_gap_ms(), clamped
 * to the spec envelope [CELL_GAP_MIN_MS, CELL_GAP_MAX_MS] and defaulting to
 * CELL_GAP_DEFAULT_MS.  A beat list carries its own gaps.
 *
 * Pull model: the caller drives haptic_out_step() with the monotonic time
 * and gets back the next deadline.  On the band the FreeRTOS task
 * (haptic_out_task.c) owns the loop; on the bench the test harness drives
 * it against a virtual clock — identical code path.  The bus writes inside
 * haptic_out_step() (dots up at buzz start, all silent at buzz end) are the
 * only I/O; there is no blocking and no sleeping in this layer.
 *
 * Every play ends with TAIL_GAP_MS of silence before the END event — the
 * spec's "silence after a pattern's last beat" — so back-to-back plays
 * never merge, matching the phone feel-tool's cadence.
 *
 * Host-portable: no ESP-IDF types in this layer.
 */
#ifndef HAPTIC_OUT_H
#define HAPTIC_OUT_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include "drv2605_i2c.h"
#include "haptic_timing.h"

#define HAPTIC_OUT_MAX_WORD_LEN 16

typedef enum {
    HAPTIC_OUT_MODE_IDLE,
    HAPTIC_OUT_MODE_MARK,
    HAPTIC_OUT_MODE_PATTERN,
    HAPTIC_OUT_MODE_WORD,
    HAPTIC_OUT_MODE_PREFIX,
    HAPTIC_OUT_MODE_BEATS       /* a caller-compiled beat list (haptic_out_play_beats) */
} haptic_out_mode_t;

/* One beat of a compiled timeline: the dots up (bit n = dot n+1, 0 = a
 * whole-device pattern beat), how long they buzz, and the silence after.
 * The caller owns the array for the whole play (until END or stop). */
typedef struct {
    uint8_t dot_mask;
    uint16_t buzz_ms;
    uint16_t gap_after_ms;
} haptic_beat_ex;

typedef enum {
    HAPTIC_OUT_EV_START,
    HAPTIC_OUT_EV_BUZZ,     /* a beat (or cell) started */
    HAPTIC_OUT_EV_END
} haptic_out_event_t;

/* One step of the timeline, as delivered with HAPTIC_OUT_EV_BUZZ. */
typedef struct {
    haptic_out_mode_t mode;
    uint32_t buzz_ms;
    uint32_t gap_after_ms;
    uint8_t dot_mask;       /* which dots are up during this buzz (0 = none) */
    uint16_t seq;           /* 0-based beat index within the play */
} haptic_out_step_t;

/* The module drives the bus; the app drives the module. */
typedef struct {
    drv2605_bus *bus;
    haptic_out_mode_t mode;
    uint16_t step_idx;
    uint8_t cur_dot_mask;
    uint8_t word[HAPTIC_OUT_MAX_WORD_LEN];
    uint8_t word_len;
    uint8_t mark_idx;
    haptic_pattern pat;
    haptic_tail tail;
    const haptic_beat_ex *beats;   /* BEATS mode: the caller's list */
    uint16_t beats_len;
    uint16_t cell_gap_ms;   /* the pace: silence between cells (MARK/WORD/PREFIX) */
    bool playing;
    bool started;           /* START event delivered */
    bool buzzing;           /* dots are up until next_deadline */
    bool draining;          /* beats exhausted; trailing silence then END */
    uint32_t last_gap_ms;   /* gap_after of the most recent buzz (the last one = the tail gap) */
    uint32_t next_deadline; /* monotonic ms of the next state change */
    haptic_err_t last_err;
} haptic_out;

void haptic_out_init(haptic_out *h, drv2605_bus *bus);

haptic_err_t haptic_out_play_mark(haptic_out *h, uint8_t mark_idx);
haptic_err_t haptic_out_play_pattern(haptic_out *h, haptic_pattern pat);
haptic_err_t haptic_out_play_word(haptic_out *h, const char *word);   /* a-z only */
haptic_err_t haptic_out_play_prefix(haptic_out *h, haptic_tail tail);

/* Play a caller-compiled beat list.  beats must stay valid until the END
 * event (or haptic_out_stop); n must be >= 1.  Each beat is one BUZZ event
 * with that beat's mask and durations, so the HAP log and the step model
 * are unchanged.  The last beat's gap_after_ms is the trailing silence
 * before END, exactly as a play's tail gap is. */
haptic_err_t haptic_out_play_beats(haptic_out *h, const haptic_beat_ex *beats, uint16_t n);

/* The pace: silence between cells inside a mark, word or prefix play.
 * Clamped into [CELL_GAP_MIN_MS, CELL_GAP_MAX_MS]; haptic_out_init() sets
 * CELL_GAP_DEFAULT_MS.  Takes effect from the next cell boundary.  Returns
 * the value actually set. */
uint16_t haptic_out_set_cell_gap_ms(haptic_out *h, uint32_t ms);
uint16_t haptic_out_cell_gap_ms(const haptic_out *h);

/* Advance the timeline.  now_ms is the current monotonic time in ms.
 * Returns the monotonic time of the next state change: call again at (or
 * after) that time.  Returns 0 when the play has finished — the END event
 * was delivered (or nothing was playing).  ev and step are written only
 * when an event fires.  Starting a new play cancels the current one. */
uint32_t haptic_out_step(haptic_out *h, uint32_t now_ms, haptic_out_event_t *ev, haptic_out_step_t *step);

/* Immediately silence every dot and drop the current play. */
void haptic_out_stop(haptic_out *h);

/* Read-only accessors (for tests / status). */
bool haptic_out_is_playing(const haptic_out *h);
uint16_t haptic_out_beat_index(const haptic_out *h);
haptic_out_mode_t haptic_out_mode(const haptic_out *h);

#endif /* HAPTIC_OUT_H */