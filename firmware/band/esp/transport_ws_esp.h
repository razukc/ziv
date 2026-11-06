/* transport_ws_esp.h — the websocket frame adapter (device only, UNVERIFIED). */
#ifndef ZIV_TRANSPORT_WS_ESP_H
#define ZIV_TRANSPORT_WS_ESP_H

#include "transport.h"
#include "queue.h"

/* Fill io with the esp_websocket_client adapter for uri.  0 ok, -1 failed. */
int transport_ws_esp_init(band_frame_io *io, const char *uri);

/* Fill store with the NVS adapter (queue_nvs_esp.c). */
void queue_nvs_store(band_queue_store *store);

#endif /* ZIV_TRANSPORT_WS_ESP_H */
