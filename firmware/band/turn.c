/*
 * turn.c — the renderer contract on top of haptic_out (see turn.h).
 *
 * Segment chain (each an END of the sequencer):
 *   PREFIX? → CUE → WORKING* (while body_pending) → WORD 0 … WORD n-1 → CLOSE → DONE
 *                           ↘ ERROR → FAILED (body failed / timed out)
 *   ANNOUNCE may sit between any two segments (another utterance's cue).
 *
 * The compiled gaps carry the structure: a cell's trailing silence is the
 * pace inside a word, WORD_GAP_MS at a word boundary, PREFIX_BREATH_MS
 * after the mark, TAIL_GAP_MS after the last word; a pattern's beats carry
 * the spec's own gaps, the last being the tail gap — so when the sequencer
 * fires END the next segment starts at exactly the reference's offset.
 */
#include "turn.h"

#include <string.h>

/* --- names ----------------------------------------------------------------- */

static const char *const k_profile_names[TURN_PROFILE_COUNT] = { "six_actuator", "single_actuator" };

const char *turn_profile_name(turn_profile p)
{
    return ((unsigned) p < TURN_PROFILE_COUNT) ? k_profile_names[p] : "?";
}

int turn_profile_from_name(const char *name)
{
    if (name == NULL) { return -1; }
    for (int i = 0; i < (int) TURN_PROFILE_COUNT; i++) {
        if (strcmp(k_profile_names[i], name) == 0) { return i; }
    }
    return -1;
}

const char *turn_result_name(turn_result r)
{
    switch (r) {
    case TURN_RESULT_NONE:         return "none";
    case TURN_RESULT_PLAYED:       return "played";
    case TURN_RESULT_BODY_TIMEOUT: return "body_timeout";
    case TURN_RESULT_BODY_ERROR:   return "compose_failed";
    case TURN_RESULT_CANCELLED:    return "cancelled_by_wearer";
    case TURN_RESULT_BUS_FAULT:    return "muted";
    default:                       return "?";
    }
}

const char *turn_phase_name(turn_phase p)
{
    switch (p) {
    case TURN_PHASE_CUE:     return "cue";
    case TURN_PHASE_WORKING: return "working";
    case TURN_PHASE_WORD:    return "word";
    case TURN_PHASE_CLOSE:   return "close";
    case TURN_PHASE_DONE:    return "done";
    case TURN_PHASE_FAILED:  return "failed";
    default:                 return "?";
    }
}

/* --- init / pace ------------------------------------------------------------ */

static uint16_t clamp_pace(uint32_t ms)
{
    if (ms < CELL_GAP_MIN_MS) { ms = CELL_GAP_MIN_MS; }
    if (ms > CELL_GAP_MAX_MS) { ms = CELL_GAP_MAX_MS; }
    return (uint16_t) ms;
}

void turn_init(turn *t, haptic_out *h, turn_profile profile, uint32_t pace_ms)
{
    memset(t, 0, sizeof *t);
    t->h = h;
    t->profile = profile;
    t->pace_ms = clamp_pace(pace_ms);
    (void) haptic_out_set_cell_gap_ms(h, t->pace_ms);
    t->announce_kind = -1;
}

void turn_set_callbacks(turn *t, turn_event_cb ev, void *ev_ctx, turn_beat_cb beat, void *beat_ctx)
{
    t->on_event = ev;
    t->event_ctx = ev_ctx;
    t->on_beat = beat;
    t->beat_ctx = beat_ctx;
}

uint16_t turn_set_pace(turn *t, uint32_t pace_ms)
{
    t->pace_ms = clamp_pace(pace_ms);
    (void) haptic_out_set_cell_gap_ms(t->h, t->pace_ms);
    return t->pace_ms;
}

uint16_t turn_pace(const turn *t) { return t->pace_ms; }
bool turn_is_active(const turn *t) { return t->active; }
bool turn_is_loaded(const turn *t) { return t->loaded; }
const ziv_utterance *turn_current(const turn *t) { return t->loaded ? &t->utt : NULL; }
turn_result turn_last_result(const turn *t) { return t->result; }
uint32_t turn_started_ms(const turn *t) { return t->started_ms; }
uint32_t turn_closed_ms(const turn *t) { return t->closed_ms; }

