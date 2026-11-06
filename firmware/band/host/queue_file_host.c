/* queue_file_host.c — the queue image in a plain file (host only). */
#include "queue_file_host.h"

#include <stdio.h>

static int file_save(void *vctx, const uint8_t *blob, size_t len)
{
    queue_file_ctx *ctx = (queue_file_ctx *) vctx;
    FILE *f = fopen(ctx->path, "wb");
    if (f == NULL) { return -1; }
    size_t n = fwrite(blob, 1, len, f);
    int rc = (fclose(f) == 0 && n == len) ? 0 : -1;
    return rc;
}

static int file_load(void *vctx, uint8_t *blob, size_t cap, size_t *len)
{
    queue_file_ctx *ctx = (queue_file_ctx *) vctx;
    *len = 0;
    FILE *f = fopen(ctx->path, "rb");
    if (f == NULL) { return 0; }   /* nothing stored yet */
    size_t n = fread(blob, 1, cap, f);
    int more = fgetc(f);
    fclose(f);
    if (more != EOF) { return -1; }   /* larger than the buffer: refuse, do not truncate */
    *len = n;
    return 0;
}

void queue_file_store(band_queue_store *store, queue_file_ctx *ctx)
{
    store->save = file_save;
    store->load = file_load;
    store->ctx = ctx;
}
