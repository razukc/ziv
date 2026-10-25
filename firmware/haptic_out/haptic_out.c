/*
 * haptic_out.c — cell sequencer + pattern player (plan §5).
 *
 * Pull model: the caller drives haptic_out_step() with the monotonic time
 * and gets back the next deadline.  Each step owns the bus writes — dots up
 * at buzz start, all silent at buzz end — so the bench tests and the
 * FreeRTOS task exercise the identical code path.  All timings come from
 * the generated haptic_timing.h, so the band plays what the phone plays.
 *
 * State machine per play:
 *   (new play) -> START -> [BUZZ (dots up, deadline = +buzz_ms)
 *                           -> silence (deadline = +gap_ms)
 *                           -> next BUZZ | DRAIN (trailing silence)
 *                           -> END]*
 * Starting a new play cancels the current one (dots silenced first).
 */
#include "haptic_out.h"
#include "drv2605.h"

static uint8_t prefix_mark_len(void)
{
    return HAPTIC_MARK_LEN_TABLE[HAPTIC_PREFIX_MARK_INDEX];
}

static haptic_pattern prefix_tail_pattern(const haptic_out *h)
{
    return HAPTIC_PREFIX_TAIL_TABLE[h->tail];
}

/* Fill beat info for step_idx.  Returns false when the index is past the
 * end of the play (the caller enters the trailing-silence drain). */
static bool beat_info(const haptic_out *h, uint32_t *buzz_ms, uint32_t *gap_ms, uint8_t *mask)
{
    uint16_t i = h->step_idx;
    switch (h->mode) {
    case HAPTIC_OUT_MODE_MARK: {
        uint8_t len = HAPTIC_MARK_LEN_TABLE[h->mark_idx];
        if (i >= len) { return false; }
        uint8_t li = HAPTIC_MARK_TABLE[h->mark_idx][i];
        *buzz_ms = haptic_cell_ms((char) ('a' + li));
        *gap_ms = (i == len - 1) ? TAIL_GAP_MS : CELL_GAP_DEFAULT_MS;
        *mask = HAPTIC_LETTER_MASKS[li];
        return true;
    }
    case HAPTIC_OUT_MODE_PATTERN: {
        uint8_t len = HAPTIC_PATTERN_LEN_TABLE[h->pat];
        if (i >= len) { return false; }
        haptic_beat b = HAPTIC_PATTERN_TABLE[h->pat][i];
        *buzz_ms = b.buzz_ms;
        *gap_ms = b.gap_after_ms;
        *mask = 0;
        return true;
    }
    case HAPTIC_OUT_MODE_WORD: {
        if (i >= h->word_len) { return false; }
        uint8_t li = (uint8_t) (h->word[i] - 'a');
        *buzz_ms = haptic_cell_ms((char) ('a' + li));
        *gap_ms = (i == h->word_len - 1) ? TAIL_GAP_MS : CELL_GAP_DEFAULT_MS;
        *mask = HAPTIC_LETTER_MASKS[li];
        return true;
    }
    case HAPTIC_OUT_MODE_PREFIX: {
        uint8_t mark_len = prefix_mark_len();
        uint16_t total = (uint16_t) (mark_len + HAPTIC_PATTERN_LEN_TABLE[prefix_tail_pattern(h)]);
        if (i >= total) { return false; }
        if (i < mark_len) {
            uint8_t li = HAPTIC_MARK_TABLE[HAPTIC_PREFIX_MARK_INDEX][i];
            *buzz_ms = haptic_cell_ms((char) ('a' + li));
            *gap_ms = (i == mark_len - 1) ? PREFIX_BREATH_MS : CELL_GAP_DEFAULT_MS;
            *mask = HAPTIC_LETTER_MASKS[li];
        } else {
            haptic_beat b = HAPTIC_PATTERN_TABLE[prefix_tail_pattern(h)][i - mark_len];
            *buzz_ms = b.buzz_ms;
            *gap_ms = b.gap_after_ms;
            *mask = 0;
        }
        return true;
    }
    default:
        return false;
    }
}

void haptic_out_init(haptic_out *h, drv2605_bus *bus)
{
    h->bus = bus;
    h->mode = HAPTIC_OUT_MODE_IDLE;
    h->step_idx = 0;
    h->cur_dot_mask = 0;
    h->word_len = 0;
    h->mark_idx = 0;
    h->pat = (haptic_pattern) 0;
    h->tail = (haptic_tail) 0;
    h->playing = false;
    h->started = false;
    h->buzzing = false;
    h->draining = false;
    h->last_gap_ms = 0;
    h->next_deadline = 0;
    h->last_err = HAPTIC_OK;
}

void haptic_out_stop(haptic_out *h)
{
    if (h->playing) { h->last_err = HAPTIC_ERR_ABORTED; }
    h->playing = false;
    h->started = false;
    h->buzzing = false;
    h->draining = false;
    h->mode = HAPTIC_OUT_MODE_IDLE;
    h->step_idx = 0;
    h->cur_dot_mask = 0;
    (void) drv2605_stop_all(h->bus);   /* best-effort silence */
}

static haptic_err_t begin_play(haptic_out *h, haptic_out_mode_t mode)
{
    haptic_out_stop(h);   /* silences any current play */
    h->mode = mode;
    h->step_idx = 0;
    h->playing = true;
    h->started = false;
    h->buzzing = false;
    h->draining = false;
    h->last_gap_ms = 0;
    h->next_deadline = 0;   /* a new play must not inherit the old deadline */
    h->last_err = HAPTIC_OK;
    return HAPTIC_OK;
}

