/*
 * utterance.c — decode a wire utterance into the band's compact image.
 *
 * Field checks follow schema/utterance.json (generated from ziv/wire.py).
 * `wearer` and `from` are required by the schema but carry nothing the
 * band renders, so they are not required here: refusing a message over a
 * field the device never reads would be a loud failure for no wearer
 * benefit.  Everything the band DOES render is checked to the letter.
 */
#include "utterance.h"

#include <string.h>
#include "cJSON.h"

/* --- name tables: the generated enums' order, spelled as the wire does --- */

static const char *const k_kind_names[HAPTIC_KIND_COUNT] = {
    "message", "reminder", "error", "system",
};

static const char *const k_pattern_ids[HAPTIC_PAT_COUNT] = {
    "double-tap", "triple-pulse", "long-buzz", "ramp-up", "heartbeat", "processing", "end-of-message",
};

static const char *const k_source_names[ZIV_SOURCE_COUNT] = {
    "sender", "echo", "live",
};

static const char *const k_err_names[ZIV_UTT_ERR_COUNT] = {
    "ok", "json", "field", "wire_version", "spec_version", "kind", "id",
    "letters", "over_cap", "tail", "source", "empty",
};

const char *utterance_kind_name(haptic_kind k)
{
    return ((unsigned) k < HAPTIC_KIND_COUNT) ? k_kind_names[k] : "?";
}

int utterance_kind_from_name(const char *name)
{
    if (name == NULL) { return -1; }
    for (int i = 0; i < (int) HAPTIC_KIND_COUNT; i++) {
        if (strcmp(k_kind_names[i], name) == 0) { return i; }
    }
    return -1;
}

const char *utterance_pattern_id(haptic_pattern p)
{
    return ((unsigned) p < HAPTIC_PAT_COUNT) ? k_pattern_ids[p] : "?";
}

const char *utterance_source_name(ziv_source s)
{
    return ((unsigned) s < ZIV_SOURCE_COUNT) ? k_source_names[s] : "?";
}

int utterance_source_from_name(const char *name)
{
    if (name == NULL) { return -1; }
    for (int i = 0; i < (int) ZIV_SOURCE_COUNT; i++) {
        if (strcmp(k_source_names[i], name) == 0) { return i; }
    }
    return -1;
}

const char *utterance_err_name(ziv_utt_err e)
{
    return ((unsigned) e < ZIV_UTT_ERR_COUNT) ? k_err_names[e] : "?";
}

/* --- helpers ------------------------------------------------------------ */

void utterance_clear(ziv_utterance *u)
{
    memset(u, 0, sizeof *u);
}

