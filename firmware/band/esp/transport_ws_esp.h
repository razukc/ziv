/* transport_ws_esp.h — the websocket frame adapter (device only; compiled
 * against ESP-IDF 5.5 + espressif/esp_websocket_client, booted under QEMU
 * with no radio; a live relay connection is still unverified). */
#ifndef ZIV_TRANSPORT_WS_ESP_H
#define ZIV_TRANSPORT_WS_ESP_H

#include <stdbool.h>
#include "transport.h"
#include "queue.h"

/* Fill io with the esp_websocket_client adapter for uri.  0 ok, -1 failed. */
int transport_ws_esp_init(band_frame_io *io, const char *uri);

/* The link gate: connect() refuses (-1, fast) until the station has an IP,
 * so the protocol layer backs off instead of starting a socket on a stack
 * with no interface.  band_main.c flips it from the Wi-Fi/IP events; it
 * starts down, which is the whole QEMU boot (no radio there). */
void transport_ws_esp_set_link(bool up);

/* Fill store with the NVS adapter (queue_nvs_esp.c). */
void queue_nvs_store(band_queue_store *store);

#endif /* ZIV_TRANSPORT_WS_ESP_H */