haptic_err_t haptic_out_play_mark(haptic_out *h, uint8_t mark_idx)
{
    if (mark_idx >= HAPTIC_MARK_COUNT) { return HAPTIC_ERR_INVALID_ARG; }
    h->mark_idx = mark_idx;
    return begin_play(h, HAPTIC_OUT_MODE_MARK);
}

haptic_err_t haptic_out_play_pattern(haptic_out *h, haptic_pattern pat)
{
    if ((uint8_t) pat >= HAPTIC_PAT_COUNT) { return HAPTIC_ERR_INVALID_ARG; }
    h->pat = pat;
    return begin_play(h, HAPTIC_OUT_MODE_PATTERN);
}

haptic_err_t haptic_out_play_word(haptic_out *h, const char *word)
{
    if (!word) { return HAPTIC_ERR_INVALID_ARG; }
    uint8_t n = 0;
    while (word[n] != '\0') {
        if (word[n] < 'a' || word[n] > 'z') { return HAPTIC_ERR_INVALID_ARG; }
        if (++n > HAPTIC_OUT_MAX_WORD_LEN) { return HAPTIC_ERR_TOO_LONG; }
    }
    if (n == 0) { return HAPTIC_ERR_INVALID_ARG; }
    h->word_len = n;
    for (uint8_t k = 0; k < n; k++) { h->word[k] = (uint8_t) word[k]; }
    return begin_play(h, HAPTIC_OUT_MODE_WORD);
}

haptic_err_t haptic_out_play_prefix(haptic_out *h, haptic_tail tail)
{
    if ((uint8_t) tail >= HAPTIC_TAIL_COUNT) { return HAPTIC_ERR_INVALID_ARG; }
    h->tail = tail;
    return begin_play(h, HAPTIC_OUT_MODE_PREFIX);
}

/* Set the six dot channels from a bitmask (bit n = dot n, channel n). */
static haptic_err_t drive_mask(drv2605_bus *bus, uint8_t mask)
{
    for (uint8_t ch = 0; ch < DRV2605_DOT_COUNT; ch++) {
        uint8_t level = (mask & (1u << ch)) ? DRV2605_DRIVE_DEFAULT : 0;
        haptic_err_t err = drv2605_set_drive(bus, ch, level);
        if (err != HAPTIC_OK) { return err; }
    }
    return HAPTIC_OK;
}

uint32_t haptic_out_step(haptic_out *h, uint32_t now_ms, haptic_out_event_t *ev, haptic_out_step_t *step)
{
    if (!h->playing) {
        if (ev) { *ev = HAPTIC_OUT_EV_END; }
        return 0;
    }

    if (!h->started) {
        h->started = true;
        if (ev) { *ev = HAPTIC_OUT_EV_START; }
        return now_ms;   /* caller should call again immediately */
    }

    if (now_ms < h->next_deadline) {
        return h->next_deadline;   /* nothing to do yet */
    }

    if (h->buzzing) {
        /* Buzz ends: silence the dots, then either the gap or the drain. */
        (void) drv2605_stop_all(h->bus);
        h->cur_dot_mask = 0;
        h->buzzing = false;
        h->step_idx++;
        uint32_t buzz_ms = 0, gap_ms = 0;
        uint8_t mask = 0;
        if (!beat_info(h, &buzz_ms, &gap_ms, &mask)) {
            h->draining = true;   /* beats exhausted: END after the silence */
        }
        /* The silence that follows a buzz belongs to the beat that just
         * buzzed — its own gap_after_ms (for a play's last beat that IS the
         * tail gap) — never to the next one. */
        h->next_deadline = now_ms + h->last_gap_ms;
        return h->next_deadline;
    }

    /* Not buzzing: either a gap elapsed, or the drain finished. */
    if (h->draining) {
        h->playing = false;
        h->draining = false;
        h->mode = HAPTIC_OUT_MODE_IDLE;
        h->step_idx = 0;
        if (ev) { *ev = HAPTIC_OUT_EV_END; }
        return 0;
    }

    /* Begin the next buzz. */
    uint32_t buzz_ms = 0, gap_ms = 0;
    uint8_t mask = 0;
    if (!beat_info(h, &buzz_ms, &gap_ms, &mask)) {
        h->playing = false;
        h->mode = HAPTIC_OUT_MODE_IDLE;
        h->step_idx = 0;
        if (ev) { *ev = HAPTIC_OUT_EV_END; }
        return 0;
    }
    haptic_err_t err = drive_mask(h->bus, mask);
    if (err != HAPTIC_OK) {
        h->last_err = err;
        h->playing = false;
        h->mode = HAPTIC_OUT_MODE_IDLE;
        h->step_idx = 0;
        (void) drv2605_stop_all(h->bus);
        if (ev) { *ev = HAPTIC_OUT_EV_END; }
        return 0;
    }
    h->cur_dot_mask = mask;
    h->buzzing = true;
    h->last_gap_ms = gap_ms;
    h->next_deadline = now_ms + buzz_ms;
    if (step) {
        step->mode = h->mode;
        step->buzz_ms = buzz_ms;
        step->gap_after_ms = gap_ms;
        step->dot_mask = mask;
        step->seq = h->step_idx;
    }
    if (ev) { *ev = HAPTIC_OUT_EV_BUZZ; }
    return h->next_deadline;
}

bool haptic_out_is_playing(const haptic_out *h) { return h->playing; }
uint16_t haptic_out_beat_index(const haptic_out *h) { return h->step_idx; }
haptic_out_mode_t haptic_out_mode(const haptic_out *h) { return h->mode; }
