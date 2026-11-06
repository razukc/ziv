/*
 * band_main.c — the band's app_main.
 *
 * Compiled against ESP-IDF v5.5 (esp32s3) and booted under Espressif QEMU
 * with the default config (mock haptic bus, no radio); a real board, real
 * motors and a live Wi-Fi/relay link are still unverified — README.md says
 * exactly what is and is not proven.
 *
 * Wires what the host already proved: the bus → the sequencer → the turn →
 * the transport, with the queue in NVS and the websocket as the frame
 * adapter.  The loop is the same pull model as the bench and the rung-1
 * app: transport_step(now) returns the next deadline; connected, the loop
 * blocks in the websocket inbox until then (a frame from the relay wakes it
 * early); offline, it sleeps until the deadline or until the link flips.
 *
 * Boot order (what the QEMU log shows): NVS → the haptic bus (mock or I2C
 * per CONFIG_ZIV_BAND_HAPTIC_MOCK) → the sequencer → the queue from NVS →
 * the transport → Wi-Fi if an SSID is configured (otherwise a WARN line and
 * the radio stays off) → the loop task, which first plays the boot ramp-up
 * on the sequencer (HAP lines in the rung-1 format, mode PATTERN) and then
 * runs the transport, which backs off while the link is down.
 *
 * HAP lines (docs/QEMU_SIMULATION_LADDER.md) are printed from the
 * sequencer's own events — the boot ramp-up directly, the utterances from
 * the turn's beat callback (mode BEATS, the reference's labels as payload)
 * — so the UART carries the same testimony the bench asserts.  at_ms is
 * esp_timer_get_time()/1000: monotonic from boot.
 *
 * Chord-key input (input.text, the wearer's controls) is not wired: the
 * braille_in module does not exist yet.  transport_control() and
 * transport_send_input_text() are the calls it will make.
 */
#if defined(ESP_PLATFORM)

#include <stdbool.h>
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
#include "mock_drv2605.h"
#include "queue.h"
#include "transport.h"
#include "transport_ws_esp.h"
#include "turn.h"

static const char *TAG = "ziv_band";

static drv2605_bus s_bus;
#if CONFIG_ZIV_BAND_HAPTIC_MOCK
static mock_drv s_mock;
#endif
static haptic_out s_haptic;
static turn s_turn;
static band_queue s_queue;
static band_queue_store s_store;
static band_transport s_transport;
static band_frame_io s_io;
static uint8_t s_blob[BAND_QUEUE_BLOB_MAX];
static EventGroupHandle_t s_link_events;
#define LINK_UP_BIT      (1u << 0)   /* the station has an IP */
#define LINK_CHANGED_BIT (1u << 1)   /* up/down flipped: wakes the loop's offline wait */

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

/* The boot ramp-up: the sequencer's own events, printed in the rung-1 app's
 * HAP format (the first six lines of its fixture, at a boot-relative clock),
 * before the transport loop takes the sequencer over. */
static void play_boot_ramp(void)
{
    static const char *const k_name = "ramp-up";   /* k_patterns[HAPTIC_PAT_RAMP_UP] in ziv_app.c */
    haptic_err_t err = haptic_out_play_pattern(&s_haptic, HAPTIC_PAT_RAMP_UP);
    if (err != HAPTIC_OK) {
        ESP_LOGE(TAG, "boot ramp-up refused (haptic_err %d)", (int) err);
        return;
    }
    uint32_t now = now_ms();
    for (;;) {
        haptic_out_event_t ev = (haptic_out_event_t) 0xFF;
        haptic_out_step_t st;
        memset(&st, 0, sizeof st);
        uint32_t next = haptic_out_step(&s_haptic, now, &ev, &st);
        if (ev == HAPTIC_OUT_EV_START) {
            printf("HAP %lu START PATTERN %s\n", (unsigned long) now, k_name);
        } else if (ev == HAPTIC_OUT_EV_BUZZ) {
            printf("HAP %lu BUZZ PATTERN %s %02X %lu %lu %u\n", (unsigned long) now, k_name,
                   (unsigned) st.dot_mask, (unsigned long) st.buzz_ms, (unsigned long) st.gap_after_ms,
                   (unsigned) st.seq);
        } else if (ev == HAPTIC_OUT_EV_END) {
            printf("HAP %lu END\n", (unsigned long) now);
            break;
        }
        if (next == 0) { break; }
        if (next > now) { vTaskDelay(pdMS_TO_TICKS(next - now)); }   /* sub-tick remainder: a yield */
        now = now_ms();
    }
    if (s_haptic.last_err != HAPTIC_OK) {
        ESP_LOGW(TAG, "boot ramp-up: bus error %d (a dead channel?)", (int) s_haptic.last_err);
    }
}

/* --- Wi-Fi station (the usual IDF dance) ---------------------------------- */

static bool wifi_configured(void)
{
    return CONFIG_ZIV_WIFI_SSID[0] != '\0';
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void) arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        transport_ws_esp_set_link(false);
        xEventGroupClearBits(s_link_events, LINK_UP_BIT);
        xEventGroupSetBits(s_link_events, LINK_CHANGED_BIT);
        ESP_LOGW(TAG, "wifi: disconnected; the radio retries, the transport backs off");
        esp_wifi_connect();   /* the transport's backoff paces the socket; the radio just retries */
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *ev = (const ip_event_got_ip_t *) data;
        ESP_LOGI(TAG, "wifi: got ip " IPSTR, IP2STR(&ev->ip_info.ip));
        transport_ws_esp_set_link(true);
        xEventGroupSetBits(s_link_events, LINK_UP_BIT | LINK_CHANGED_BIT);
    }
}

