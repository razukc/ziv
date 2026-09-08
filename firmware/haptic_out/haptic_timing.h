/* GENERATED FILE — do not edit by hand.
 *
 * Source of truth: docs/haptic-timing.json
 * Regenerate:      python tools/haptic_timing.py --write
 * Consumer:        firmware/haptic_out — DRV2605L vibro-braille sequencer + attention patterns (plan §5)
 * Readable spec:   docs/HAPTIC_TIMING_SPEC.md
 *
 * The phone feel-tool (docs/haptic-name-marks.html) is generated from the same
 * JSON — never tune a duration here without regenerating both sides.
 */
#ifndef HAPTIC_TIMING_H
#define HAPTIC_TIMING_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define HAPTIC_SPEC_VERSION 2

/* Vibro-braille cell: buzz_ms = CELL_BASE_MS + CELL_PER_DOT_MS * dot_count */
#define CELL_BASE_MS 50
#define CELL_PER_DOT_MS 60

/* Inter-cell silence is the playback-speed setting (user-tunable on device). */
#define CELL_GAP_DEFAULT_MS 420
#define CELL_GAP_MIN_MS 250
#define CELL_GAP_MAX_MS 700

/* Attention-vocabulary constants (plan §4). One beat = buzz, then silence. */
#define TICK_MS 70
#define TICK_GAP_MS 160
#define LONG_BUZZ_MS 600
#define TAIL_GAP_MS 420
#define PREFIX_BREATH_MS 550

/* One haptic beat: buzz for buzz_ms, then stay silent for gap_after_ms. */
typedef struct {
    uint16_t buzz_ms;
    uint16_t gap_after_ms;
} haptic_beat;

/* --- Attention patterns (plan §4) --- */

#define HAPTIC_DOUBLE_TAP_LEN 2
static const haptic_beat HAPTIC_DOUBLE_TAP[HAPTIC_DOUBLE_TAP_LEN] = {
    {TICK_MS, TICK_GAP_MS}, {TICK_MS, TAIL_GAP_MS}
};

#define HAPTIC_TRIPLE_PULSE_LEN 3
static const haptic_beat HAPTIC_TRIPLE_PULSE[HAPTIC_TRIPLE_PULSE_LEN] = {
    {TICK_MS, TICK_GAP_MS}, {TICK_MS, TICK_GAP_MS}, {TICK_MS, TAIL_GAP_MS}
};

#define HAPTIC_LONG_BUZZ_LEN 1
static const haptic_beat HAPTIC_LONG_BUZZ[HAPTIC_LONG_BUZZ_LEN] = {
    {LONG_BUZZ_MS, TAIL_GAP_MS}
};

#define HAPTIC_RAMP_UP_LEN 4
static const haptic_beat HAPTIC_RAMP_UP[HAPTIC_RAMP_UP_LEN] = {
    {50, 90}, {90, 120}, {140, 160}, {200, TAIL_GAP_MS}
};

#define HAPTIC_HEARTBEAT_LEN 2
static const haptic_beat HAPTIC_HEARTBEAT[HAPTIC_HEARTBEAT_LEN] = {
    {TICK_MS, 120}, {TICK_MS, TAIL_GAP_MS}
};

typedef enum {
    HAPTIC_PAT_DOUBLE_TAP = 0,
    HAPTIC_PAT_TRIPLE_PULSE,
    HAPTIC_PAT_LONG_BUZZ,
    HAPTIC_PAT_RAMP_UP,
    HAPTIC_PAT_HEARTBEAT,
    HAPTIC_PAT_COUNT
} haptic_pattern;

static const haptic_beat *const HAPTIC_PATTERN_TABLE[HAPTIC_PAT_COUNT] = {
    HAPTIC_DOUBLE_TAP, HAPTIC_TRIPLE_PULSE, HAPTIC_LONG_BUZZ, HAPTIC_RAMP_UP, HAPTIC_HEARTBEAT
};
static const uint8_t HAPTIC_PATTERN_LEN_TABLE[HAPTIC_PAT_COUNT] = {
    HAPTIC_DOUBLE_TAP_LEN, HAPTIC_TRIPLE_PULSE_LEN, HAPTIC_LONG_BUZZ_LEN, HAPTIC_RAMP_UP_LEN, HAPTIC_HEARTBEAT_LEN
};

