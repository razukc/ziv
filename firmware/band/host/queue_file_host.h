/* queue_file_host.h — the queue's persistence vtable bound to a file (host only). */
#ifndef ZIV_QUEUE_FILE_HOST_H
#define ZIV_QUEUE_FILE_HOST_H

#include "queue.h"

typedef struct {
    const char *path;
} queue_file_ctx;

/* Fill store for the file at ctx->path.  save() rewrites the whole file;
 * load() reports 0 bytes when the file does not exist. */
void queue_file_store(band_queue_store *store, queue_file_ctx *ctx);

#endif /* ZIV_QUEUE_FILE_HOST_H */
