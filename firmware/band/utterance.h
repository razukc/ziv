/*
 * utterance.h — the band's decoded utterance (architecture §2).
 *
 * A compact, pointer-free image of one wire utterance (schema/utterance.json):
 * the id, the kind, the optional name-mark prefix, the words as letter
 * indices packed back to back, the body_pending flag, the spec version and
 * the source.  Pointer-free so a queue slot, an NVS blob and a turn's own
 * copy are all plain memcpy-able.
 *
 * Decoding refuses rather than guesses: every schema cap is a distinct
 * error code and nothing is ever truncated — an utterance the band cannot
 * hold whole is an utterance it does not hold at all (and the transport
 * tells the relay why, with a nack).
 *
 * Letters are stored as indices 0..25 ('a'..'z'), the same index the
 * generated tables use (HAPTIC_LETTER_MASKS[idx], haptic_cell_ms('a'+idx)).
 *
 * Host-portable: the only dependency is cJSON (vendored for the host,
 * ESP-IDF's json component on the device) and the generated timing header.
 */
#ifndef ZIV_UTTERANCE_H
#define ZIV_UTTERANCE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "haptic_timing.h"

/* Caps, exactly the schema's (ziv/wire.py): id 8..64 chars, mark 1..8
 * letters, up to 64 words of 1..32 letters. */
#define ZIV_UTT_ID_MIN      8
#define ZIV_UTT_ID_MAX      64
#define ZIV_UTT_MARK_MAX    8
#define ZIV_UTT_WORDS_MAX   64
#define ZIV_UTT_WORD_MAX    32
#define ZIV_UTT_LETTERS_MAX (ZIV_UTT_WORDS_MAX * ZIV_UTT_WORD_MAX)
#define ZIV_WIRE_VERSION    1

/* How the words were produced (wire: "sender" | "echo" | "live"). */
typedef enum {
    ZIV_SOURCE_SENDER = 0,
    ZIV_SOURCE_ECHO,
    ZIV_SOURCE_LIVE,
    ZIV_SOURCE_COUNT
} ziv_source;

typedef struct {
    char id[ZIV_UTT_ID_MAX + 1];
    haptic_kind kind;                        /* selects the cue and the tail (generated tables) */
    bool has_prefix;
    uint8_t mark_len;
    uint8_t mark[ZIV_UTT_MARK_MAX];          /* letter indices 0..25 */
    haptic_pattern tail;                     /* HAPTIC_KIND_TAIL_TABLE[kind]; the wire's prefix.tail agreed with it */
    uint8_t word_count;
    uint8_t word_len[ZIV_UTT_WORDS_MAX];
    uint16_t word_off[ZIV_UTT_WORDS_MAX];    /* offset of each word's first letter in letters[] */
    uint16_t letters_len;
    uint8_t letters[ZIV_UTT_LETTERS_MAX];    /* every word's letters, packed, as indices 0..25 */
    bool body_pending;
    bool body_error;                         /* the relay said the body failed: play the error pattern at its turn */
    uint16_t spec_version;
    ziv_source source;
} ziv_utterance;

typedef enum {
    ZIV_UTT_OK = 0,
    ZIV_UTT_ERR_JSON,          /* not JSON, or not an object */
    ZIV_UTT_ERR_FIELD,         /* a required field is missing or has the wrong type */
    ZIV_UTT_ERR_WIRE_VERSION,  /* v is present and not 1 */
    ZIV_UTT_ERR_SPEC_VERSION,  /* spec_version is not HAPTIC_SPEC_VERSION: the band would guess */
    ZIV_UTT_ERR_KIND,          /* kind is not one the spec knows */
    ZIV_UTT_ERR_ID,            /* id is outside [0-9A-Za-z_-]{8,64} */
    ZIV_UTT_ERR_LETTERS,       /* a word or the mark is empty or has a character outside a-z */
    ZIV_UTT_ERR_OVER_CAP,      /* more than 64 words, a word over 32 letters, a mark over 8 */
    ZIV_UTT_ERR_TAIL,          /* prefix.tail names neither the kind's tail pattern nor the kind */
    ZIV_UTT_ERR_SOURCE,        /* source is not sender | echo | live */
    ZIV_UTT_ERR_EMPTY,         /* no words and body_pending is false */
    ZIV_UTT_ERR_COUNT
} ziv_utt_err;

struct cJSON;

/* Decode one utterance from its JSON text.  On any error *out is cleared
 * (utterance_clear) and nothing partial survives. */
ziv_utt_err utterance_decode_json(const char *json, size_t len, ziv_utterance *out);

/* The same, from an already-parsed object (a frame's "utterance" member). */
ziv_utt_err utterance_decode_object(const struct cJSON *obj, ziv_utterance *out);

/* Replace the words from a JSON array of lower-case strings (an
 * utterance.body frame).  On error the words are left as they were. */
ziv_utt_err utterance_decode_words(const struct cJSON *words_array, ziv_utterance *u);

/* Replace the words from C strings (the turn's body hand-off, tests). */
ziv_utt_err utterance_set_words(ziv_utterance *u, const char *const *words, uint8_t n);

void utterance_clear(ziv_utterance *u);

/* True when id is a valid utterance id ([0-9A-Za-z_-]{8,64}). */
bool utterance_valid_id(const char *id);

/* Word i as letter indices (len written) — NULL when i is out of range. */
const uint8_t *utterance_word(const ziv_utterance *u, uint8_t i, uint8_t *len);

/* Word i spelled into buf ("taxi"); returns the letter count, 0 if out of range. */
size_t utterance_word_text(const ziv_utterance *u, uint8_t i, char *buf, size_t cap);

/* Wire names mirrored by hand from the generated enums (the generated
 * header carries indices, not strings; the order is the spec's). */
const char *utterance_kind_name(haptic_kind k);      /* "message" | "reminder" | "error" | "system" */
int utterance_kind_from_name(const char *name);      /* -1 when unknown */
const char *utterance_pattern_id(haptic_pattern p);  /* "double-tap" ... "end-of-message" */
const char *utterance_source_name(ziv_source s);
int utterance_source_from_name(const char *name);
const char *utterance_err_name(ziv_utt_err e);

#endif /* ZIV_UTTERANCE_H */
