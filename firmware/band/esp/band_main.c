/*
 * band_main.c — the band's app_main (UNVERIFIED: written against ESP-IDF
 * 5.x, not compiled here — see README.md).
 *
 * Wires what the host already proved: the I2C bus → the sequencer → the
 * turn → the transport, with the queue in NVS and the websocket as the
 * frame adapter.  The loop is the same pull model as the bench and the
 * rung-1 app: transport_step(now) returns the next deadline and
 * transport_wait() blocks in the websocket inbox until then, so a frame
 * from the relay wakes the loop early and a beat deadline is never missed
 * by more than a tick.
 *
 * HAP lines (docs/QEMU_SIMULATION_LADDER.md) are printed from the turn's
 * beat callback — the sequencer's own BUZZ events — so the UART carries the
 * same testimony the bench asserts, with mode BEATS and the reference's
 * labels as payload.
 *
 * Chord-key input (input.text, the wearer's controls) is not wired: the
 * braille_in module does not exist yet.  transport_control() and
 * transport_send_input_text() are the calls it will make.
 */
#if defined(ESP_PLATFORM)

#include <stdio.h>
#include <string.h>
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#include "drv2605.h"
#include "drv2605_i2c_esp32.h"
#include "haptic_out.h"
#include "queue.h"
#include "transport.h"
#include "transport_ws_esp.h"
#include "turn.h"

static const char *TAG = "ziv_band";

static drv2605_bus s_bus;
static haptic_out s_haptic;
static turn s_turn;
static band_queue s_queue;
static band_queue_store s_store;
static band_transport s_transport;
static band_frame_io s_io;
static uint8_t s_blob[BAND_QUEUE_BLOB_MAX];
static EventGroupHandle_t s_wifi_events;
#define WIFI_CONNECTED_BIT (1u << 0)

static uint32_t now_ms(void)
{
    return (uint32_t) (esp_timer_get_time() / 1000);
}

/* --- HAP log from the sequencer's own events ------------------------------ */

static void on_beat(void *ctx, uint32_t now, const haptic_out_step_t *st, const char *label)
{
    (void) ctx;
    printf("HAP %lu BUZZ BEATS %s %02X %lu %lu %u\n", (unsigned long) now, label, (unsigned) st->dot_mask,
           (unsigned long) st->buzz_ms, (unsigned long) st->gap_after_ms, (unsigned) st->seq);
}

static void on_log(void *ctx, const char *line)
{
    (void) ctx;
    ESP_LOGI(TAG, "%s", line);
}

/* --- Wi-Fi station (the usual IDF dance) ---------------------------------- */

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void) arg; (void) data;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_wifi_events, WIFI_CONNECTED_BIT);
        esp_wifi_connect();   /* the transport's backoff paces the socket; the radio just retries */
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(s_wifi_events, WIFI_CONNECTED_BIT);
    }
}

static void wifi_start(void)
{
    s_wifi_events = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    wifi_config_t cfg;
    memset(&cfg, 0, sizeof cfg);
    strncpy((char *) cfg.sta.ssid, CONFIG_ZIV_WIFI_SSID, sizeof cfg.sta.ssid - 1);
    strncpy((char *) cfg.sta.password, CONFIG_ZIV_WIFI_PASSWORD, sizeof cfg.sta.password - 1);
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &cfg));
    ESP_ERROR_CHECK(esp_wifi_start());
}

/* --- the loop ---------------------------------------------------------------- */

static void band_loop(void *arg)
{
    (void) arg;
    /* the radio first; the queue plays offline meanwhile only once loaded below */
    xEventGroupWaitBits(s_wifi_events, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
    for (;;) {
        uint32_t now = now_ms();
        uint32_t next = transport_step(&s_transport, now);
        uint32_t wait = (next == 0) ? (uint32_t) WORKING_EVERY_MS : (next > now ? next - now : 0);
        /* block in the websocket inbox until the deadline (a frame wakes us early) */
        if (transport_wait(&s_transport, now, wait) == 0 && !s_transport.connected && wait) {
            vTaskDelay(pdMS_TO_TICKS(wait));   /* offline: nothing to wait on but time */
        }
    }
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    }

    /* the bus and the sequencer */
    drv2605_esp32_pins pins = { CONFIG_ZIV_I2C_PORT, CONFIG_ZIV_I2C_SDA_GPIO, CONFIG_ZIV_I2C_SCL_GPIO, CONFIG_ZIV_I2C_HZ };
    if (drv2605_bus_esp32_init(&s_bus, &pins) != HAPTIC_OK) { ESP_LOGE(TAG, "I2C bus init failed"); }
    if (drv2605_init(&s_bus) != HAPTIC_OK) { ESP_LOGE(TAG, "DRV2605 init failed (check the mux wiring)"); }
    haptic_out_init(&s_haptic, &s_bus);

    /* the renderer contract */
#if CONFIG_ZIV_PROFILE_SINGLE_ACTUATOR
    turn_profile profile = TURN_PROFILE_SINGLE_ACTUATOR;
#else
    turn_profile profile = TURN_PROFILE_SIX_ACTUATOR;
#endif
    turn_init(&s_turn, &s_haptic, profile, CELL_GAP_DEFAULT_MS);
    turn_set_callbacks(&s_turn, NULL, NULL, on_beat, NULL);

    /* the queue, from NVS */
    queue_nvs_store(&s_store);
    band_queue_init(&s_queue, &s_store);
    if (band_queue_load(&s_queue, s_blob, sizeof s_blob) != BAND_QUEUE_OK) {
        ESP_LOGW(TAG, "stored queue unreadable; starting empty");
        band_queue_init(&s_queue, &s_store);
    }
    ESP_LOGI(TAG, "queue: %u held, last_acked '%s'", (unsigned) band_queue_count(&s_queue), band_queue_last_acked(&s_queue));

    /* the transport over the websocket */
    if (transport_ws_esp_init(&s_io, CONFIG_ZIV_RELAY_URI) != 0) { ESP_LOGE(TAG, "websocket client init failed"); }
    band_transport_config cfg;
    memset(&cfg, 0, sizeof cfg);
    cfg.device_key = CONFIG_ZIV_DEVICE_KEY;
    cfg.profile = profile;
    cfg.seed = (uint32_t) esp_timer_get_time();
    transport_init(&s_transport, &s_io, &s_queue, &s_turn, &cfg);
    transport_set_log(&s_transport, on_log, NULL);
    transport_set_blob(&s_transport, s_blob, sizeof s_blob);

    wifi_start();
    xTaskCreate(band_loop, "ziv_band", 8192, NULL, 5, NULL);
}

#else
typedef int band_main_is_device_only;
#endif /* ESP_PLATFORM */
