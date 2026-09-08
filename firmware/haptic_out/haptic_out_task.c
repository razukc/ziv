/*
 * haptic_out_task.c — FreeRTOS task owning the haptic_out state machine.
 *
 * Sketch (not yet compiled on-device): the app never touches the sequencer
 * directly — it posts commands to the queue and the task drives
 * haptic_out_step() on a timer, so the rest of the firmware cannot block
 * on haptic I/O.  The task is a thin shell: all timing logic lives in
 * haptic_out.c, which the bench tests drive identically.
 *
 * Command set (extend freely):
 *   MARK n      play candidate mark n (0..HAPTIC_MARK_COUNT-1)
 *   PAT n       play attention pattern n (0..HAPTIC_PAT_COUNT-1)
 *   WORD s      spell a word (a-z)
 *   PREFIX t    name-mark prefix with tail t (0..HAPTIC_TAIL_COUNT-1)
 *   STOP        silence now
 *
 * TODO(on hardware): pick the queue length / task stack size, wire
 * haptic_out_task_init() into app_main, and decide what END does in the
 * app (e.g. unlock the next queued message).
 */
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "haptic_out.h"
#include "drv2605.h"

typedef struct {
    uint8_t kind;          /* 'M' | 'P' | 'W' | 'X'(prefix) | 'S'(stop) */
    uint8_t arg;
    char word[HAPTIC_OUT_MAX_WORD_LEN];
} haptic_cmd;

#define HAPTIC_CMD_QUEUE_LEN 8
#define HAPTIC_TASK_STACK    (4 * 1024)
#define HAPTIC_TASK_PRIO     5

static haptic_out g_haptic;
static QueueHandle_t g_q;

static void haptic_apply(const haptic_cmd *cmd)
{
    switch (cmd->kind) {
    case 'M': (void) haptic_out_play_mark(&g_haptic, cmd->arg); break;
    case 'P': (void) haptic_out_play_pattern(&g_haptic, (haptic_pattern) cmd->arg); break;
    case 'W': (void) haptic_out_play_word(&g_haptic, cmd->word); break;
    case 'X': (void) haptic_out_play_prefix(&g_haptic, (haptic_tail) cmd->arg); break;
    case 'S': haptic_out_stop(&g_haptic); break;
    default:  break;
    }
}

static void haptic_task(void *arg)
{
    (void) arg;
    haptic_cmd cmd;
    uint32_t deadline = 0;

    for (;;) {
        if (deadline == 0) {
            /* idle: wait for a command */
            if (xQueueReceive(g_q, &cmd, portMAX_DELAY) == pdTRUE) {
                haptic_apply(&cmd);
                deadline = haptic_out_step(&g_haptic, (uint32_t) pdTicksToMs(xTaskGetTickCount()),
                                           NULL, NULL);
            }
        } else {
            /* playing: wait for the next deadline (or a new command) */
            uint32_t now = (uint32_t) pdTicksToMs(xTaskGetTickCount());
            if (now >= deadline) {
                deadline = haptic_out_step(&g_haptic, now, NULL, NULL);
            } else {
                uint32_t wait_ms = deadline - now;
                if (xQueueReceive(g_q, &cmd, pdMsToTicks(wait_ms)) == pdTRUE) {
                    haptic_apply(&cmd);
                    deadline = haptic_out_step(&g_haptic,
                                               (uint32_t) pdTicksToMs(xTaskGetTickCount()),
                                               NULL, NULL);
                }
            }
        }
    }
}

void haptic_out_task_init(drv2605_bus *bus)
{
    haptic_out_init(&g_haptic, bus);
    (void) drv2605_init(bus);
    g_q = xQueueCreate(HAPTIC_CMD_QUEUE_LEN, sizeof(haptic_cmd));
    (void) xTaskCreate(haptic_task, "haptic", HAPTIC_TASK_STACK, NULL,
                       HAPTIC_TASK_PRIO, NULL);
}

/* App-side helpers (post-and-forget). */
void haptic_post_mark(uint8_t mi)
{
    haptic_cmd c = { 'M', mi, {0} };
    (void) xQueueSend(g_q, &c, 0);
}

void haptic_post_word(const char *w)
{
    haptic_cmd c = { 'W', 0, {0} };
    strncpy(c.word, w, HAPTIC_OUT_MAX_WORD_LEN - 1);
    (void) xQueueSend(g_q, &c, 0);
}

void haptic_post_stop(void)
{
    haptic_cmd c = { 'S', 0, {0} };
    (void) xQueueSend(g_q, &c, 0);
}