static bool id_char(char c)
{
    return (c >= '0' && c <= '9') || (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '_' || c == '-';
}

bool utterance_valid_id(const char *id)
{
    if (id == NULL) { return false; }
    size_t n = 0;
    while (id[n] != '\0') {
        if (!id_char(id[n])) { return false; }
        if (++n > ZIV_UTT_ID_MAX) { return false; }
    }
    return n >= ZIV_UTT_ID_MIN;
}

/* Validate a-z and copy as letter indices; distinct errors for a bad
 * letter and for a word over the cap.  Returns the letter count in *len. */
static ziv_utt_err letters_of(const char *s, uint8_t cap, uint8_t *out, uint8_t *len)
{
    uint8_t n = 0;
    while (s[n] != '\0') {
        if (s[n] < 'a' || s[n] > 'z') { return ZIV_UTT_ERR_LETTERS; }
        if (n >= cap) { return ZIV_UTT_ERR_OVER_CAP; }
        out[n] = (uint8_t) (s[n] - 'a');
        n++;
    }
    if (n == 0) { return ZIV_UTT_ERR_LETTERS; }
    *len = n;
    return ZIV_UTT_OK;
}

/* Append one word (validated letters) to the packed store. */
static ziv_utt_err push_word(ziv_utterance *u, const char *s)
{
    if (u->word_count >= ZIV_UTT_WORDS_MAX) { return ZIV_UTT_ERR_OVER_CAP; }
    uint8_t tmp[ZIV_UTT_WORD_MAX];
    uint8_t n = 0;
    ziv_utt_err err = letters_of(s, ZIV_UTT_WORD_MAX, tmp, &n);
    if (err != ZIV_UTT_OK) { return err; }
    if ((size_t) u->letters_len + n > ZIV_UTT_LETTERS_MAX) { return ZIV_UTT_ERR_OVER_CAP; }
    u->word_off[u->word_count] = u->letters_len;
    u->word_len[u->word_count] = n;
    memcpy(&u->letters[u->letters_len], tmp, n);
    u->letters_len = (uint16_t) (u->letters_len + n);
    u->word_count++;
    return ZIV_UTT_OK;
}

static void drop_words(ziv_utterance *u)
{
    u->word_count = 0;
    u->letters_len = 0;
}

ziv_utt_err utterance_set_words(ziv_utterance *u, const char *const *words, uint8_t n)
{
    if (n > ZIV_UTT_WORDS_MAX) { return ZIV_UTT_ERR_OVER_CAP; }
    ziv_utterance tmp = *u;   /* all or nothing */
    drop_words(&tmp);
    for (uint8_t i = 0; i < n; i++) {
        if (words == NULL || words[i] == NULL) { return ZIV_UTT_ERR_FIELD; }
        ziv_utt_err err = push_word(&tmp, words[i]);
        if (err != ZIV_UTT_OK) { return err; }
    }
    *u = tmp;
    return ZIV_UTT_OK;
}

ziv_utt_err utterance_decode_words(const cJSON *arr, ziv_utterance *u)
{
    if (!cJSON_IsArray(arr)) { return ZIV_UTT_ERR_FIELD; }
    int count = cJSON_GetArraySize(arr);
    if (count > ZIV_UTT_WORDS_MAX) { return ZIV_UTT_ERR_OVER_CAP; }
    ziv_utterance tmp = *u;   /* all or nothing */
    drop_words(&tmp);
    const cJSON *item = NULL;
    cJSON_ArrayForEach(item, arr) {
        if (!cJSON_IsString(item) || item->valuestring == NULL) { return ZIV_UTT_ERR_FIELD; }
        ziv_utt_err err = push_word(&tmp, item->valuestring);
        if (err != ZIV_UTT_OK) { return err; }
    }
    *u = tmp;
    return ZIV_UTT_OK;
}

const uint8_t *utterance_word(const ziv_utterance *u, uint8_t i, uint8_t *len)
{
    if (i >= u->word_count) { if (len) { *len = 0; } return NULL; }
    if (len) { *len = u->word_len[i]; }
    return &u->letters[u->word_off[i]];
}

size_t utterance_word_text(const ziv_utterance *u, uint8_t i, char *buf, size_t cap)
{
    if (cap == 0) { return 0; }
    buf[0] = '\0';
    uint8_t n = 0;
    const uint8_t *w = utterance_word(u, i, &n);
    if (w == NULL || (size_t) n + 1 > cap) { return 0; }
    for (uint8_t k = 0; k < n; k++) { buf[k] = (char) ('a' + w[k]); }
    buf[n] = '\0';
    return n;
}

/* --- the decoder --------------------------------------------------------- */

static ziv_utt_err decode_into(const cJSON *obj, ziv_utterance *u)
{
    if (!cJSON_IsObject(obj)) { return ZIV_UTT_ERR_JSON; }

    const cJSON *v = cJSON_GetObjectItemCaseSensitive(obj, "v");
    if (v != NULL) {
        if (!cJSON_IsNumber(v)) { return ZIV_UTT_ERR_FIELD; }
        if (v->valuedouble != (double) ZIV_WIRE_VERSION) { return ZIV_UTT_ERR_WIRE_VERSION; }
    }

    const cJSON *spec = cJSON_GetObjectItemCaseSensitive(obj, "spec_version");
    if (!cJSON_IsNumber(spec)) { return ZIV_UTT_ERR_FIELD; }
    if (spec->valuedouble != (double) HAPTIC_SPEC_VERSION) { return ZIV_UTT_ERR_SPEC_VERSION; }
    u->spec_version = (uint16_t) HAPTIC_SPEC_VERSION;

    const cJSON *id = cJSON_GetObjectItemCaseSensitive(obj, "id");
    if (!cJSON_IsString(id) || id->valuestring == NULL) { return ZIV_UTT_ERR_FIELD; }
    if (!utterance_valid_id(id->valuestring)) { return ZIV_UTT_ERR_ID; }
    strncpy(u->id, id->valuestring, ZIV_UTT_ID_MAX);
    u->id[ZIV_UTT_ID_MAX] = '\0';

    const cJSON *kind = cJSON_GetObjectItemCaseSensitive(obj, "kind");
    if (!cJSON_IsString(kind) || kind->valuestring == NULL) { return ZIV_UTT_ERR_FIELD; }
    int ki = utterance_kind_from_name(kind->valuestring);
    if (ki < 0) { return ZIV_UTT_ERR_KIND; }
    u->kind = (haptic_kind) ki;
    u->tail = HAPTIC_KIND_TAIL_TABLE[u->kind];

    const cJSON *prefix = cJSON_GetObjectItemCaseSensitive(obj, "prefix");
    if (prefix != NULL && !cJSON_IsNull(prefix)) {
        if (!cJSON_IsObject(prefix)) { return ZIV_UTT_ERR_FIELD; }
        const cJSON *mark = cJSON_GetObjectItemCaseSensitive(prefix, "mark");
        const cJSON *tail = cJSON_GetObjectItemCaseSensitive(prefix, "tail");
        if (!cJSON_IsString(mark) || mark->valuestring == NULL) { return ZIV_UTT_ERR_FIELD; }
        if (!cJSON_IsString(tail) || tail->valuestring == NULL) { return ZIV_UTT_ERR_FIELD; }
        ziv_utt_err err = letters_of(mark->valuestring, ZIV_UTT_MARK_MAX, u->mark, &u->mark_len);
        if (err != ZIV_UTT_OK) { return err; }
        /* the tail after the mark is the kind's; the wire may spell it as
         * the pattern id or as the kind name, and it must agree */
        if (strcmp(tail->valuestring, utterance_pattern_id(u->tail)) != 0
            && strcmp(tail->valuestring, utterance_kind_name(u->kind)) != 0) {
            return ZIV_UTT_ERR_TAIL;
        }
        u->has_prefix = true;
    }

    const cJSON *words = cJSON_GetObjectItemCaseSensitive(obj, "words");
    if (words != NULL && !cJSON_IsNull(words)) {
        ziv_utt_err err = utterance_decode_words(words, u);
        if (err != ZIV_UTT_OK) { return err; }
    }

    const cJSON *pending = cJSON_GetObjectItemCaseSensitive(obj, "body_pending");
    if (pending != NULL && !cJSON_IsNull(pending)) {
        if (!cJSON_IsBool(pending)) { return ZIV_UTT_ERR_FIELD; }
        u->body_pending = cJSON_IsTrue(pending) ? true : false;
    }

    const cJSON *source = cJSON_GetObjectItemCaseSensitive(obj, "source");
    if (source != NULL && !cJSON_IsNull(source)) {
        if (!cJSON_IsString(source) || source->valuestring == NULL) { return ZIV_UTT_ERR_FIELD; }
        int si = utterance_source_from_name(source->valuestring);
        if (si < 0) { return ZIV_UTT_ERR_SOURCE; }
        u->source = (ziv_source) si;
    }

    if (u->word_count == 0 && !u->body_pending) { return ZIV_UTT_ERR_EMPTY; }
    return ZIV_UTT_OK;
}

ziv_utt_err utterance_decode_object(const cJSON *obj, ziv_utterance *out)
{
    utterance_clear(out);
    ziv_utt_err err = decode_into(obj, out);
    if (err != ZIV_UTT_OK) { utterance_clear(out); }
    return err;
}

ziv_utt_err utterance_decode_json(const char *json, size_t len, ziv_utterance *out)
{
    utterance_clear(out);
    if (json == NULL) { return ZIV_UTT_ERR_JSON; }
    cJSON *root = cJSON_ParseWithLength(json, len);
    if (root == NULL) { return ZIV_UTT_ERR_JSON; }
    ziv_utt_err err = decode_into(root, out);
    cJSON_Delete(root);
    if (err != ZIV_UTT_OK) { utterance_clear(out); }
    return err;
}
