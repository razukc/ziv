/*
 * turn.h — the band's renderer contract (architecture §5.1), one utterance
 * at a time, on top of the haptic_out sequencer.
 *
 * A turn plays one utterance exactly as the reference renderer
 * (ziv/haptics/reference.py) defines it:
 *
 *   [prefix: mark cells at the pace, PREFIX_BREATH_MS after the last, the
 *            kind's tail pattern]                         when present
 *   the kind's cue pattern
 *   [`processing`, repeated every WORKING_EVERY_MS]       while body_pending
 *   the words: the pace between cells, WORD_GAP_MS between words
 *   TAIL_GAP_MS, then `end-of-message`
 *
 * It compiles ONE SEGMENT at a time (prefix, cue, working, a word, close)
 * into a bounded haptic_beat_ex buffer and hands it to
 * haptic_out_play_beats(), so the sequencer's START/BUZZ/END events — the
 * HAP log, the conformance timeline — are the same events a mark or a
 * word play produces.  Pull model like haptic_out: turn_step(now) returns
 * the next deadline; nothing blocks.
 *
 * Profiles (architecture §5.2): six_actuator drives a cell's dots together
 * for haptic_cell_ms(); single_actuator plays a cell as HAPTIC_SLOT_COUNT
 * slots in HAPTIC_SLOT_ORDER — SLOT_MS per raised dot, SLOT_GAP_MS after
 * every slot but the last, COLUMN_GAP_MS more after the third.
 *
 * Every duration comes from haptic_timing.h.  The one cadence the spec
 * does not name — how long a body may stay pending — is a COUNT of
 * working repeats (TURN_BODY_TIMEOUT_REPEATS), so it is still spec time.
 *
 * Host-portable: no ESP-IDF types.
 */
#ifndef ZIV_TURN_H
#define ZIV_TURN_H

#include <stdbool.h>
#include <stdint.h>
#include "haptic_out.h"
#include "utterance.h"

typedef enum {
    TURN_PROFILE_SIX_ACTUATOR = 0,
    TURN_PROFILE_SINGLE_ACTUATOR,
    TURN_PROFILE_COUNT
} turn_profile;

/* Progress phases on the wire (schema Phase) plus the two terminal ones. */
typedef enum {
    TURN_PHASE_CUE = 0,
    TURN_PHASE_WORKING,
    TURN_PHASE_WORD,      /* word_index says which */
    TURN_PHASE_CLOSE,
    TURN_PHASE_DONE,      /* the close finished on the actuator: `played` */
    TURN_PHASE_FAILED     /* label = the reason: see turn_result_name() */
} turn_phase;

typedef enum {
    TURN_RESULT_NONE = 0,
    TURN_RESULT_PLAYED,
    TURN_RESULT_BODY_TIMEOUT,    /* the body never came: nack body_timeout */
    TURN_RESULT_BODY_ERROR,      /* the relay said the body failed (no nack: it already knows) */
    TURN_RESULT_CANCELLED,       /* the wearer advanced past it: nack cancelled_by_wearer */
    TURN_RESULT_BUS_FAULT        /* the actuator bus failed mid-play: nack muted */
} turn_result;

typedef enum {
    TURN_CTL_STOP = 0,     /* silence now; the utterance stays loaded for REPLAY */
    TURN_CTL_REPLAY,       /* the utterance from its first beat */
    TURN_CTL_REPLAY_WORD,  /* the current (or last) word again, then continue */
    TURN_CTL_SKIP,         /* drop the current word; next word or the close */
    TURN_CTL_ADVANCE       /* done with this utterance now (FAILED cancelled_by_wearer if mid-play) */
} turn_control_t;

/* The segment that is compiling / playing; exposed for labels and tests. */
typedef enum {
    TURN_SEG_NONE = 0,
    TURN_SEG_PREFIX,
    TURN_SEG_CUE,
    TURN_SEG_WORKING,
    TURN_SEG_WORD,
    TURN_SEG_CLOSE,
    TURN_SEG_ERROR,       /* the error pattern when the body failed or timed out */
    TURN_SEG_ANNOUNCE     /* another utterance's arrival cue, interjected between segments */
} turn_segment;

/* Phase event: word_index is the word for TURN_PHASE_WORD (-1 otherwise);
 * label is "cue" | "working" | the word's letters | "close" | "played" |
 * the failure reason. */
typedef void (*turn_event_cb)(void *ctx, turn_phase phase, int word_index, const char *label);

/* Beat event: every HAPTIC_OUT_EV_BUZZ, with the sequencer's own step and
 * the reference's label ("prefix:z", "tail", "cue", "working", "cell:t",
 * "close"; also "error", "announce"). */
typedef void (*turn_beat_cb)(void *ctx, uint32_t now_ms, const haptic_out_step_t *step, const char *label);

/* A 32-letter word on single_actuator is at most 32 × 6 beats; a prefix is
 * 8 × 6 + the longest pattern.  One buffer, bounded, reused per segment. */
