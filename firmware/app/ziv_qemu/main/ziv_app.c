/*
 * ziv_app.c -- implementation of the rung-1 app core (see ziv_app.h).
 *
 * Every HAP line is emitted from haptic_out_step()'s own events -- the app
 * adds narration, never a parallel model. Payload names for PATTERN / MARK
 * / PREFIX are mirrored by hand from the generated header (the timing
 * checker holds spec <-> header; rung 2 holds the HAP names to these
 * tables via tools/qemu_timeline.py).
 */
#include "ziv_app.h"

#include <stdio.h>
#include <string.h>

#include "haptic_timing.h"
#include "ziv_demo_sequence.h"

/* ------------------------------------------------------------------ */
/* Name tables - order follows the generated enums exactly. */
static const char *const k_patterns[HAPTIC_PAT_COUNT] = {
    "double-tap", "triple-pulse", "long-buzz",
    "ramp-up", "heartbeat", "processing", "end-of-message",
};

static const char *const k_marks[HAPTIC_MARK_COUNT] = {
    "ziv", "raz", "boaz", "razu", "buz",
};

static const char *const k_tails[HAPTIC_TAIL_COUNT] = {
    "message", "reminder", "error",
};

static void current_payload(ziv_app *app, char *buf, size_t n);
static const char *mode_name(haptic_out_mode_t mode);
static bool ziv_app_play_demo_stage(ziv_app *app, int stage);

/* Send one HAP line to the app's sink (a no-op when no sink was wired). */
static void emit(ziv_app *app, const char *line)
{
    if (app->sink != NULL) {
        app->sink(app->sink_ctx, line);
    }
}

void ziv_app_init(ziv_app *app, drv2605_bus *bus, ziv_hap_sink sink, void *sink_ctx)
{
    haptic_out_init(&app->haptic, bus);
    app->sink = sink;
    app->sink_ctx = sink_ctx;
    app->demo_done = false;  /* nothing has finished; running-ness is demo_stage == -1 */
    app->demo_stage = -1;
}

void ziv_app_run_demo(ziv_app *app)
{
    app->demo_stage = 0;
    app->demo_done = false;
    (void) ziv_app_play_demo_stage(app, 0);
}

/* Play the stage at k_demo_sequence[stage]. Returns false when the stage is
 * the sentinel (demo finished). */
static bool ziv_app_play_demo_stage(ziv_app *app, int stage)
{
    if (stage < 0 || stage >= k_demo_stage_count) { return false; }
    const demo_stage_t *s = &k_demo_sequence[stage];
    switch (s->mode) {
    case HAPTIC_OUT_MODE_PATTERN:
        return (void) haptic_out_play_pattern(&app->haptic, s->u.pat), true;
    case HAPTIC_OUT_MODE_PREFIX:
        return (void) haptic_out_play_prefix(&app->haptic, s->u.tail), true;
    case HAPTIC_OUT_MODE_WORD:
        return (void) haptic_out_play_word(&app->haptic, s->u.word), true;
    case HAPTIC_OUT_MODE_MARK:
        return (void) haptic_out_play_mark(&app->haptic, (uint8_t) s->u.mark), true;
    default:
        return false;
    }
}

static void demo_advance(ziv_app *app)
{
    app->demo_stage++;
    if (app->demo_stage >= k_demo_stage_count
        || !ziv_app_play_demo_stage(app, app->demo_stage)) {
        app->demo_done = true;
        app->demo_stage = -1;
    }
}

static const char *mode_name(haptic_out_mode_t mode)
{
    switch (mode) {
    case HAPTIC_OUT_MODE_IDLE:   return "IDLE";
    case HAPTIC_OUT_MODE_MARK:   return "MARK";
    case HAPTIC_OUT_MODE_PATTERN: return "PATTERN";
    case HAPTIC_OUT_MODE_WORD:   return "WORD";
    case HAPTIC_OUT_MODE_PREFIX: return "PREFIX";
    default:                     return "?";
    }
}

static void current_payload(ziv_app *app, char *buf, size_t n)
{
    if (n == 0) { return; }
    buf[0] = '\0';
    switch (app->haptic.mode) {
    case HAPTIC_OUT_MODE_PATTERN:
        snprintf(buf, n, "%s", k_patterns[app->haptic.pat]);
        break;
    case HAPTIC_OUT_MODE_MARK:
        snprintf(buf, n, "%s", k_marks[app->haptic.mark_idx]);
        break;
    case HAPTIC_OUT_MODE_WORD:
        snprintf(buf, n, "%.*s", (int) app->haptic.word_len, (char *) app->haptic.word);
        break;
    case HAPTIC_OUT_MODE_PREFIX:
        snprintf(buf, n, "%s", k_tails[app->haptic.tail]);
        break;
    default:
        snprintf(buf, n, "-");
        break;
    }
}