/* --- Grade-1 alphabet: dot counts and derived cell durations (index 0 = 'a') --- */
#define HAPTIC_LETTERS 26
/* a b c d e f g h i j k l m n o p q r s t u v w x y z */
static const uint8_t HAPTIC_LETTER_DOTS[HAPTIC_LETTERS] = {
    1, 2, 2, 3, 2, 3, 4, 3, 2, 3, 2, 3, 3, 4, 3, 4, 5, 4, 3, 4, 3, 4, 4, 4, 5, 4
};
static const uint16_t HAPTIC_LETTER_MS[HAPTIC_LETTERS] = {
    110, 170, 170, 230, 170, 230, 290, 230, 170, 230, 170, 230, 230, 290, 230, 290, 350, 290, 230, 290, 230, 290, 290, 290, 350, 290
};
static const uint8_t HAPTIC_LETTER_MASKS[HAPTIC_LETTERS] = {
    /* dot bitmask, bit n = dot n (DRV2605L / LRA pin mapping lives in haptic_out.c) */
    0x01, 0x03, 0x09, 0x19, 0x11, 0x0B, 0x1B, 0x13, 0x0A, 0x1A, 0x05, 0x07, 0x0D, 0x1D, 0x15, 0x0F, 0x1F, 0x17, 0x0E, 0x1E, 0x25, 0x27, 0x3A, 0x2D, 0x3D, 0x35
};

/* Cell buzz duration for a letter 'a'..'z'. */
static inline uint16_t haptic_cell_ms(char letter) {
    return (uint16_t) (CELL_BASE_MS + CELL_PER_DOT_MS * HAPTIC_LETTER_DOTS[letter - 'a']);
}

/* --- The five candidate marks (letter indices, 0 = 'a'); protocol §0 loads all five --- */
#define HAPTIC_MARK_ZIV_LEN 3
static const uint8_t HAPTIC_MARK_ZIV[HAPTIC_MARK_ZIV_LEN] = { 25, 8, 21 }; /* z i v */
#define HAPTIC_MARK_RAZ_LEN 3
static const uint8_t HAPTIC_MARK_RAZ[HAPTIC_MARK_RAZ_LEN] = { 17, 0, 25 }; /* r a z */
#define HAPTIC_MARK_BOAZ_LEN 4
static const uint8_t HAPTIC_MARK_BOAZ[HAPTIC_MARK_BOAZ_LEN] = { 1, 14, 0, 25 }; /* b o a z */
#define HAPTIC_MARK_RAZU_LEN 4
static const uint8_t HAPTIC_MARK_RAZU[HAPTIC_MARK_RAZU_LEN] = { 17, 0, 25, 20 }; /* r a z u */
#define HAPTIC_MARK_BUZ_LEN 3
static const uint8_t HAPTIC_MARK_BUZ[HAPTIC_MARK_BUZ_LEN] = { 1, 20, 25 }; /* b u z */
#define HAPTIC_MARK_COUNT 5
static const uint8_t *const HAPTIC_MARK_TABLE[HAPTIC_MARK_COUNT] = {
    HAPTIC_MARK_ZIV, HAPTIC_MARK_RAZ, HAPTIC_MARK_BOAZ, HAPTIC_MARK_RAZU, HAPTIC_MARK_BUZ
};
static const uint8_t HAPTIC_MARK_LEN_TABLE[HAPTIC_MARK_COUNT] = {
    HAPTIC_MARK_ZIV_LEN, HAPTIC_MARK_RAZ_LEN, HAPTIC_MARK_BOAZ_LEN, HAPTIC_MARK_RAZU_LEN, HAPTIC_MARK_BUZ_LEN
};

/* --- Rename examples: protocol §5 option B — same arc, different word (arc-validated only; legal screening per plan §1) --- */
/* same dot-count arc as ziv: 4-2-4 */
#define HAPTIC_RENAME_ARC_REF HAPTIC_MARK_ZIV
#define HAPTIC_RENAME_WORD_COUNT 2

/* --- Name-mark prefix (plan §4): play a mark, keep silent PREFIX_BREATH_MS, then the tail --- */
typedef enum {
    HAPTIC_TAIL_MESSAGE = 0,
    HAPTIC_TAIL_REMINDER,
    HAPTIC_TAIL_ERROR,
    HAPTIC_TAIL_COUNT
} haptic_tail;

static const haptic_pattern HAPTIC_PREFIX_TAIL_TABLE[HAPTIC_TAIL_COUNT] = {
    HAPTIC_PAT_DOUBLE_TAP, HAPTIC_PAT_TRIPLE_PULSE, HAPTIC_PAT_LONG_BUZZ
};
#define HAPTIC_PREFIX_MARK_INDEX 0  /* ziv — index into HAPTIC_MARK_TABLE */

#ifdef __cplusplus
}
#endif

#endif /* HAPTIC_TIMING_H */
