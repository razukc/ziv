/*
 * transport_ws_esp.c — the band_frame_io adapter on esp_websocket_client
 * (UNVERIFIED: written against ESP-IDF 5.x + espressif/esp_websocket_client
 * 1.x, not compiled here).
 *
 * The WebSocket does the framing, so this adapter only moves whole text
 * frames: the client's event handler copies each complete text message into
 * a heap buffer and posts the pointer on a FreeRTOS queue; recv_frame()
 * takes one with a timeout and copies it out.  connect() starts the client
 * and waits for the CONNECTED event; the protocol layer then sends `hello`
 * as the first frame, so the device key never appears in the URI.
 *
 * Fragmented messages (payload_offset > 0) are reassembled per frame up to
 * TRANSPORT_RX_MAX; anything larger is dropped and counted, never
 * truncated into a half frame.
 */
#if defined(ESP_PLATFORM)

#include <stdlib.h>
#include <string.h>
#include "esp_log.h"
#include "esp_websocket_client.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "transport.h"
#include "transport_ws_esp.h"

static const char *TAG = "ziv_ws";

#define WS_INBOX_DEPTH      8
#define WS_CONNECT_WAIT_MS  10000   /* adapter patience for the socket; not a haptic duration */
#define WS_SEND_WAIT_MS     5000
#define BIT_CONNECTED       (1u << 0)
#define BIT_DISCONNECTED    (1u << 1)

typedef struct { char *data; size_t len; } ws_msg;

typedef struct {
    esp_websocket_client_handle_t client;
    QueueHandle_t inbox;             /* ws_msg */
    EventGroupHandle_t events;
    char *assembling;                /* a fragmented text frame being rebuilt */
    size_t assembled;
    uint32_t dropped_oversize;
    bool gone;                       /* the link dropped: recv_frame reports -1 once */
} ws_ctx;

static ws_ctx s_ws;

static void inbox_push(ws_ctx *c, const char *data, size_t len)
{
    ws_msg m;
    m.data = (char *) malloc(len + 1);
    if (m.data == NULL) { return; }
    memcpy(m.data, data, len);
    m.data[len] = '\0';
    m.len = len;
    if (xQueueSend(c->inbox, &m, 0) != pdTRUE) {
        free(m.data);   /* the band is slower than the relay: drop, loudly */
        ESP_LOGW(TAG, "inbox full; frame dropped");
    }
}

static void ws_event(void *arg, esp_event_base_t base, int32_t event_id, void *event_data)
{
    (void) base;
    ws_ctx *c = (ws_ctx *) arg;
    esp_websocket_event_data_t *d = (esp_websocket_event_data_t *) event_data;
    switch (event_id) {
    case WEBSOCKET_EVENT_CONNECTED:
        xEventGroupClearBits(c->events, BIT_DISCONNECTED);
        xEventGroupSetBits(c->events, BIT_CONNECTED);
        break;
    case WEBSOCKET_EVENT_DISCONNECTED:
    case WEBSOCKET_EVENT_ERROR:
    case WEBSOCKET_EVENT_CLOSED:
        c->gone = true;
        xEventGroupClearBits(c->events, BIT_CONNECTED);
        xEventGroupSetBits(c->events, BIT_DISCONNECTED);
        break;
    case WEBSOCKET_EVENT_DATA:
        if (d->op_code != 0x1) { break; }   /* text frames only; pings are the client's */
        if (d->payload_len > TRANSPORT_RX_MAX) {
            c->dropped_oversize++;
            break;
        }
        if (d->payload_offset == 0 && d->data_len == d->payload_len) {
            inbox_push(c, d->data_ptr, (size_t) d->data_len);
            break;
        }
        /* a fragment: rebuild */
        if (d->payload_offset == 0) {
            free(c->assembling);
            c->assembling = (char *) malloc((size_t) d->payload_len);
            c->assembled = 0;
        }
        if (c->assembling == NULL) { break; }
        if ((size_t) d->payload_offset + (size_t) d->data_len <= (size_t) d->payload_len) {
            memcpy(c->assembling + d->payload_offset, d->data_ptr, (size_t) d->data_len);
            c->assembled = (size_t) d->payload_offset + (size_t) d->data_len;
        }
        if (c->assembled == (size_t) d->payload_len) {
            inbox_push(c, c->assembling, c->assembled);
            free(c->assembling);
            c->assembling = NULL;
            c->assembled = 0;
        }
        break;
    default:
        break;
    }
}

static int ws_connect(void *vctx)
{
    ws_ctx *c = (ws_ctx *) vctx;
    c->gone = false;
    xEventGroupClearBits(c->events, BIT_CONNECTED | BIT_DISCONNECTED);
    if (esp_websocket_client_start(c->client) != ESP_OK) { return -1; }
    EventBits_t bits = xEventGroupWaitBits(c->events, BIT_CONNECTED | BIT_DISCONNECTED, pdFALSE, pdFALSE,
                                           pdMS_TO_TICKS(WS_CONNECT_WAIT_MS));
    if (bits & BIT_CONNECTED) { return 0; }
    (void) esp_websocket_client_stop(c->client);
    return -1;
}

static int ws_send(void *vctx, const char *text, size_t len)
{
    ws_ctx *c = (ws_ctx *) vctx;
    if (c->gone) { return -1; }
    int n = esp_websocket_client_send_text(c->client, text, (int) len, pdMS_TO_TICKS(WS_SEND_WAIT_MS));
    return (n == (int) len) ? 0 : -1;
}

static int ws_recv(void *vctx, char *buf, size_t cap, uint32_t timeout_ms)
{
    ws_ctx *c = (ws_ctx *) vctx;
    ws_msg m;
    if (xQueueReceive(c->inbox, &m, pdMS_TO_TICKS(timeout_ms)) != pdTRUE) {
        return c->gone ? -1 : 0;
    }
    if (m.len + 1 > cap) { free(m.data); return -1; }   /* does not fit: the link drops, no half frame */
    memcpy(buf, m.data, m.len + 1);
    free(m.data);
    return (int) m.len;
}

static void ws_close(void *vctx)
{
    ws_ctx *c = (ws_ctx *) vctx;
    (void) esp_websocket_client_close(c->client, pdMS_TO_TICKS(WS_SEND_WAIT_MS));
    (void) esp_websocket_client_stop(c->client);
    ws_msg m;
    while (xQueueReceive(c->inbox, &m, 0) == pdTRUE) { free(m.data); }
    c->gone = true;
}

int transport_ws_esp_init(band_frame_io *io, const char *uri)
{
    esp_websocket_client_config_t cfg = {
        .uri = uri,
        .buffer_size = TRANSPORT_RX_MAX,
        .disable_auto_reconnect = true,   /* the protocol layer owns backoff and resume */
    };
    s_ws.client = esp_websocket_client_init(&cfg);
    if (s_ws.client == NULL) { return -1; }
    s_ws.inbox = xQueueCreate(WS_INBOX_DEPTH, sizeof(ws_msg));
    s_ws.events = xEventGroupCreate();
    if (s_ws.inbox == NULL || s_ws.events == NULL) { return -1; }
    if (esp_websocket_register_events(s_ws.client, WEBSOCKET_EVENT_ANY, ws_event, &s_ws) != ESP_OK) { return -1; }
    io->connect = ws_connect;
    io->send_frame = ws_send;
    io->recv_frame = ws_recv;
    io->close = ws_close;
    io->ctx = &s_ws;
    return 0;
}

#else
typedef int transport_ws_esp_is_device_only;
#endif /* ESP_PLATFORM */