uint32_t ziv_app_step(ziv_app *app, uint32_t now_ms)
{
    haptic_out_event_t ev;
    haptic_out_step_t st;
    char payload[HAPTIC_OUT_MAX_WORD_LEN + 1];
    char line[160];

    for (;;) {
        ev = (haptic_out_event_t) 0xFF;   /* sentinel, as the bench does */
        memset(&st, 0, sizeof st);
        uint32_t next = haptic_out_step(&app->haptic, now_ms, &ev, &st);

        if (ev == HAPTIC_OUT_EV_START) {
            current_payload(app, payload, sizeof payload);
            (void) snprintf(line, sizeof line, "HAP %lu START %s %s",
                            (unsigned long) now_ms, mode_name(app->haptic.mode), payload);
            emit(app, line);
            continue;   /* call again immediately */
        }
        if (ev == HAPTIC_OUT_EV_BUZZ) {
            current_payload(app, payload, sizeof payload);
            (void) snprintf(line, sizeof line,
                            "HAP %lu BUZZ %s %s %02X %lu %lu %u",
                            (unsigned long) now_ms, mode_name(st.mode), payload,
                            (unsigned) st.dot_mask,
                            (unsigned long) st.buzz_ms,
                            (unsigned long) st.gap_after_ms,
                            (unsigned) st.seq);
            emit(app, line);
            if (next > now_ms) { return next; }
            continue;
        }
        if (ev == HAPTIC_OUT_EV_END) {
            (void) snprintf(line, sizeof line, "HAP %lu END", (unsigned long) now_ms);
            emit(app, line);
            break;
        }
        /* No event: idle or waiting on the deadline. */
        return next;
    }

    /* END path (kept out of the loop above for clarity). */
    if (app->demo_stage >= 0 && !app->demo_done) {
        demo_advance(app);
        /* 0 when the demo just finished -- the caller must not step an idle
         * sequencer, which would report a spurious second END. */
        return app->haptic.playing ? now_ms : 0;
    }
    return 0;
}

void ziv_app_stop(ziv_app *app)
{
    haptic_out_stop(&app->haptic);
    app->demo_stage = -1;
    app->demo_done = false;
}

int ziv_app_play_pattern(ziv_app *app, int pat_idx)
{
    app->demo_stage = -1;
    app->demo_done = false;
    return (int) haptic_out_play_pattern(&app->haptic, (haptic_pattern) pat_idx);
}

int ziv_app_play_mark(ziv_app *app, int mark_idx)
{
    app->demo_stage = -1;
    app->demo_done = false;
    return (int) haptic_out_play_mark(&app->haptic, (uint8_t) mark_idx);
}

int ziv_app_play_word(ziv_app *app, const char *word)
{
    app->demo_stage = -1;
    app->demo_done = false;
    return (int) haptic_out_play_word(&app->haptic, word);
}

int ziv_app_play_prefix(ziv_app *app, int tail_idx)
{
    app->demo_stage = -1;
    app->demo_done = false;
    return (int) haptic_out_play_prefix(&app->haptic, (haptic_tail) tail_idx);
}

/* ------------------------------------------------------------------ */
/* Name -> index lookups (order follows the generated enums exactly). */
int ziv_pattern_index(const char *id)
{
    if (id == NULL) { return -1; }
    for (int i = 0; i < (int) HAPTIC_PAT_COUNT; i++) {
        if (strcmp(k_patterns[i], id) == 0) { return i; }
    }
    return -1;
}

int ziv_mark_index(const char *id)
{
    if (id == NULL) { return -1; }
    for (int i = 0; i < (int) HAPTIC_MARK_COUNT; i++) {
        if (strcmp(k_marks[i], id) == 0) { return i; }
    }
    return -1;
}

int ziv_tail_index(const char *id)
{
    if (id == NULL) { return -1; }
    for (int i = 0; i < (int) HAPTIC_TAIL_COUNT; i++) {
        if (strcmp(k_tails[i], id) == 0) { return i; }
    }
    return -1;
}