/* --- segment compilers ------------------------------------------------------ */

static void beats_clear(turn *t)
{
    t->nbeats = 0;
    t->seg_lead_ms = 0;
}

/* Silence BEFORE a beat: a beat list only has silence after a beat, so it
 * lands on the previous beat's gap — or, for the segment's first beat, on
 * the segment's lead (the play is armed that much later). */
static void lead_silence(turn *t, uint32_t ms)
{
    if (ms == 0) { return; }
    if (t->nbeats == 0) { t->seg_lead_ms = (uint16_t) (t->seg_lead_ms + ms); }
    else { t->beats[t->nbeats - 1].gap_after_ms = (uint16_t) (t->beats[t->nbeats - 1].gap_after_ms + ms); }
}

static void beats_add(turn *t, uint8_t mask, uint32_t buzz_ms, uint32_t gap_ms, uint8_t letter)
{
    if (t->nbeats >= TURN_BEATS_MAX) { return; }   /* cannot happen within the caps; never overrun */
    t->beats[t->nbeats].dot_mask = mask;
    t->beats[t->nbeats].buzz_ms = (uint16_t) buzz_ms;
    t->beats[t->nbeats].gap_after_ms = (uint16_t) gap_ms;
    t->beat_letter[t->nbeats] = letter;
    t->nbeats++;
}

void turn_compile_cell(turn *t, uint8_t letter_idx, uint16_t trailing_gap_ms)
{
    uint8_t mask = HAPTIC_LETTER_MASKS[letter_idx];
    if (t->profile == TURN_PROFILE_SIX_ACTUATOR) {
        beats_add(t, mask, haptic_cell_ms((char) ('a' + letter_idx)), trailing_gap_ms, letter_idx);
        return;
    }

    /* single_actuator: slot offsets exactly as the reference computes them */
    uint32_t off[HAPTIC_SLOT_COUNT];
    uint32_t cursor = 0;
    const int column_break = HAPTIC_SLOT_COUNT / 2 - 1;   /* after the third of six slots */
    for (int i = 0; i < HAPTIC_SLOT_COUNT; i++) {
        off[i] = cursor;
        cursor += SLOT_MS;
        if (i < HAPTIC_SLOT_COUNT - 1) { cursor += SLOT_GAP_MS; }
        if (i == column_break) { cursor += COLUMN_GAP_MS; }
    }
    const uint32_t cell_end = cursor;   /* == HAPTIC_SLOT_CELL_MS */

    /* one beat per raised dot; its gap reaches the next raised dot's start,
     * the last one reaches the cell's end plus the trailing silence */
    int raised[HAPTIC_SLOT_COUNT];
    int nraised = 0;
    for (int i = 0; i < HAPTIC_SLOT_COUNT; i++) {
        uint8_t bit = (uint8_t) (1u << (HAPTIC_SLOT_ORDER[i] - 1));
        if (mask & bit) { raised[nraised++] = i; }
    }
    if (nraised == 0) {   /* every letter has a dot; a whole cell of silence, should it ever come */
        lead_silence(t, cell_end + trailing_gap_ms);
        return;
    }
    lead_silence(t, off[raised[0]]);   /* absent dots before the first raised one */
    for (int k = 0; k < nraised; k++) {
        int i = raised[k];
        uint32_t start = off[i];
        uint32_t next_start = (k + 1 < nraised) ? off[raised[k + 1]] : cell_end;
        uint32_t gap = next_start - (start + SLOT_MS);
        if (k + 1 == nraised) { gap += trailing_gap_ms; }
        uint8_t bit = (uint8_t) (1u << (HAPTIC_SLOT_ORDER[i] - 1));
        beats_add(t, bit, SLOT_MS, gap, letter_idx);
    }
}

