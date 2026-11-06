/*
 * haptic_out_task.c — FreeRTOS task owning the haptic_out state machine.
 *
 * Device-only; compiles against ESP-IDF v5.5 (linked into the band image,
 * not started by it — the band's turn owns its sequencer), unverified on
 * hardware.  Note for a board: the deadline wait here is tick-based
 * (pdMS_TO_TICKS / xQueueReceive), good to one tick; the rung-1 QEMU app
 * moved to an esp_timer one-shot wake for a millisecond-exact timeline.
 * The app never touches the sequencer directly — it posts commands to the
 * queue and the task drives haptic_out_step() on the FreeRTOS tick, so the
 * rest of the firmware cannot block on haptic I/O.  The task is a thin
 * shell: all timing logic lives in haptic_out.c, which the bench drives
 * identically.
 *
 * Command set:
 *   MARK n      play candidate mark n (0..HAPTIC_MARK_COUNT-1)
 *   PAT n       play attention pattern n (0..HAPTIC_PAT_COUNT-1)
 *   WORD s      spell a word (a-z, up to HAPTIC_OUT_MAX_WORD_LEN letters)
 *   PREFIX t    name-mark prefix with tail t (0..HAPTIC_TAIL_COUNT-1)
 *   PACE ms     set the cell gap (clamped by the sequencer)
 *   STOP        silence now
 *
 * The band's utterance path (firmware/band) does not go through this
 * queue: its turn module owns a haptic_out of its own and compiles whole
 * segments into haptic_out_play_beats().  This task remains the console /
 * bring-up surface (HARDWARE_BRINGUP.md §4).
 *
 * Fixed since the first sketch: the tick<->ms macros are the ones FreeRTOS
 * and ESP-IDF define (pdMS_TO_TICKS, pdTICKS_TO_MS — the earlier
 * pdMsToTicks / pdTicksToMs do not exist), and the command buffer has room
 * for a full HAPTIC_OUT_MAX_WORD_LEN-letter word plus its terminator, so a
 * 16-letter word is no longer cut to 15.
 */
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "haptic_out.h"
#include "haptic_out_task.h"
#include "drv2605.h"

typedef struct {
    uint8_t kind;          /* 'M' | 'P' | 'W' | 'X'(prefix) | 'G'(pace) | 'S'(stop) */
    uint8_t arg;
    uint32_t arg32;        /* PACE: the cell gap in ms */
    char word[HAPTIC_OUT_MAX_WORD_LEN + 1];   /* +1: the terminator, so 16 letters fit */
} haptic_cmd;

#define HAPTIC_CMD_QUEUE_LEN 8
#define HAPTIC_TASK_STACK    (4 * 1024)
#define HAPTIC_TASK_PRIO     5

static haptic_out g_haptic;
static QueueHandle_t g_q;

static uint32_t now_ms(void)
{
    return (uint32_t) pdTICKS_TO_MS(xTaskGetTickCount());
}

static void haptic_apply(const haptic_cmd *cmd)
{
    switch (cmd->kind) {
    case 'M': (void) haptic_out_play_mark(&g_haptic, cmd->arg); break;
    case 'P': (void) haptic_out_play_pattern(&g_haptic, (haptic_pattern) cmd->arg); break;
    case 'W': (void) haptic_out_play_word(&g_haptic, cmd->word); break;
    case 'X': (void) haptic_out_play_prefix(&g_haptic, (haptic_tail) cmd->arg); break;
    case 'G': (void) haptic_out_set_cell_gap_ms(&g_haptic, cmd->arg32); break;
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
                deadline = haptic_out_step(&g_haptic, now_ms(), NULL, NULL);
            }
        } else {
            /* playing: wait for the next deadline (or a new command) */
            uint32_t now = now_ms();
            if (now >= deadline) {
                deadline = haptic_out_step(&g_haptic, now, NULL, NULL);
            } else {
                uint32_t wait_ms = deadline - now;
                if (xQueueReceive(g_q, &cmd, pdMS_TO_TICKS(wait_ms)) == pdTRUE) {
                    haptic_apply(&cmd);
                    deadline = haptic_out_step(&g_haptic, now_ms(), NULL, NULL);
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
static void post(haptic_cmd *c)
{
    (void) xQueueSend(g_q, c, 0);
}

void haptic_post_mark(uint8_t mi)
{
    haptic_cmd c = { 'M', mi, 0, {0} };
    post(&c);
}

void haptic_post_pattern(uint8_t pi)
{
    haptic_cmd c = { 'P', pi, 0, {0} };
    post(&c);
}

void haptic_post_word(const char *w)
{
    haptic_cmd c = { 'W', 0, 0, {0} };
    /* copy up to the full word length; the +1 byte keeps the terminator */
    strncpy(c.word, w, HAPTIC_OUT_MAX_WORD_LEN);
    c.word[HAPTIC_OUT_MAX_WORD_LEN] = '\0';
    post(&c);
}

void haptic_post_prefix(uint8_t t)
{
    haptic_cmd c = { 'X', t, 0, {0} };
    post(&c);
}

void haptic_post_pace(uint32_t cell_gap_ms)
{
    haptic_cmd c = { 'G', 0, cell_gap_ms, {0} };
    post(&c);
}

void haptic_post_stop(void)
{
    haptic_cmd c = { 'S', 0, 0, {0} };
    post(&c);
}