#define TURN_BEATS_MAX (ZIV_UTT_WORD_MAX * HAPTIC_SLOT_COUNT)
#define TURN_BEAT_PATTERN 0xFF   /* beat_letter[] marker for a pattern beat */

/* How many `processing` repeats a body may stay pending (count, not ms):
 * 12 × WORKING_EVERY_MS = 24 s at spec v4, past the relay's own 20 s body
 * timeout so the relay's error body normally arrives first. */
#define TURN_BODY_TIMEOUT_REPEATS 12

typedef struct {
    haptic_out *h;
    turn_profile profile;
    uint16_t pace_ms;

    ziv_utterance utt;            /* the turn's own copy */
    bool loaded;
    bool active;                  /* in progress: between load and DONE/FAILED/ADVANCE */
    bool stopped;                 /* wearer STOP: silent, kept for REPLAY */
    turn_segment seg;             /* playing now */
    uint8_t word_idx;
    turn_segment resume_seg;      /* what ANNOUNCE interrupts */
    uint8_t resume_word;
    int announce_kind;            /* -1 none, else a haptic_kind to cue at the next boundary */

    haptic_beat_ex beats[TURN_BEATS_MAX];
    uint8_t beat_letter[TURN_BEATS_MAX];   /* letter index per beat, or TURN_BEAT_PATTERN */
    uint16_t nbeats;
    uint16_t seg_lead_ms;         /* silence before the segment's first beat (a slot cell whose
                                     first raised dot is not in the first slot); a beat list cannot
                                     carry it, so the play is armed that much later */
    bool seg_armed;               /* the compiled segment waits for seg_start_ms */
    uint32_t seg_start_ms;

    bool body_arrived;
    bool body_error;
    bool waiting_body;            /* between working repeats, sequencer idle */
    uint32_t working_due_ms;      /* when the next repeat starts */
    uint8_t working_repeats;
    bool working_reported;        /* progress(working) sent once */

    turn_result result;
    uint32_t started_ms;          /* first beat of the utterance */
    uint32_t closed_ms;           /* END of the close */

    turn_event_cb on_event; void *event_ctx;
    turn_beat_cb on_beat; void *beat_ctx;
    char label[ZIV_UTT_WORD_MAX + 1];
} turn;

void turn_init(turn *t, haptic_out *h, turn_profile profile, uint32_t pace_ms);
void turn_set_callbacks(turn *t, turn_event_cb ev, void *ev_ctx, turn_beat_cb beat, void *beat_ctx);

/* Load an utterance (copied).  Playback starts at the next turn_step().
 * Returns false while another utterance is active (ADVANCE it first). */
bool turn_load(turn *t, const ziv_utterance *u);

/* The pending body arrived: these words (n may be 0 — an empty body plays
 * straight to the close).  Takes effect at the current segment's end, or
 * at once if the sequencer is idle between working repeats. */
ziv_utt_err turn_set_body(turn *t, const char *const *words, uint8_t n);
/* The relay says the body failed: the error pattern, then FAILED. */
void turn_set_body_error(turn *t);

/* Advance.  Returns the next deadline in monotonic ms, or 0 when there is
 * nothing scheduled (no utterance, stopped, or finished). */
uint32_t turn_step(turn *t, uint32_t now_ms);

void turn_control(turn *t, turn_control_t c, uint32_t now_ms);

/* Another utterance arrived while this one plays: its kind's cue is
 * interjected at the next segment boundary (plan §4 invariant 4).  Ignored
 * when no utterance is active (its own turn will cue it). */
void turn_announce(turn *t, haptic_kind kind);

/* The pace (cell gap) — clamped to the spec envelope; applies from the next
 * segment.  Also sets the sequencer's own pace for MARK/WORD/PREFIX plays. */
uint16_t turn_set_pace(turn *t, uint32_t pace_ms);
uint16_t turn_pace(const turn *t);

bool turn_is_active(const turn *t);
bool turn_is_loaded(const turn *t);
const ziv_utterance *turn_current(const turn *t);   /* NULL when nothing is loaded */
turn_result turn_last_result(const turn *t);
uint32_t turn_started_ms(const turn *t);
uint32_t turn_closed_ms(const turn *t);
/* Release a finished utterance (after DONE/FAILED) so another may load. */
void turn_release(turn *t);

const char *turn_result_name(turn_result r);   /* wire reasons: "body_timeout", "cancelled_by_wearer", "muted", ... */
const char *turn_phase_name(turn_phase p);     /* "cue" | "working" | "word" | "close" | "done" | "failed" */
const char *turn_profile_name(turn_profile p); /* "six_actuator" | "single_actuator" */
int turn_profile_from_name(const char *name);  /* -1 when unknown */

/* Segment compilers, exposed for the golden tests: compile into t->beats. */
void turn_compile_prefix(turn *t);
void turn_compile_pattern(turn *t, haptic_pattern p);
void turn_compile_word(turn *t, uint8_t word_index);
/* One cell at the current pace/profile with a trailing silence, appended. */
void turn_compile_cell(turn *t, uint8_t letter_idx, uint16_t trailing_gap_ms);

#endif /* ZIV_TURN_H */