void turn_compile_pattern(turn *t, haptic_pattern p)
{
    uint8_t len = HAPTIC_PATTERN_LEN_TABLE[p];
    const haptic_beat *beats = HAPTIC_PATTERN_TABLE[p];
    for (uint8_t i = 0; i < len; i++) {
        beats_add(t, 0, beats[i].buzz_ms, beats[i].gap_after_ms, TURN_BEAT_PATTERN);
    }
}

void turn_compile_prefix(turn *t)
{
    beats_clear(t);
    for (uint8_t i = 0; i < t->utt.mark_len; i++) {
        uint16_t gap = (i + 1 == t->utt.mark_len) ? PREFIX_BREATH_MS : t->pace_ms;
        turn_compile_cell(t, t->utt.mark[i], gap);
    }
    turn_compile_pattern(t, t->utt.tail);
}

void turn_compile_word(turn *t, uint8_t wi)
{
    beats_clear(t);
    uint8_t n = 0;
    const uint8_t *w = utterance_word(&t->utt, wi, &n);
    if (w == NULL) { return; }
    bool last_word = (wi + 1 >= t->utt.word_count);
    for (uint8_t i = 0; i < n; i++) {
        uint16_t gap;
        if (i + 1 < n) { gap = t->pace_ms; }
        else { gap = last_word ? TAIL_GAP_MS : WORD_GAP_MS; }
        turn_compile_cell(t, w[i], gap);
    }
}

/* --- events ----------------------------------------------------------------- */

static void emit(turn *t, turn_phase phase, int word_index, const char *label)
{
    if (t->on_event) { t->on_event(t->event_ctx, phase, word_index, label); }
}

static const char *beat_label(turn *t, uint16_t seq)
{
    uint8_t letter = (seq < t->nbeats) ? t->beat_letter[seq] : TURN_BEAT_PATTERN;
    switch (t->seg) {
    case TURN_SEG_PREFIX:
        if (letter == TURN_BEAT_PATTERN) { return "tail"; }
        t->label[0] = 'p'; t->label[1] = 'r'; t->label[2] = 'e'; t->label[3] = 'f'; t->label[4] = 'i'; t->label[5] = 'x';
        t->label[6] = ':'; t->label[7] = (char) ('a' + letter); t->label[8] = '\0';
        return t->label;
    case TURN_SEG_CUE:      return "cue";
    case TURN_SEG_WORKING:  return "working";
    case TURN_SEG_WORD:
        t->label[0] = 'c'; t->label[1] = 'e'; t->label[2] = 'l'; t->label[3] = 'l'; t->label[4] = ':';
        t->label[5] = (letter == TURN_BEAT_PATTERN) ? '?' : (char) ('a' + letter); t->label[6] = '\0';
        return t->label;
    case TURN_SEG_CLOSE:    return "close";
    case TURN_SEG_ERROR:    return "error";
    case TURN_SEG_ANNOUNCE: return "announce";
    default:                return "?";
    }
}

/* --- the segment chain ------------------------------------------------------ */

static void finish(turn *t, turn_result result, uint32_t now_ms)
{
    t->result = result;
    t->active = false;
    t->waiting_body = false;
    t->seg_armed = false;
    t->seg = TURN_SEG_NONE;
    if (result == TURN_RESULT_PLAYED) {
        t->closed_ms = now_ms;
        emit(t, TURN_PHASE_DONE, -1, "played");
    } else {
        emit(t, TURN_PHASE_FAILED, -1, turn_result_name(result));
    }
}

