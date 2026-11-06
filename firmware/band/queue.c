/*
 * queue.c — bounded, de-duplicated utterance queue with a byte image.
 *
 * Image layout (little-endian, all lengths explicit):
 *   'Z' 'Q' version(1) count(1) last_acked_len(1) last_acked[…]
 *   per utterance: id_len(1) id[…] kind(1) flags(1: bit0 has_prefix, bit1 body_pending, bit2 body_error)
 *                  source(1) spec_version(2) mark_len(1) mark[…]
 *                  word_count(1) { word_len(1) letters[…] }*
 */
#include "queue.h"

#include <string.h>

#define BLOB_MAGIC0 'Z'
#define BLOB_MAGIC1 'Q'
#define BLOB_VERSION 1

void band_queue_init(band_queue *q, const band_queue_store *store)
{
    memset(q, 0, sizeof *q);
    q->store = store;
}

static uint8_t slot_of(const band_queue *q, uint8_t pos)
{
    return (uint8_t) ((q->head + pos) % BAND_QUEUE_CAP);
}

static int index_of(const band_queue *q, const char *id)
{
    if (id == NULL) { return -1; }
    for (uint8_t i = 0; i < q->count; i++) {
        if (strcmp(q->items[slot_of(q, i)].id, id) == 0) { return (int) i; }
    }
    return -1;
}

band_queue_err band_queue_push(band_queue *q, const ziv_utterance *u)
{
    if (index_of(q, u->id) >= 0) { return BAND_QUEUE_DUPLICATE; }
    if (q->count >= BAND_QUEUE_CAP) { return BAND_QUEUE_FULL; }
    q->items[slot_of(q, q->count)] = *u;
    q->count++;
    return BAND_QUEUE_OK;
}

const ziv_utterance *band_queue_peek(const band_queue *q)
{
    return q->count ? &q->items[q->head] : NULL;
}

ziv_utterance *band_queue_find(band_queue *q, const char *id)
{
    int i = index_of(q, id);
    return (i < 0) ? NULL : &q->items[slot_of(q, (uint8_t) i)];
}

bool band_queue_holds(const band_queue *q, const char *id)
{
    return index_of(q, id) >= 0;
}

band_queue_err band_queue_pop(band_queue *q)
{
    if (q->count == 0) { return BAND_QUEUE_EMPTY; }
    utterance_clear(&q->items[q->head]);
    q->head = (uint8_t) ((q->head + 1) % BAND_QUEUE_CAP);
    q->count--;
    return BAND_QUEUE_OK;
}

band_queue_err band_queue_ack(band_queue *q)
{
    if (q->count == 0) { return BAND_QUEUE_EMPTY; }
    band_queue_set_last_acked(q, q->items[q->head].id);
    return band_queue_pop(q);
}

band_queue_err band_queue_cancel(band_queue *q, const char *id)
{
    int i = index_of(q, id);
    if (i < 0) { return BAND_QUEUE_NOT_FOUND; }
    /* shift the tail down one slot */
    for (uint8_t k = (uint8_t) i; k + 1 < q->count; k++) {
        q->items[slot_of(q, k)] = q->items[slot_of(q, (uint8_t) (k + 1))];
    }
    utterance_clear(&q->items[slot_of(q, (uint8_t) (q->count - 1))]);
    q->count--;
    return BAND_QUEUE_OK;
}

uint8_t band_queue_ids(const band_queue *q, const char **ids, uint8_t cap)
{
    uint8_t n = 0;
    for (uint8_t i = 0; i < q->count && n < cap; i++) {
        ids[n++] = q->items[slot_of(q, i)].id;
    }
    return n;
}

uint8_t band_queue_count(const band_queue *q) { return q->count; }

const char *band_queue_last_acked(const band_queue *q) { return q->last_acked; }

void band_queue_set_last_acked(band_queue *q, const char *id)
{
    if (id == NULL) { q->last_acked[0] = '\0'; return; }
    strncpy(q->last_acked, id, ZIV_UTT_ID_MAX);
    q->last_acked[ZIV_UTT_ID_MAX] = '\0';
}

/* --- byte image ------------------------------------------------------------- */

typedef struct { uint8_t *p; size_t cap; size_t len; bool overflow; } writer;

static void put8(writer *w, uint8_t v)
{
    if (w->len < w->cap) { w->p[w->len] = v; } else { w->overflow = true; }
    w->len++;
}

static void put16(writer *w, uint16_t v)
{
    put8(w, (uint8_t) (v & 0xFF));
    put8(w, (uint8_t) (v >> 8));
}

static void put_bytes(writer *w, const void *src, size_t n)
{
    const uint8_t *s = (const uint8_t *) src;
    for (size_t i = 0; i < n; i++) { put8(w, s[i]); }
}

size_t band_queue_encode(const band_queue *q, uint8_t *blob, size_t cap)
{
    writer w = { blob, cap, 0, false };
    put8(&w, BLOB_MAGIC0);
    put8(&w, BLOB_MAGIC1);
    put8(&w, BLOB_VERSION);
    put8(&w, q->count);
    uint8_t la = (uint8_t) strlen(q->last_acked);
    put8(&w, la);
    put_bytes(&w, q->last_acked, la);
    for (uint8_t i = 0; i < q->count; i++) {
        const ziv_utterance *u = &q->items[slot_of(q, i)];
        uint8_t idl = (uint8_t) strlen(u->id);
        put8(&w, idl);
        put_bytes(&w, u->id, idl);
        put8(&w, (uint8_t) u->kind);
        put8(&w, (uint8_t) ((u->has_prefix ? 1u : 0u) | (u->body_pending ? 2u : 0u) | (u->body_error ? 4u : 0u)));
        put8(&w, (uint8_t) u->source);
        put16(&w, u->spec_version);
        put8(&w, u->mark_len);
        put_bytes(&w, u->mark, u->mark_len);
        put8(&w, u->word_count);
        for (uint8_t k = 0; k < u->word_count; k++) {
            put8(&w, u->word_len[k]);
            put_bytes(&w, &u->letters[u->word_off[k]], u->word_len[k]);
        }
    }
    return w.overflow ? 0 : w.len;
}

