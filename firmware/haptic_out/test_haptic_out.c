/*
 * test_haptic_out.c — bench tests for the haptic_out sequencer.
 *
 * Drives the real module against the mock bus with a virtual clock:
 * haptic_out_step() returns the next deadline, so the harness walks the
 * timeline exactly and asserts every buzz start time, duration, gap, and
 * dot mask against the generated haptic_timing.h tables — the same numbers
 * the phone feel-tool plays.
 *
 * Build & run (host C compiler, e.g. gcc):
 *     cc -I. -o test_haptic_out haptic_out.c drv2605.c mock_drv2605.c test_haptic_out.c
 *     ./test_haptic_out            (or test_haptic_out.exe)
 * Or:  python run_tests.py
 */
#include <stdio.h>
#include <string.h>
#include "haptic_out.h"
#include "drv2605.h"
#include "mock_drv2605.h"

static int failures = 0;
static int checks = 0;

#define CHECK(cond, msg) do { \
    checks++; \
    if (!(cond)) { failures++; printf("FAIL: %s\n", msg); } \
} while (0)

#define CHECK_EQ(a, b, msg) do { \
    checks++; \
    if ((a) != (b)) { failures++; printf("FAIL: %s (got %lld, want %lld)\n", msg, (long long) (a), (long long) (b)); } \
} while (0)

typedef struct { uint32_t at, buzz, gap; uint8_t mask; } buzz_rec;

/* Walk a play to completion, recording every buzz. */
static int run_play(haptic_out *h, buzz_rec *out, int max)
{
    uint32_t now = 0;
    int n = 0;
    for (;;) {
        haptic_out_event_t ev = HAPTIC_OUT_EV_BUZZ;
        haptic_out_step_t st;
        uint32_t next = haptic_out_step(h, now, &ev, &st);
        if (ev == HAPTIC_OUT_EV_BUZZ && n < max) {
            out[n].at = now;
            out[n].buzz = st.buzz_ms;
            out[n].gap = st.gap_after_ms;
            out[n].mask = st.dot_mask;
            n++;
        }
        if (ev == HAPTIC_OUT_EV_END || next == 0) { break; }
        now = next;
    }
    return n;
}

static void check_buzz(const buzz_rec *r, int i, uint32_t at, uint32_t buzz, uint32_t gap, uint8_t mask)
{
    char m[96];
    snprintf(m, sizeof m, "buzz %d start time", i);
    CHECK_EQ(r[i].at, at, m);
    snprintf(m, sizeof m, "buzz %d duration", i);
    CHECK_EQ(r[i].buzz, buzz, m);
    snprintf(m, sizeof m, "buzz %d gap", i);
    CHECK_EQ(r[i].gap, gap, m);
    snprintf(m, sizeof m, "buzz %d dot mask", i);
    CHECK_EQ(r[i].mask, mask, m);
}

static void test_ziv_mark(void)
{
    haptic_out h; mock_drv m; drv2605_bus bus;
    mock_init(&m); mock_bus(&bus, &m);
    haptic_out_init(&h, &bus);

    CHECK_EQ(haptic_out_play_mark(&h, 0), HAPTIC_OK, "play ziv mark accepts index 0");
    buzz_rec r[8];
    int n = run_play(&h, r, 8);
    CHECK_EQ(n, 3, "ziv mark has 3 cells");
    check_buzz(r, 0, 0,   290, 420, 0x35);   /* z = 4 dots, dots 1-3-5-6 */
    check_buzz(r, 1, 710, 170, 420, 0x0A);   /* i = 2 dots, dots 2-4    */
    check_buzz(r, 2, 1300, 290, 420, 0x27);  /* v = 4 dots, dots 1-2-3-6 */
    CHECK_EQ(haptic_out_is_playing(&h), false, "ziv mark finished");
    /* trailing silence: END exactly one tail gap after the last buzz */
    CHECK_EQ(haptic_out_step(&h, 2010, NULL, NULL), 0, "ziv total duration 2010 ms");
    /* mock shows silence after playback */
    for (int ch = 0; ch < 6; ch++) { CHECK_EQ(mock_drive(&m, (uint8_t) ch), 0, "all dots silent after play"); }
}