/* Compile and start `seg` now; emits the phase event for it. */
static void start_segment(turn *t, turn_segment seg, uint32_t now_ms)
{
    t->seg = seg;
    t->waiting_body = false;
    switch (seg) {
    case TURN_SEG_PREFIX:
        turn_compile_prefix(t);
        break;
    case TURN_SEG_CUE:
        beats_clear(t);
        turn_compile_pattern(t, HAPTIC_KIND_CUE_TABLE[t->utt.kind]);
        emit(t, TURN_PHASE_CUE, -1, "cue");
        break;
    case TURN_SEG_WORKING:
        beats_clear(t);
        turn_compile_pattern(t, HAPTIC_PAT_PROCESSING);
        t->working_due_ms = now_ms + WORKING_EVERY_MS;   /* the period runs start to start */
        if (!t->working_reported) {
            t->working_reported = true;
            emit(t, TURN_PHASE_WORKING, -1, "working");
        }
        break;
    case TURN_SEG_WORD:
        turn_compile_word(t, t->word_idx);
        (void) utterance_word_text(&t->utt, t->word_idx, t->label, sizeof t->label);
        emit(t, TURN_PHASE_WORD, (int) t->word_idx, t->label);
        break;
    case TURN_SEG_CLOSE:
        beats_clear(t);
        turn_compile_pattern(t, HAPTIC_PAT_END_OF_MESSAGE);
        emit(t, TURN_PHASE_CLOSE, -1, "close");
        break;
    case TURN_SEG_ERROR:
        beats_clear(t);
        turn_compile_pattern(t, HAPTIC_KIND_CUE_TABLE[HAPTIC_KIND_ERROR]);
        break;
    case TURN_SEG_ANNOUNCE:
        beats_clear(t);
        turn_compile_pattern(t, HAPTIC_KIND_CUE_TABLE[(haptic_kind) t->announce_kind]);
        t->announce_kind = -1;
        break;
    default:
        return;
    }
    /* play now, or after the segment's lead silence */
    t->seg_armed = true;
    t->seg_start_ms = now_ms + t->seg_lead_ms;
}

/* The armed segment's start time has come: hand the beats to the sequencer. */
static void fire_segment(turn *t)
{
    t->seg_armed = false;
    if (t->nbeats == 0) { return; }   /* nothing to play; on_end runs on the next step */
    (void) haptic_out_play_beats(t->h, t->beats, t->nbeats);
}

/* Start `seg`, or an interjected announce first when one is pending. */
static void start_next(turn *t, turn_segment seg, uint32_t now_ms)
{
    if (t->announce_kind >= 0 && seg != TURN_SEG_ANNOUNCE) {
        t->resume_seg = seg;
        t->resume_word = t->word_idx;
        start_segment(t, TURN_SEG_ANNOUNCE, now_ms);
        return;
    }
    start_segment(t, seg, now_ms);
}

static void words_or_close(turn *t, uint32_t now_ms)
{
    if (t->utt.word_count > 0) {
        t->word_idx = 0;
        start_next(t, TURN_SEG_WORD, now_ms);
    } else {
        start_next(t, TURN_SEG_CLOSE, now_ms);
    }
}

static void after_cue(turn *t, uint32_t now_ms)
{
    if (t->body_error) { start_next(t, TURN_SEG_ERROR, now_ms); return; }
    if (t->utt.body_pending && !t->body_arrived) {
        t->working_repeats = 0;
        start_next(t, TURN_SEG_WORKING, now_ms);
        return;
    }
    words_or_close(t, now_ms);
}

/* Returns the next deadline (0 when a segment was started: step again). */
static uint32_t after_working(turn *t, uint32_t now_ms)
{
    t->working_repeats++;
    if (t->body_error) { t->result = TURN_RESULT_BODY_ERROR; start_next(t, TURN_SEG_ERROR, now_ms); return 0; }
    if (t->body_arrived) { words_or_close(t, now_ms); return 0; }
    if (t->working_repeats >= TURN_BODY_TIMEOUT_REPEATS) {
        t->result = TURN_RESULT_BODY_TIMEOUT;
        start_next(t, TURN_SEG_ERROR, now_ms);
        return 0;
    }
    if (t->announce_kind >= 0) {
        /* an arrival cue fits in the silence between repeats */
        t->resume_seg = TURN_SEG_WORKING;   /* resumes as a wait, see on_end */
        start_segment(t, TURN_SEG_ANNOUNCE, now_ms);
        return 0;
    }
    t->waiting_body = true;
    return t->working_due_ms;
}

/* The sequencer finished the current segment.  Returns a deadline, or 0
 * when a new segment started (the caller steps again at once), or 0 with
 * active == false when the utterance is over. */
