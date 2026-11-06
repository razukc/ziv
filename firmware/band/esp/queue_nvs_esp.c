/*
 * queue_nvs_esp.c — the queue's persistence vtable on NVS.  Compiled against
 * ESP-IDF v5.5 and exercised at every QEMU boot (the load of an empty
 * namespace: "queue: 0 held"); a save after a real utterance is still
 * unverified.
 *
 * One blob under namespace "ziv", key "queue": the byte image
 * band_queue_encode() produces (ids, kinds, letters, flags — no durations).
 * Written after every change the transport makes to the queue; read once at
 * boot so a power cycle keeps what the wearer has not yet felt and the
 * last_acked id the next hello resumes from.
 */
#if defined(ESP_PLATFORM)

#include <string.h>
#include "nvs.h"
#include "nvs_flash.h"
#include "esp_log.h"
#include "queue.h"

static const char *TAG = "ziv_nvs";
#define NVS_NAMESPACE "ziv"
#define NVS_KEY_QUEUE "queue"

static int nvs_save(void *ctx, const uint8_t *blob, size_t len)
{
    (void) ctx;
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h) != ESP_OK) { return -1; }
    esp_err_t err = nvs_set_blob(h, NVS_KEY_QUEUE, blob, len);
    if (err == ESP_OK) { err = nvs_commit(h); }
    nvs_close(h);
    if (err != ESP_OK) { ESP_LOGW(TAG, "queue save failed: %s", esp_err_to_name(err)); return -1; }
    return 0;
}

static int nvs_load(void *ctx, uint8_t *blob, size_t cap, size_t *len)
{
    (void) ctx;
    *len = 0;
    nvs_handle_t h;
    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &h) != ESP_OK) { return 0; }   /* nothing stored yet */
    size_t stored = 0;
    esp_err_t err = nvs_get_blob(h, NVS_KEY_QUEUE, NULL, &stored);
    if (err == ESP_ERR_NVS_NOT_FOUND) { nvs_close(h); return 0; }
    if (err != ESP_OK) { nvs_close(h); return -1; }
    if (stored > cap) { nvs_close(h); ESP_LOGW(TAG, "stored queue larger than the buffer"); return -1; }   /* refuse, never truncate */
    err = nvs_get_blob(h, NVS_KEY_QUEUE, blob, &stored);
    nvs_close(h);
    if (err != ESP_OK) { return -1; }
    *len = stored;
    return 0;
}

void queue_nvs_store(band_queue_store *store)
{
    store->save = nvs_save;
    store->load = nvs_load;
    store->ctx = NULL;
}

#else
/* host builds never include this file; the symbol keeps -Wempty-translation-unit quiet if one does */
typedef int queue_nvs_esp_is_device_only;
#endif /* ESP_PLATFORM */