static void test_word_ziv_equals_mark(void)
{
    haptic_out h; mock_drv m; drv2605_bus bus;
    mock_init(&m); mock_bus(&bus, &m);
    haptic_out_init(&h, &bus);

    buzz_rec a[8], b[8];
    CHECK_EQ(haptic_out_play_word(&h, "ziv"), HAPTIC_OK, "play word ziv");
    int na = run_play(&h, a, 8);
    CHECK_EQ(haptic_out_play_mark(&h, 0), HAPTIC_OK, "play mark ziv");
    int nb = run_play(&h, b, 8);
    CHECK_EQ(na, nb, "word and mark ziv same cell count");
    for (int i = 0; i < na && i < nb; i++) {
        CHECK_EQ(a[i].at, b[i].at, "word/mark ziv buzz time");
        CHECK_EQ(a[i].buzz, b[i].buzz, "word/mark ziv buzz duration");
        CHECK_EQ(a[i].mask, b[i].mask, "word/mark ziv dot mask");
    }
}

static void test_rename_arc(void)
{
    /* Protocol §5 option B: tin and wiz spell the same dot-count arc as ziv. */
    haptic_out h; mock_drv m; drv2605_bus bus;
    mock_init(&m); mock_bus(&bus, &m);
    haptic_out_init(&h, &bus);

    buzz_rec a[8], b[8], c[8];
    CHECK_EQ(haptic_out_play_word(&h, "ziv"), HAPTIC_OK, "play ziv");
    int nz = run_play(&h, a, 8);
    CHECK_EQ(haptic_out_play_word(&h, "tin"), HAPTIC_OK, "play tin");
    int nt = run_play(&h, b, 8);
    CHECK_EQ(haptic_out_play_word(&h, "wiz"), HAPTIC_OK, "play wiz");
    int nw = run_play(&h, c, 8);
    CHECK_EQ(nz, nt, "ziv/tin same length");
    CHECK_EQ(nz, nw, "ziv/wiz same length");
    for (int i = 0; i < nz; i++) {
        CHECK_EQ(a[i].buzz, b[i].buzz, "ziv/tin arc equality");
        CHECK_EQ(a[i].buzz, c[i].buzz, "ziv/wiz arc equality");
    }
    /* and the actual rename-arc words, spelled out */
    check_buzz(b, 0, 0, 290, 420, 0x1E);   /* t = 4 dots, dots 2-3-4-5 */
    check_buzz(b, 1, 710, 170, 420, 0x0A); /* i */
    check_buzz(b, 2, 1300, 290, 420, 0x1D);/* n = 4 dots, dots 1-3-4-5 */
}

static void test_double_tap(void)
{
    haptic_out h; mock_drv m; drv2605_bus bus;
    mock_init(&m); mock_bus(&bus, &m);
    haptic_out_init(&h, &bus);

    CHECK_EQ(haptic_out_play_pattern(&h, HAPTIC_PAT_DOUBLE_TAP), HAPTIC_OK, "play double tap");
    buzz_rec r[4];
    int n = run_play(&h, r, 4);
    CHECK_EQ(n, 2, "double tap has 2 beats");
    check_buzz(r, 0, 0, 70, 160, 0);
    check_buzz(r, 1, 230, 70, 420, 0);
    CHECK_EQ(haptic_out_step(&h, 720, NULL, NULL), 0, "double tap total 720 ms");
}

static void test_prefix_message(void)
{
    /* The plan §4 morning brief: Z-I-V, breath, then "new message" (double tap). */
    haptic_out h; mock_drv m; drv2605_bus bus;
    mock_init(&m); mock_bus(&bus, &m);
    haptic_out_init(&h, &bus);

    CHECK_EQ(haptic_out_play_prefix(&h, HAPTIC_TAIL_MESSAGE), HAPTIC_OK, "play prefix message");
    buzz_rec r[8];
    int n = run_play(&h, r, 8);
    CHECK_EQ(n, 5, "prefix message = 3 mark cells + 2 tail beats");
    check_buzz(r, 0, 0,    290, 420, 0x35);
    check_buzz(r, 1, 710,  170, 420, 0x0A);
    check_buzz(r, 2, 1300, 290, 550, 0x27);   /* the breath, not a cell gap */
    check_buzz(r, 3, 2140, 70, 160, 0);
    check_buzz(r, 4, 2370, 70, 420, 0);
    CHECK_EQ(haptic_out_step(&h, 2860, NULL, NULL), 0, "prefix message total 2860 ms");
}