static uint32_t on_end(turn *t, uint32_t now_ms)
{
    if (t->h->last_err != HAPTIC_OK) {
        finish(t, TURN_RESULT_BUS_FAULT, now_ms);
        return 0;
    }
    switch (t->seg) {
    case TURN_SEG_PREFIX:
        start_next(t, TURN_SEG_CUE, now_ms);
        return 0;
    case TURN_SEG_CUE:
        after_cue(t, now_ms);
        return 0;
    case TURN_SEG_WORKING:
        return after_working(t, now_ms);
    case TURN_SEG_WORD:
        if (t->word_idx + 1 < t->utt.word_count) {
            t->word_idx++;
            start_next(t, TURN_SEG_WORD, now_ms);
        } else {
            start_next(t, TURN_SEG_CLOSE, now_ms);
        }
        return 0;
    case TURN_SEG_CLOSE:
        finish(t, TURN_RESULT_PLAYED, now_ms);
        return 0;
    case TURN_SEG_ERROR:
        finish(t, t->result == TURN_RESULT_NONE ? TURN_RESULT_BODY_ERROR : t->result, now_ms);
        return 0;
    case TURN_SEG_ANNOUNCE:
        if (t->resume_seg == TURN_SEG_WORKING) {
            /* back to the wait between repeats (the repeat may be due already) */
            t->seg = TURN_SEG_WORKING;
            t->waiting_body = true;
            return (t->working_due_ms > now_ms) ? t->working_due_ms : now_ms;
        }
        t->word_idx = t->resume_word;
        start_segment(t, t->resume_seg, now_ms);
        return 0;
    default:
        finish(t, TURN_RESULT_PLAYED, now_ms);
        return 0;
    }
}

uint32_t turn_step(turn *t, uint32_t now_ms)
{
    if (!t->loaded || !t->active || t->stopped) { return 0; }

    for (int guard = 0; guard < 64; guard++) {
        if (t->seg == TURN_SEG_NONE) {
            /* the utterance's first beat */
            t->started_ms = now_ms;
            start_next(t, t->utt.has_prefix ? TURN_SEG_PREFIX : TURN_SEG_CUE, now_ms);
            continue;
        }

        if (t->waiting_body) {
            if (t->body_arrived || t->body_error) {
                t->waiting_body = false;
                if (t->body_error) { t->result = TURN_RESULT_BODY_ERROR; start_next(t, TURN_SEG_ERROR, now_ms); }
                else { words_or_close(t, now_ms); }
                continue;
            }
            if (now_ms < t->working_due_ms) { return t->working_due_ms; }
            t->waiting_body = false;
            start_next(t, TURN_SEG_WORKING, now_ms);
            continue;
        }

        if (t->seg_armed) {
            if (now_ms < t->seg_start_ms) { return t->seg_start_ms; }
            fire_segment(t);
            if (!haptic_out_is_playing(t->h)) {
                /* an empty segment: treat as ended at once */
                uint32_t deadline = on_end(t, now_ms);
                if (!t->active) { return 0; }
                if (deadline > now_ms) { return deadline; }
            }
            continue;
        }

        if (!haptic_out_is_playing(t->h)) {
            /* a control stopped the sequencer and left a segment to start */
            start_next(t, t->seg, now_ms);
            continue;
        }

        haptic_out_event_t ev = (haptic_out_event_t) 0xFF;
        haptic_out_step_t st;
        memset(&st, 0, sizeof st);
        uint32_t next = haptic_out_step(t->h, now_ms, &ev, &st);
        if (ev == HAPTIC_OUT_EV_START) { continue; }
        if (ev == HAPTIC_OUT_EV_BUZZ) {
            if (t->on_beat) { t->on_beat(t->beat_ctx, now_ms, &st, beat_label(t, st.seq)); }
            if (next > now_ms) { return next; }
            continue;
        }
        if (ev == HAPTIC_OUT_EV_END) {
            uint32_t deadline = on_end(t, now_ms);
            if (!t->active) { return 0; }
            if (deadline > now_ms) { return deadline; }
            continue;
        }
        /* no event: waiting on the sequencer's deadline */
        return next;
    }
    return now_ms;   /* guard tripped: ask to be called again */
}

/* --- loading, body, controls ------------------------------------------------ */

