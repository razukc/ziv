/*
 * app_main.c — ESP-IDF shell of the QEMU boot app (ladder rung 1).
 *
 * Thin on purpose: everything worth testing lives in ziv_app.c
 * (host-portable, asserted end to end by host_demo.c on the bench).
 * This file owns only the IDF realities: the monotonic ms clock, the HAP
 * sink on the emulated UART, the FreeRTOS loop around ziv_app_step()'s
 * pull-model deadlines, and the scripted boot demo start.
 *
 * Run:  idf.py set-target esp32s3 && idf.py qemu monitor
 * The console command protocol (ziv play pattern <id> | ziv play word
 * <letters> | ziv stop | ziv status) lands with the IDF console component
 * wiring; the dispatcher it will call (ziv_pattern_index and friends) is
 * already in ziv_app.c and exercised by the host tests.
 */
#include <stdint.h>
#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"

#include "ziv_app.h"
#include "mock_drv2605.h"

static ziv_app s_app;
static mock_drv s_mock;

static void hap_sink(void *ctx, const char *line)
{
    (void) ctx;
    if (line != NULL) {
        printf("%s\n", line);
    }
}

static uint32_t now_ms(void)
{
    return (uint32_t) (esp_timer_get_time() / 1000);
}

static void ziv_loop_task(void *arg)
{
    (void) arg;
    uint32_t now = now_ms();

    /* The scripted boot demo runs at boot — rung 2 diffs its HAP output. */
    ziv_app_run_demo(&s_app);

    for (;;) {
        uint32_t next = ziv_app_step(&s_app, now);
        if (next == 0) {
            vTaskDelay(pdMS_TO_TICKS(50));   /* idle poll */
        } else if (next > now) {
            vTaskDelay(pdMS_TO_TICKS(next - now));
        }
        now = now_ms();
    }
}

void app_main(void)
{
    mock_init(&s_mock);
    static drv2605_bus s_bus;
    mock_bus(&s_bus, &s_mock);
    ziv_app_init(&s_app, &s_bus, hap_sink, NULL);

    xTaskCreate(ziv_loop_task, "ziv_loop", 4096, NULL, 5, NULL);
}
