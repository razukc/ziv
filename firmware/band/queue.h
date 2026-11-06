/*
 * queue.h — the band's bounded utterance queue (architecture §5.1, §4.3).
 *
 * Holds up to BAND_QUEUE_CAP utterances in arrival order, de-duplicated by
 * id (redelivery after a reconnect is the normal case, never a double
 * play).  The head is what the turn plays next; popping it after the
 * close records the id as last_acked, which the next `hello` carries so
 * the relay resends only what is missing.
 *
 * Persistence is a vtable: save(blob) / load(blob) over one compact byte
 * image of the whole queue.  The host binds a file (host/queue_file_host.c),
 * the band binds NVS (esp/queue_nvs_esp.c).  The image carries no pointers
 * and no durations — only ids, kinds, letters and flags.
 *
 * Host-portable: no ESP-IDF types.
 */
#ifndef ZIV_BAND_QUEUE_H
#define ZIV_BAND_QUEUE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "utterance.h"

#define BAND_QUEUE_CAP 20

typedef enum {
    BAND_QUEUE_OK = 0,
    BAND_QUEUE_DUPLICATE,    /* an utterance with this id is already held (not an error on the wire) */
    BAND_QUEUE_FULL,         /* at the cap: the transport nacks queue_full */
    BAND_QUEUE_NOT_FOUND,
    BAND_QUEUE_EMPTY,
    BAND_QUEUE_STORE_ERR,    /* the persistence adapter failed, or the blob is malformed */
    BAND_QUEUE_BLOB_TOO_SMALL
} band_queue_err;

/* Persistence adapter.  save: write len bytes; load: read up to cap bytes
 * and report how many (0 when nothing is stored).  Both return 0 on
 * success, -1 on failure. */
typedef struct {
    int (*save)(void *ctx, const uint8_t *blob, size_t len);
    int (*load)(void *ctx, uint8_t *blob, size_t cap, size_t *len);
    void *ctx;
} band_queue_store;

typedef struct {
    ziv_utterance items[BAND_QUEUE_CAP];
    uint8_t head;                     /* ring: items[head] is the next to play */
    uint8_t count;
    char last_acked[ZIV_UTT_ID_MAX + 1];
    const band_queue_store *store;    /* NULL = no persistence */
} band_queue;

/* Worst-case image: header + every slot at its largest.  Callers size the
 * blob buffer with this (a file / NVS blob of this size is the ceiling). */
#define BAND_QUEUE_ITEM_BLOB_MAX \
    (1 + ZIV_UTT_ID_MAX + 1 + 1 + 1 + 2 + 1 + ZIV_UTT_MARK_MAX + 1 + ZIV_UTT_WORDS_MAX + ZIV_UTT_LETTERS_MAX)
#define BAND_QUEUE_BLOB_MAX (8 + 1 + ZIV_UTT_ID_MAX + BAND_QUEUE_CAP * BAND_QUEUE_ITEM_BLOB_MAX)

void band_queue_init(band_queue *q, const band_queue_store *store);

/* Append (copy).  DUPLICATE when the id is already held; FULL at the cap. */
band_queue_err band_queue_push(band_queue *q, const ziv_utterance *u);

const ziv_utterance *band_queue_peek(const band_queue *q);   /* NULL when empty */
ziv_utterance *band_queue_find(band_queue *q, const char *id);   /* NULL when not held */
bool band_queue_holds(const band_queue *q, const char *id);

/* Remove the head without acknowledging it (a cancel, a failure). */
band_queue_err band_queue_pop(band_queue *q);

/* Remove the head and record its id as last_acked (the close played). */
band_queue_err band_queue_ack(band_queue *q);

/* Remove any held utterance by id. */
band_queue_err band_queue_cancel(band_queue *q, const char *id);

/* The held ids in queue order; returns how many were written (≤ cap). */
uint8_t band_queue_ids(const band_queue *q, const char **ids, uint8_t cap);

uint8_t band_queue_count(const band_queue *q);
const char *band_queue_last_acked(const band_queue *q);   /* "" when none */
void band_queue_set_last_acked(band_queue *q, const char *id);

/* Serialize to / from a byte image (no I/O).  encode returns the length
 * written, 0 when the blob is too small. */
size_t band_queue_encode(const band_queue *q, uint8_t *blob, size_t cap);
band_queue_err band_queue_decode(band_queue *q, const uint8_t *blob, size_t len);

/* Through the store: encode + save, load + decode.  Without a store both
 * return BAND_QUEUE_OK and do nothing. */
band_queue_err band_queue_save(const band_queue *q, uint8_t *blob, size_t cap);
band_queue_err band_queue_load(band_queue *q, uint8_t *blob, size_t cap);

#endif /* ZIV_BAND_QUEUE_H */