static void test_letter_sweep(void)
{
    /* Every letter: buzz = 50 + 60*dots, mask = the generated bitmask. */
    for (int li = 0; li < 26; li++) {
        haptic_out h; mock_drv m; drv2605_bus bus;
        mock_init(&m); mock_bus(&bus, &m);
        haptic_out_init(&h, &bus);
        char word[2] = { (char) ('a' + li), '\0' };
        CHECK_EQ(haptic_out_play_word(&h, word), HAPTIC_OK, "single-letter word accepted");
        buzz_rec r[2];
        int n = run_play(&h, r, 2);
        CHECK_EQ(n, 1, "single letter is one cell");
        CHECK_EQ(r[0].buzz, (uint32_t) (CELL_BASE_MS + CELL_PER_DOT_MS * HAPTIC_LETTER_DOTS[li]), "letter buzz duration");
        CHECK_EQ(r[0].mask, HAPTIC_LETTER_MASKS[li], "letter dot mask");
        CHECK_EQ(r[0].gap, (uint32_t) TAIL_GAP_MS, "last cell gap is the tail gap");
    }
}

static void test_invalid_inputs(void)
{
    haptic_out h; mock_drv m; drv2605_bus bus;
    mock_init(&m); mock_bus(&bus, &m);
    haptic_out_init(&h, &bus);

    CHECK_EQ(haptic_out_play_mark(&h, 99), HAPTIC_ERR_INVALID_ARG, "mark index out of range");
    CHECK_EQ(haptic_out_play_pattern(&h, (haptic_pattern) 99), HAPTIC_ERR_INVALID_ARG, "pattern out of range");
    CHECK_EQ(haptic_out_play_prefix(&h, (haptic_tail) 99), HAPTIC_ERR_INVALID_ARG, "tail out of range");
    CHECK_EQ(haptic_out_play_word(&h, "Ziv"), HAPTIC_ERR_INVALID_ARG, "uppercase rejected");
    CHECK_EQ(haptic_out_play_word(&h, "zi v"), HAPTIC_ERR_INVALID_ARG, "space rejected");
    CHECK_EQ(haptic_out_play_word(&h, ""), HAPTIC_ERR_INVALID_ARG, "empty word rejected");
    CHECK_EQ(haptic_out_play_word(&h, "abcdefghijklmnopq"), HAPTIC_ERR_TOO_LONG, "17-letter word rejected");
    CHECK_EQ(haptic_out_play_word(&h, "abcdefghijklmnop"), HAPTIC_OK, "16-letter word accepted");
    CHECK_EQ(haptic_out_play_word(&h, NULL), HAPTIC_ERR_INVALID_ARG, "NULL word rejected");
}

static void test_stop_mid_play(void)
{
    haptic_out h; mock_drv m; drv2605_bus bus;
    mock_init(&m); mock_bus(&bus, &m);
    haptic_out_init(&h, &bus);

    CHECK_EQ(haptic_out_play_word(&h, "hello"), HAPTIC_OK, "play hello");
    uint32_t now = 0;
    haptic_out_event_t ev;
    now = haptic_out_step(&h, now, &ev, NULL);              /* START */
    now = haptic_out_step(&h, now, &ev, NULL);              /* buzz h */
    CHECK_EQ(haptic_out_is_playing(&h), true, "playing mid-word");
    CHECK_EQ(mock_drive(&m, 0), DRV2605_DRIVE_DEFAULT, "dot 1 up during h");

    haptic_out_stop(&h);
    CHECK_EQ(haptic_out_is_playing(&h), false, "stopped");
    for (int ch = 0; ch < 6; ch++) { CHECK_EQ(mock_drive(&m, (uint8_t) ch), 0, "stop silences all dots"); }
    CHECK_EQ(haptic_out_step(&h, 9999, &ev, NULL), 0, "step after stop returns 0");
    CHECK_EQ(ev, HAPTIC_OUT_EV_END, "step after stop reports END");
}