bool turn_load(turn *t, const ziv_utterance *u)
{
    if (t->active) { return false; }
    haptic_out_stop(t->h);
    t->utt = *u;
    t->loaded = true;
    t->active = true;
    t->stopped = false;
    t->seg = TURN_SEG_NONE;
    t->word_idx = 0;
    t->resume_seg = TURN_SEG_NONE;
    t->resume_word = 0;
    t->announce_kind = -1;
    t->nbeats = 0;
    t->seg_lead_ms = 0;
    t->seg_armed = false;
    t->seg_start_ms = 0;
    t->body_arrived = !u->body_pending;
    t->body_error = u->body_error;
    t->waiting_body = false;
    t->working_due_ms = 0;
    t->working_repeats = 0;
    t->working_reported = false;
    t->result = TURN_RESULT_NONE;
    t->started_ms = 0;
    t->closed_ms = 0;
    return true;
}

void turn_release(turn *t)
{
    if (t->active) { haptic_out_stop(t->h); }
    t->loaded = false;
    t->active = false;
    t->stopped = false;
    t->seg = TURN_SEG_NONE;
    t->waiting_body = false;
    t->seg_armed = false;
}

ziv_utt_err turn_set_body(turn *t, const char *const *words, uint8_t n)
{
    if (!t->loaded) { return ZIV_UTT_ERR_FIELD; }
    ziv_utt_err err = utterance_set_words(&t->utt, words, n);
    if (err != ZIV_UTT_OK) { return err; }
    t->utt.body_pending = false;
    t->body_arrived = true;
    return ZIV_UTT_OK;
}

void turn_set_body_error(turn *t)
{
    if (!t->loaded) { return; }
    t->body_error = true;
}

void turn_announce(turn *t, haptic_kind kind)
{
    if (!t->active || t->stopped) { return; }
    if ((unsigned) kind >= HAPTIC_KIND_COUNT) { return; }
    t->announce_kind = (int) kind;
}

void turn_control(turn *t, turn_control_t c, uint32_t now_ms)
{
    if (!t->loaded) { return; }
    switch (c) {
    case TURN_CTL_STOP:
        if (!t->active) { return; }
        haptic_out_stop(t->h);
        t->stopped = true;
        t->waiting_body = false;
        t->seg_armed = false;
        break;
    case TURN_CTL_REPLAY: {
        /* from the first beat; the body state is kept (a body that came
         * stays; one still pending is still waited for) */
        bool arrived = t->body_arrived, failed = t->body_error;
        haptic_out_stop(t->h);
        t->active = false;            /* turn_load refuses an active turn; this is a restart */
        (void) turn_load(t, &t->utt);
        t->body_arrived = arrived || !t->utt.body_pending;
        t->body_error = failed;
        break;
    }
    case TURN_CTL_REPLAY_WORD:
        if (t->utt.word_count == 0 || !t->body_arrived) { return; }
        haptic_out_stop(t->h);
        t->stopped = false;
        t->active = true;
        t->waiting_body = false;
        t->seg_armed = false;
        if (t->seg == TURN_SEG_CLOSE || t->seg == TURN_SEG_NONE) { t->word_idx = (uint8_t) (t->utt.word_count - 1); }
        if (t->seg != TURN_SEG_WORD && t->seg != TURN_SEG_CLOSE) { t->word_idx = 0; }
        t->seg = TURN_SEG_WORD;   /* turn_step starts it (sequencer idle) */
        break;
    case TURN_CTL_SKIP:
        if (!t->active || t->seg != TURN_SEG_WORD) { return; }
        haptic_out_stop(t->h);
        t->stopped = false;
        t->seg_armed = false;
        if (t->word_idx + 1 < t->utt.word_count) { t->word_idx++; t->seg = TURN_SEG_WORD; }
        else { t->seg = TURN_SEG_CLOSE; }
        break;
    case TURN_CTL_ADVANCE:
        if (t->active) {
            haptic_out_stop(t->h);
            t->stopped = false;
            t->seg_armed = false;
            finish(t, TURN_RESULT_CANCELLED, now_ms);
        }
        break;
    default:
        break;
    }
}