typedef struct { const uint8_t *p; size_t len; size_t pos; bool bad; } reader;

static uint8_t get8(reader *r)
{
    if (r->pos < r->len) { return r->p[r->pos++]; }
    r->bad = true;
    return 0;
}

static uint16_t get16(reader *r)
{
    uint16_t lo = get8(r);
    uint16_t hi = get8(r);
    return (uint16_t) (lo | (hi << 8));
}

static void get_bytes(reader *r, void *dst, size_t n)
{
    uint8_t *d = (uint8_t *) dst;
    for (size_t i = 0; i < n; i++) { d[i] = get8(r); }
}

band_queue_err band_queue_decode(band_queue *q, const uint8_t *blob, size_t len)
{
    reader r = { blob, len, 0, false };
    if (get8(&r) != BLOB_MAGIC0 || get8(&r) != BLOB_MAGIC1 || get8(&r) != BLOB_VERSION) {
        return BAND_QUEUE_STORE_ERR;
    }
    band_queue tmp;
    band_queue_init(&tmp, q->store);
    uint8_t count = get8(&r);
    if (count > BAND_QUEUE_CAP) { return BAND_QUEUE_STORE_ERR; }
    uint8_t la = get8(&r);
    if (la > ZIV_UTT_ID_MAX) { return BAND_QUEUE_STORE_ERR; }
    get_bytes(&r, tmp.last_acked, la);
    tmp.last_acked[la] = '\0';
    for (uint8_t i = 0; i < count; i++) {
        ziv_utterance *u = &tmp.items[i];
        uint8_t idl = get8(&r);
        if (idl > ZIV_UTT_ID_MAX) { return BAND_QUEUE_STORE_ERR; }
        get_bytes(&r, u->id, idl);
        u->id[idl] = '\0';
        uint8_t kind = get8(&r);
        if (kind >= HAPTIC_KIND_COUNT) { return BAND_QUEUE_STORE_ERR; }
        u->kind = (haptic_kind) kind;
        u->tail = HAPTIC_KIND_TAIL_TABLE[u->kind];
        uint8_t flags = get8(&r);
        u->has_prefix = (flags & 1u) != 0;
        u->body_pending = (flags & 2u) != 0;
        u->body_error = (flags & 4u) != 0;
        uint8_t source = get8(&r);
        if (source >= ZIV_SOURCE_COUNT) { return BAND_QUEUE_STORE_ERR; }
        u->source = (ziv_source) source;
        u->spec_version = get16(&r);
        u->mark_len = get8(&r);
        if (u->mark_len > ZIV_UTT_MARK_MAX) { return BAND_QUEUE_STORE_ERR; }
        get_bytes(&r, u->mark, u->mark_len);
        u->word_count = get8(&r);
        if (u->word_count > ZIV_UTT_WORDS_MAX) { return BAND_QUEUE_STORE_ERR; }
        for (uint8_t k = 0; k < u->word_count; k++) {
            uint8_t wl = get8(&r);
            if (wl == 0 || wl > ZIV_UTT_WORD_MAX) { return BAND_QUEUE_STORE_ERR; }
            if ((size_t) u->letters_len + wl > ZIV_UTT_LETTERS_MAX) { return BAND_QUEUE_STORE_ERR; }
            u->word_off[k] = u->letters_len;
            u->word_len[k] = wl;
            get_bytes(&r, &u->letters[u->letters_len], wl);
            u->letters_len = (uint16_t) (u->letters_len + wl);
        }
        for (uint16_t k = 0; k < u->letters_len; k++) {
            if (u->letters[k] >= HAPTIC_LETTERS) { return BAND_QUEUE_STORE_ERR; }
        }
        for (uint8_t k = 0; k < u->mark_len; k++) {
            if (u->mark[k] >= HAPTIC_LETTERS) { return BAND_QUEUE_STORE_ERR; }
        }
        if (!utterance_valid_id(u->id)) { return BAND_QUEUE_STORE_ERR; }
        if (r.bad) { return BAND_QUEUE_STORE_ERR; }
    }
    if (r.bad || r.pos != len) { return BAND_QUEUE_STORE_ERR; }
    tmp.head = 0;
    tmp.count = count;
    *q = tmp;
    return BAND_QUEUE_OK;
}

band_queue_err band_queue_save(const band_queue *q, uint8_t *blob, size_t cap)
{
    if (q->store == NULL || q->store->save == NULL) { return BAND_QUEUE_OK; }
    size_t len = band_queue_encode(q, blob, cap);
    if (len == 0) { return BAND_QUEUE_BLOB_TOO_SMALL; }
    return q->store->save(q->store->ctx, blob, len) == 0 ? BAND_QUEUE_OK : BAND_QUEUE_STORE_ERR;
}

band_queue_err band_queue_load(band_queue *q, uint8_t *blob, size_t cap)
{
    if (q->store == NULL || q->store->load == NULL) { return BAND_QUEUE_OK; }
    size_t len = 0;
    if (q->store->load(q->store->ctx, blob, cap, &len) != 0) { return BAND_QUEUE_STORE_ERR; }
    if (len == 0) { return BAND_QUEUE_OK; }   /* nothing stored yet */
    return band_queue_decode(q, blob, len);
}