static void wifi_start(void)
{
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
    ESP_LOGI(TAG, "wifi: station started, SSID '%s'", CONFIG_ZIV_WIFI_SSID);
}

/* --- the loop ---------------------------------------------------------------- */

static void band_loop(void *arg)
{
    (void) arg;
    play_boot_ramp();
    ESP_LOGI(TAG, "loop: transport %s, link %s", transport_state_name(transport_state(&s_transport)),
             (xEventGroupGetBits(s_link_events) & LINK_UP_BIT) ? "up" : "down");
    for (;;) {
        uint32_t now = now_ms();
        uint32_t next = transport_step(&s_transport, now);
        uint32_t wait = (next == 0) ? (uint32_t) WORKING_EVERY_MS : (next > now ? next - now : 0);
        if (s_transport.connected) {
            /* block in the websocket inbox until the deadline (a frame wakes us early) */
            (void) transport_wait(&s_transport, now, wait);
        } else if (wait != 0) {
            /* offline: nothing to wait on but time — or the link flipping */
            (void) xEventGroupWaitBits(s_link_events, LINK_CHANGED_BIT, pdTRUE, pdTRUE, pdMS_TO_TICKS(wait));
        }
    }
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    ESP_LOGI(TAG, "nvs: ready");

    s_link_events = xEventGroupCreate();

    /* the bus and the sequencer */
#if CONFIG_ZIV_BAND_HAPTIC_MOCK
    mock_init(&s_mock);
    mock_bus(&s_bus, &s_mock);
    ESP_LOGW(TAG, "haptics: bench mock bus (CONFIG_ZIV_BAND_HAPTIC_MOCK=y) — no motors are driven");
#else
    drv2605_esp32_pins pins = { CONFIG_ZIV_I2C_PORT, CONFIG_ZIV_I2C_SDA_GPIO, CONFIG_ZIV_I2C_SCL_GPIO, CONFIG_ZIV_I2C_HZ };
    if (drv2605_bus_esp32_init(&s_bus, &pins) != HAPTIC_OK) { ESP_LOGE(TAG, "I2C bus init failed"); }
    ESP_LOGI(TAG, "haptics: I2C port %d SDA %d SCL %d at %d Hz (TCA9548A + 6x DRV2605L)",
             CONFIG_ZIV_I2C_PORT, CONFIG_ZIV_I2C_SDA_GPIO, CONFIG_ZIV_I2C_SCL_GPIO, CONFIG_ZIV_I2C_HZ);
#endif
    if (drv2605_init(&s_bus) != HAPTIC_OK) { ESP_LOGE(TAG, "DRV2605 init failed (check the mux wiring)"); }
    else { ESP_LOGI(TAG, "haptics: DRV2605 x%d initialised (RTP mode)", DRV2605_DOT_COUNT); }
    haptic_out_init(&s_haptic, &s_bus);

    /* the renderer contract */
#if CONFIG_ZIV_PROFILE_SINGLE_ACTUATOR
    turn_profile profile = TURN_PROFILE_SINGLE_ACTUATOR;
#else
    turn_profile profile = TURN_PROFILE_SIX_ACTUATOR;
#endif
    turn_init(&s_turn, &s_haptic, profile, CELL_GAP_DEFAULT_MS);
    turn_set_callbacks(&s_turn, NULL, NULL, on_beat, NULL);
    ESP_LOGI(TAG, "turn: profile %s, pace %u ms", turn_profile_name(profile), (unsigned) CELL_GAP_DEFAULT_MS);

    /* the queue, from NVS */
    queue_nvs_store(&s_store);
    band_queue_init(&s_queue, &s_store);
    if (band_queue_load(&s_queue, s_blob, sizeof s_blob) != BAND_QUEUE_OK) {
        ESP_LOGW(TAG, "stored queue unreadable; starting empty");
        band_queue_init(&s_queue, &s_store);
    }
    ESP_LOGI(TAG, "queue: %u held, last_acked '%s'", (unsigned) band_queue_count(&s_queue), band_queue_last_acked(&s_queue));

    /* the transport over the websocket (the client is only created here; the
     * link gate in transport_ws_esp.c keeps it closed until Wi-Fi has an IP) */
    if (transport_ws_esp_init(&s_io, CONFIG_ZIV_RELAY_URI) != 0) { ESP_LOGE(TAG, "websocket client init failed"); }
    band_transport_config cfg;
    memset(&cfg, 0, sizeof cfg);
    cfg.device_key = CONFIG_ZIV_DEVICE_KEY;
    cfg.profile = profile;
    cfg.seed = (uint32_t) esp_timer_get_time();
    transport_init(&s_transport, &s_io, &s_queue, &s_turn, &cfg);
    transport_set_log(&s_transport, on_log, NULL);
    transport_set_blob(&s_transport, s_blob, sizeof s_blob);
    ESP_LOGI(TAG, "transport: relay %s", CONFIG_ZIV_RELAY_URI);
    if (CONFIG_ZIV_DEVICE_KEY[0] == '\0') {
        ESP_LOGW(TAG, "transport: no device key configured (CONFIG_ZIV_DEVICE_KEY); the relay will refuse hello");
    }

    /* the radio — or, with no SSID (QEMU, an unconfigured board), none */
    if (wifi_configured()) {
        wifi_start();
    } else {
        ESP_LOGW(TAG, "wifi: unavailable — no SSID configured (CONFIG_ZIV_WIFI_SSID is empty); "
                      "the radio stays off, the transport stays offline and backs off");
    }

    xTaskCreate(band_loop, "ziv_band", 8192, NULL, 5, NULL);
}

#else
typedef int band_main_is_device_only;
#endif /* ESP_PLATFORM */