static void test_cancel_with_new_play(void)
{
    haptic_out h; mock_drv m; drv2605_bus bus;
    mock_init(&m); mock_bus(&bus, &m);
    haptic_out_init(&h, &bus);

    CHECK_EQ(haptic_out_play_word(&h, "ziv"), HAPTIC_OK, "play ziv");
    haptic_out_step(&h, 0, NULL, NULL);   /* START only */
    CHECK_EQ(haptic_out_play_mark(&h, 1), HAPTIC_OK, "cancel with raz mark");
    buzz_rec r[8];
    int n = run_play(&h, r, 8);
    CHECK_EQ(n, 3, "raz has 3 cells");
    check_buzz(r, 0, 0, 290, 420, 0x17);   /* r = 4 dots, dots 1-2-3-5 */
    check_buzz(r, 1, 710, 110, 420, 0x01); /* a = 1 dot */
    check_buzz(r, 2, 1300, 290, 420, 0x35);/* z */
}

static void test_bus_fault(void)
{
    haptic_out h; mock_drv m; drv2605_bus bus;
    mock_init(&m); mock_bus(&bus, &m);
    haptic_out_init(&h, &bus);

    /* z = dots 1-3-5-6: channel 2 (dot 3) write fails -> drive_mask errors. */
    mock_fault(&m, 2, DRV2605_REG_RTPIN);
    CHECK_EQ(haptic_out_play_word(&h, "ziv"), HAPTIC_OK, "play ziv with a dead dot");
    buzz_rec r[8];
    int n = run_play(&h, r, 8);
    CHECK_EQ(n, 0, "no buzz delivered on bus error");
    CHECK_EQ(h.last_err, HAPTIC_ERR_IO, "last_err is IO");
    for (int ch = 0; ch < 6; ch++) { CHECK_EQ(mock_drive(&m, (uint8_t) ch), 0, "fault path silences all dots"); }
    mock_clear_fault(&m);

    /* recovery: a fresh play works again */
    CHECK_EQ(haptic_out_play_word(&h, "ziv"), HAPTIC_OK, "replay after fault");
    n = run_play(&h, r, 8);
    CHECK_EQ(n, 3, "recovers after fault cleared");
}

static void test_early_step_returns_deadline(void)
{
    haptic_out h; mock_drv m; drv2605_bus bus;
    mock_init(&m); mock_bus(&bus, &m);
    haptic_out_init(&h, &bus);

    CHECK_EQ(haptic_out_play_word(&h, "ziv"), HAPTIC_OK, "play ziv");
    uint32_t now = 0;
    haptic_out_event_t ev = HAPTIC_OUT_EV_END;
    now = haptic_out_step(&h, now, &ev, NULL);         /* START */
    now = haptic_out_step(&h, now, &ev, NULL);         /* buzz z at 0, next 290 */
    CHECK_EQ(now, 290u, "buzz z deadline 290");
    CHECK_EQ(ev, HAPTIC_OUT_EV_BUZZ, "buzz event delivered");
    /* calling early must not advance anything nor fire an event */
    ev = (haptic_out_event_t) 0xFF;
    uint32_t still = haptic_out_step(&h, 100, &ev, NULL);
    CHECK_EQ(still, 290u, "early call returns the same deadline");
    CHECK_EQ(ev, (haptic_out_event_t) 0xFF, "early call fires no event");
    CHECK_EQ(mock_drive(&m, 0), DRV2605_DRIVE_DEFAULT, "dots unchanged by early call");
}

int main(void)
{
    test_ziv_mark();
    test_word_ziv_equals_mark();
    test_rename_arc();
    test_double_tap();
    test_prefix_message();
    test_letter_sweep();
    test_invalid_inputs();
    test_stop_mid_play();
    test_cancel_with_new_play();
    test_bus_fault();
    test_early_step_returns_deadline();

    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}