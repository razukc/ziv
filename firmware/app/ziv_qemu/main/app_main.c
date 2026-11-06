/*
 * app_main.c — ESP-IDF shell of the QEMU boot app (ladder rung 1).
 *
 * Thin on purpose: everything worth testing lives in ziv_app.c
 * (host-portable, asserted end to end by host_demo.c on the bench).
 * This file owns only the IDF realities: the monotonic ms clock, the HAP
 * sink on the emulated UART, the FreeRTOS loop around ziv_app_step()'s
 * pull-model deadlines, and the scripted boot demo start.
 *
 * The HAP clock. at_ms is esp_timer_get_time()/1000 (monotonic, µs
 * resolution, the same source on silicon and under QEMU) REBASED to the
 * instant the demo starts: the bench's virtual clock is 0 at the demo's
 * first step, so both logs share one epoch and tools/qemu_timeline.py
 * (rung 2) compares absolute timestamps like with like. Boot time before
 * the demo (ROM, bootloader, FreeRTOS start — a few hundred ms) is not
 * part of the timeline and must not appear as drift.
 *
 * Waiting for a deadline. The FreeRTOS tick is NOT the clock here: under
 * QEMU (wall-clock mode) the emulated periodic tick alarm loses whole
 * ticks when the host is late, so xTickCount lags esp_timer by 10-30 ms at
 * random moments and a vTaskDelay()-based wait wakes that late — and the
 * sequencer schedules the next beat from `now`, so every slip shifts the
 * rest of the timeline (measured: +84 ms over the 7.3 s demo on a quiet
 * host, +1039 ms under load). esp_timer's one-shot alarm is a compare on
 * the µs counter, so the loop arms it at the ABSOLUTE deadline and blocks
 * on a task notification; a late host still delays one wake, but ticks
 * cannot be lost and nothing is rounded to 10 ms.
 *
 * Run:  idf.py set-target esp32s3 && idf.py build && idf.py qemu monitor
 * The console command protocol (ziv play pattern <id> | ziv play word
 * <letters> | ziv stop | ziv status) lands with the IDF console component
 * wiring; the dispatcher it will call (ziv_pattern_index and friends) is
 * already in ziv_app.c and exercised by the host tests.
 */
#include <stdint.h>
#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_err.h"
#include "esp_timer.h"

#include "ziv_app.h"
#include "mock_drv2605.h"

static ziv_app s_app;
static mock_drv s_mock;
static int64_t s_epoch_us;   /* esp_timer time of the demo start: HAP at_ms 0 */
static TaskHandle_t s_loop_task;
static esp_timer_handle_t s_deadline_timer;

static void hap_sink(void *ctx, const char *line)
{
    (void) ctx;
    if (line != NULL) {
        printf("%s\n", line);
    }
}

static uint32_t now_ms(void)
{
    return (uint32_t) ((esp_timer_get_time() - s_epoch_us) / 1000);
}

static void deadline_cb(void *arg)
{
    (void) arg;
    xTaskNotifyGive(s_loop_task);
}

/* Block until the HAP clock reads deadline_ms: the esp_timer one-shot is
 * armed at the absolute instant (µs), the task sleeps on its notification.
 * Any early wake (a stale notification, the safety-net timeout) is harmless:
 * the caller re-steps and, still before the deadline, waits again. */
static void wait_until(uint32_t deadline_ms)
{
    int64_t target_us = s_epoch_us + (int64_t) deadline_ms * 1000;
    int64_t delta_us = target_us - esp_timer_get_time();
    if (delta_us <= 0) { return; }
    (void) esp_timer_stop(s_deadline_timer);            /* ESP_ERR_INVALID_STATE when idle: fine */
    (void) ulTaskNotifyTake(pdTRUE, 0);                  /* drop a stale wake */
    ESP_ERROR_CHECK(esp_timer_start_once(s_deadline_timer, (uint64_t) delta_us));
    (void) ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS((uint32_t) (delta_us / 1000) + 100));   /* safety net */
}

static void ziv_loop_task(void *arg)
{
    (void) arg;
    s_loop_task = xTaskGetCurrentTaskHandle();

    /* The scripted boot demo runs at boot — rung 2 diffs its HAP output.
     * The epoch is taken here so the first line reads "HAP 0 START". */
    s_epoch_us = esp_timer_get_time();
    uint32_t now = now_ms();
    ziv_app_run_demo(&s_app);

    for (;;) {
        uint32_t next = ziv_app_step(&s_app, now);
        if (next == 0) {
            vTaskDelay(pdMS_TO_TICKS(50));   /* idle poll (the console will wake this) */
        } else if (next > now) {
            wait_until(next);
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

    const esp_timer_create_args_t timer_args = {
        .callback = deadline_cb,
        .arg = NULL,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "ziv_deadline",
        .skip_unhandled_events = true,
    };
    ESP_ERROR_CHECK(esp_timer_create(&timer_args, &s_deadline_timer));

    /* Pinned to CPU0 with the esp_timer task: the deadline wake is then a
     * same-core notification, not a cross-core interrupt to a halted vCPU. */
    xTaskCreatePinnedToCore(ziv_loop_task, "ziv_loop", 6144, NULL, 5, NULL, 0);
}
