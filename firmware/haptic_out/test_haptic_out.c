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
 *     cc -I. -o test_haptic_out haptic_out.c drv2605.c drv2605_i2c_esp32.c mock_drv2605.c test_haptic_out.c
 * (drv2605_i2c_esp32.c compiles to stubs off ESP_PLATFORM; building it here
 * keeps the device bus file honest under the same warning flags.)
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
    long long got_ = (long long) (a), want_ = (long long) (b); \
    checks++; \
    if (got_ != want_) { failures++; printf("FAIL: %s (got %lld, want %lld)\n", msg, got_, want_); } \
} while (0)

typedef struct { uint32_t at, buzz, gap; uint8_t mask; } buzz_rec;

/* Walk a play to completion, recording every buzz.
 *
 * The module's contract: ev/step are written only when an event fires, so
 * the caller must pre-fill ev with a sentinel and trust it only after the
 * module actually reported something. */
#define EV_NONE ((haptic_out_event_t) 0xFF)
static int run_play(haptic_out *h, buzz_rec *out, int max)
{
    uint32_t now = 0;
    int n = 0;
    for (;;) {
        haptic_out_event_t ev = EV_NONE;
        haptic_out_step_t st = {0};
        uint32_t next = haptic_out_step(h, now, &ev, &st);
        if (ev == HAPTIC_OUT_EV_START) { continue; }   /* call again immediately */
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
    check_buzz(r, 2, 1240, 290, 420, 0x35);/* z — a is 110 ms, so z lands at 710+110+420 */
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


static void test_mux_select_contract(void)
{
    /* The TCA9548A control byte is a bitmask (bit n = channel n).  The
     * mock refuses anything that is not exactly one set bit, so a bus that
     * writes the raw channel number — the first ESP32 sketch did — fails
     * here instead of on a board. */
    mock_drv m; drv2605_bus bus;
    mock_init(&m); mock_bus(&bus, &m);

    for (uint8_t ch = 0; ch < DRV2605_DOT_COUNT; ch++) {
        uint8_t control = tca9548_select_byte(ch);
        CHECK_EQ(control, 1u << ch, "select byte is 1 << channel");
        CHECK_EQ(bus.write_reg(bus.ctx, TCA9548_ADDR, TCA9548_REG_SELECT, control), HAPTIC_OK,
                 "one-hot control byte accepted by the mux");
        CHECK_EQ(m.mux_select, ch, "control byte routes to its channel");
        uint8_t back = 0;
        CHECK_EQ(bus.read_reg(bus.ctx, TCA9548_ADDR, TCA9548_REG_SELECT, &back), HAPTIC_OK, "mux reads back");
        CHECK_EQ(back, control, "mux read-back is the control byte");
    }
    CHECK_EQ(m.mux_rejects, 0u, "no rejects for one-hot bytes");

    /* the regression: raw channel numbers */
    CHECK_EQ(bus.write_reg(bus.ctx, TCA9548_ADDR, TCA9548_REG_SELECT, 0), HAPTIC_ERR_IO, "raw channel 0 (no bits) refused");
    CHECK_EQ(bus.write_reg(bus.ctx, TCA9548_ADDR, TCA9548_REG_SELECT, 3), HAPTIC_ERR_IO, "raw channel 3 (two bits) refused");
    CHECK_EQ(bus.write_reg(bus.ctx, TCA9548_ADDR, TCA9548_REG_SELECT, 5), HAPTIC_ERR_IO, "raw channel 5 (two bits) refused");
    CHECK_EQ(bus.write_reg(bus.ctx, TCA9548_ADDR, TCA9548_REG_SELECT, 0x40), HAPTIC_ERR_IO, "bit 6 (no such channel) refused");
    CHECK_EQ(m.mux_rejects, 4u, "every bad control byte counted");
    CHECK_EQ(m.mux_select, 5, "a refused byte leaves the routing unchanged");

    /* the vtable's select path goes through the same contract */
    CHECK_EQ(bus.select_channel(bus.ctx, 2), HAPTIC_OK, "select_channel 2");
    CHECK_EQ(m.mux_select, 2, "select_channel routes channel 2");
    CHECK_EQ(mock_mux_control_byte(&m), 0x04, "control byte for channel 2 is 0x04");
    CHECK_EQ(bus.select_channel(bus.ctx, 6), HAPTIC_ERR_INVALID_ARG, "select_channel past the last dot refused");
}

static void test_runtime_pace(void)
{
    haptic_out h; mock_drv m; drv2605_bus bus;
    mock_init(&m); mock_bus(&bus, &m);
    haptic_out_init(&h, &bus);

    CHECK_EQ(haptic_out_cell_gap_ms(&h), CELL_GAP_DEFAULT_MS, "pace defaults to the spec default");
    CHECK_EQ(haptic_out_set_cell_gap_ms(&h, 10), CELL_GAP_MIN_MS, "pace clamps up to the minimum");
    CHECK_EQ(haptic_out_set_cell_gap_ms(&h, 9999), CELL_GAP_MAX_MS, "pace clamps down to the maximum");

    /* a word at the fastest pace: cells land pace apart, the tail gap is untouched */
    CHECK_EQ(haptic_out_set_cell_gap_ms(&h, CELL_GAP_MIN_MS), CELL_GAP_MIN_MS, "pace set to the minimum");
    buzz_rec r[8];
    CHECK_EQ(haptic_out_play_word(&h, "ziv"), HAPTIC_OK, "play ziv at min pace");
    int n = run_play(&h, r, 8);
    CHECK_EQ(n, 3, "ziv at min pace has 3 cells");
    check_buzz(r, 0, 0, 290, CELL_GAP_MIN_MS, 0x35);
    check_buzz(r, 1, 290 + CELL_GAP_MIN_MS, 170, CELL_GAP_MIN_MS, 0x0A);
    check_buzz(r, 2, 290 + CELL_GAP_MIN_MS + 170 + CELL_GAP_MIN_MS, 290, TAIL_GAP_MS, 0x27);

    /* a mark at a middle pace */
    CHECK_EQ(haptic_out_set_cell_gap_ms(&h, 300), 300, "pace 300 accepted");
    CHECK_EQ(haptic_out_play_mark(&h, 1), HAPTIC_OK, "play raz at pace 300");
    n = run_play(&h, r, 8);
    CHECK_EQ(n, 3, "raz has 3 cells");
    check_buzz(r, 0, 0, 290, 300, 0x17);
    check_buzz(r, 1, 590, 110, 300, 0x01);
    check_buzz(r, 2, 1000, 290, TAIL_GAP_MS, 0x35);

    /* a prefix at the slowest pace: the breath after the mark is not the pace */
    CHECK_EQ(haptic_out_set_cell_gap_ms(&h, CELL_GAP_MAX_MS), CELL_GAP_MAX_MS, "pace set to the maximum");
    CHECK_EQ(haptic_out_play_prefix(&h, HAPTIC_TAIL_MESSAGE), HAPTIC_OK, "play prefix at max pace");
    n = run_play(&h, r, 8);
    CHECK_EQ(n, 5, "prefix message = 3 cells + 2 tail beats");
    check_buzz(r, 0, 0, 290, CELL_GAP_MAX_MS, 0x35);
    check_buzz(r, 1, 290 + CELL_GAP_MAX_MS, 170, CELL_GAP_MAX_MS, 0x0A);
    check_buzz(r, 2, 290 + CELL_GAP_MAX_MS + 170 + CELL_GAP_MAX_MS, 290, PREFIX_BREATH_MS, 0x27);
    check_buzz(r, 3, 290 + CELL_GAP_MAX_MS + 170 + CELL_GAP_MAX_MS + 290 + PREFIX_BREATH_MS, 70, 160, 0);
    check_buzz(r, 4, 290 + CELL_GAP_MAX_MS + 170 + CELL_GAP_MAX_MS + 290 + PREFIX_BREATH_MS + 70 + 160, 70, TAIL_GAP_MS, 0);

    /* patterns carry their own gaps: the pace never touches them */
    CHECK_EQ(haptic_out_play_pattern(&h, HAPTIC_PAT_DOUBLE_TAP), HAPTIC_OK, "double tap at max pace");
    n = run_play(&h, r, 8);
    CHECK_EQ(n, 2, "double tap has 2 beats");
    check_buzz(r, 0, 0, 70, 160, 0);
    check_buzz(r, 1, 230, 70, TAIL_GAP_MS, 0);

    /* the pace survives a stop and a new play */
    haptic_out_stop(&h);
    CHECK_EQ(haptic_out_cell_gap_ms(&h), CELL_GAP_MAX_MS, "pace kept across stop");
}

/* Compile a word into a beat list from the generated tables — the same
 * derivation haptic_out's WORD mode makes, written independently. */
static uint16_t compile_word_beats(const char *word, uint16_t pace_ms, haptic_beat_ex *out)
{
    uint16_t n = 0;
    while (word[n] != '\0') { n++; }
    for (uint16_t i = 0; i < n; i++) {
        uint8_t li = (uint8_t) (word[i] - 'a');
        out[i].dot_mask = HAPTIC_LETTER_MASKS[li];
        out[i].buzz_ms = haptic_cell_ms(word[i]);
        out[i].gap_after_ms = (uint16_t) ((i == n - 1) ? TAIL_GAP_MS : pace_ms);
    }
    return n;
}

static void test_play_beats_equals_word(void)
{
    haptic_out h; mock_drv m; drv2605_bus bus;
    mock_init(&m); mock_bus(&bus, &m);
    haptic_out_init(&h, &bus);

    static const uint16_t paces[2] = { CELL_GAP_DEFAULT_MS, CELL_GAP_MIN_MS };
    for (int p = 0; p < 2; p++) {
        haptic_out_set_cell_gap_ms(&h, paces[p]);
        buzz_rec a[8], b[8];
        haptic_beat_ex beats[8];
        uint16_t nb = compile_word_beats("ziv", paces[p], beats);

        CHECK_EQ(haptic_out_play_word(&h, "ziv"), HAPTIC_OK, "word ziv");
        int na = run_play(&h, a, 8);
        CHECK_EQ(haptic_out_play_beats(&h, beats, nb), HAPTIC_OK, "beats ziv");
        CHECK_EQ(haptic_out_mode(&h), HAPTIC_OUT_MODE_BEATS, "mode is BEATS while a list plays");
        int nbp = run_play(&h, b, 8);
        CHECK_EQ(na, 3, "word ziv has 3 beats");
        CHECK_EQ(nbp, na, "beat list and word have the same beat count");
        for (int i = 0; i < na && i < nbp; i++) {
            CHECK_EQ(b[i].at, a[i].at, "beat list / word: start time");
            CHECK_EQ(b[i].buzz, a[i].buzz, "beat list / word: buzz");
            CHECK_EQ(b[i].gap, a[i].gap, "beat list / word: gap");
            CHECK_EQ(b[i].mask, a[i].mask, "beat list / word: dot mask");
        }
        /* END lands one tail gap after the last buzz in both */
        uint32_t last_end = b[nbp - 1].at + b[nbp - 1].buzz + b[nbp - 1].gap;
        CHECK_EQ(haptic_out_step(&h, last_end, NULL, NULL), 0, "beat list finished after its last gap");
        CHECK(h.beats == NULL, "the list is released at END (the caller may reuse the buffer)");
    }

    /* the dot events of a beat list go to the bus exactly as a word's do */
    {
        haptic_beat_ex one[1] = { { HAPTIC_LETTER_MASKS['z' - 'a'], 290, TAIL_GAP_MS } };
        CHECK_EQ(haptic_out_play_beats(&h, one, 1), HAPTIC_OK, "single beat");
        haptic_out_event_t ev;
        uint32_t now = haptic_out_step(&h, 0, &ev, NULL);    /* START */
        now = haptic_out_step(&h, now, &ev, NULL);           /* BUZZ */
        CHECK_EQ(ev, HAPTIC_OUT_EV_BUZZ, "beat buzz event");
        CHECK_EQ(mock_drive(&m, 0), DRV2605_DRIVE_DEFAULT, "dot 1 up for z");
        CHECK_EQ(mock_drive(&m, 1), 0, "dot 2 down for z");
        CHECK_EQ(mock_drive(&m, 2), DRV2605_DRIVE_DEFAULT, "dot 3 up for z");
        CHECK_EQ(mock_drive(&m, 4), DRV2605_DRIVE_DEFAULT, "dot 5 up for z");
        CHECK_EQ(mock_drive(&m, 5), DRV2605_DRIVE_DEFAULT, "dot 6 up for z");
        haptic_out_step(&h, now, &ev, NULL);                 /* buzz end */
        for (int ch = 0; ch < 6; ch++) { CHECK_EQ(mock_drive(&m, (uint8_t) ch), 0, "all dots silent after the beat"); }
        haptic_out_stop(&h);
    }

    /* a beat list reproduces a pattern too (mask 0 = whole-device beat) */
    {
        haptic_beat_ex pat[HAPTIC_END_OF_MESSAGE_LEN];
        for (int i = 0; i < HAPTIC_END_OF_MESSAGE_LEN; i++) {
            pat[i].dot_mask = 0;
            pat[i].buzz_ms = HAPTIC_END_OF_MESSAGE[i].buzz_ms;
            pat[i].gap_after_ms = HAPTIC_END_OF_MESSAGE[i].gap_after_ms;
        }
        buzz_rec a[8], b[8];
        CHECK_EQ(haptic_out_play_pattern(&h, HAPTIC_PAT_END_OF_MESSAGE), HAPTIC_OK, "pattern end-of-message");
        int na = run_play(&h, a, 8);
        CHECK_EQ(haptic_out_play_beats(&h, pat, HAPTIC_END_OF_MESSAGE_LEN), HAPTIC_OK, "beats end-of-message");
        int nb = run_play(&h, b, 8);
        CHECK_EQ(na, HAPTIC_END_OF_MESSAGE_LEN, "end-of-message has 4 beats");
        CHECK_EQ(nb, na, "beat list / pattern: beat count");
        for (int i = 0; i < na && i < nb; i++) {
            CHECK_EQ(b[i].at, a[i].at, "beat list / pattern: start time");
            CHECK_EQ(b[i].buzz, a[i].buzz, "beat list / pattern: buzz");
            CHECK_EQ(b[i].gap, a[i].gap, "beat list / pattern: gap");
            CHECK_EQ(b[i].mask, 0, "beat list / pattern: mask 0");
        }
    }

    /* invalid lists */
    haptic_beat_ex dummy[1] = { { 0, 70, 160 } };
    CHECK_EQ(haptic_out_play_beats(&h, NULL, 1), HAPTIC_ERR_INVALID_ARG, "NULL list rejected");
    CHECK_EQ(haptic_out_play_beats(&h, dummy, 0), HAPTIC_ERR_INVALID_ARG, "empty list rejected");
    CHECK_EQ(haptic_out_is_playing(&h), false, "a rejected list starts nothing");

    /* stop mid-list silences and releases the list */
    CHECK_EQ(haptic_out_play_beats(&h, dummy, 1), HAPTIC_OK, "one-beat list");
    haptic_out_step(&h, 0, NULL, NULL);
    haptic_out_step(&h, 0, NULL, NULL);
    haptic_out_stop(&h);
    CHECK(h.beats == NULL, "stop releases the list");
    CHECK_EQ(haptic_out_is_playing(&h), false, "stopped");
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
    test_mux_select_contract();
    test_runtime_pace();
    test_play_beats_equals_word();

    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}