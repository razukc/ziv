/* host_demo.c - host bench driver for the ziv_qemu app core.
 *
 * Runs the scripted boot demo (ramp-up -> prefix(message) -> word "ok" ->
 * end-of-message -> heartbeat) on a VIRTUAL clock - the same walk the bench
 * suite uses, via ziv_app_step() - and asserts the complete HAP line
 * sequence: every start time, mode, payload name, dot mask, buzz duration,
 * gap, and beat index. These 27 lines are the rung-1 fixture: tools/qemu_timeline.py
 * diffs the QEMU boot's HAP output against this exact sequence (wall-clock
 * tolerance), so a drift here is a drift in what the emulated chip will play.
 *
 * The fixture is DERIVED from the stage table in ziv_demo_sequence.h (which is
 * itself generated from the timing spec). host_demo.c asserts the live HAP
 * stream against k_demo_expected[], so the fixture cannot drift from the demo
 * it describes without regenerating ziv_demo_sequence.h.
 *
 * Build & run:  python ../run_ziv_tests.py   (from firmware/app/ziv_qemu)
 */
#include <stdio.h>
#include <string.h>
#include "ziv_app.h"
#include "mock_drv2605.h"

static int failures = 0;
static int checks = 0;

#define CHECK(cond, msg) do { \
    checks++; \
    if (!(cond)) { failures++; printf("FAIL: %s\n", msg); } \
} while (0)

/* k_demo_expected[] is re-exported from ziv_demo_sequence.h, which derives
 * the 27-line HAP fixture from the stage table + the generated timing tables.
 * The live HAP stream is asserted against it, so the fixture cannot drift from
 * the demo it describes without regenerating ziv_demo_sequence.h. */
#define N_EXPECTED k_demo_expected_count

#define MAX_LINES 64
static char lines[MAX_LINES][160];
static int n_lines;

static void sink(void *ctx, const char *line)
{
    (void) ctx;
    if (n_lines < MAX_LINES) {
        snprintf(lines[n_lines], sizeof lines[0], "%s", line);
        n_lines++;
    }
}

/* Walk the timeline with a virtual clock until the app goes idle. */
static void walk(ziv_app *app)
{
    uint32_t now = 0;
    int guard = 0;
    while (guard++ < 10000) {
        uint32_t next = ziv_app_step(app, now);
        if (next == 0) { break; }
        if (next > now) { now = next; }
        /* next == now: the caller should call again immediately (START or
         * a chained play's first event). */
    }
}

static void test_console_lookups(void)
{
    CHECK(ziv_pattern_index("double-tap") == 0, "double-tap index 0");
    CHECK(ziv_pattern_index("processing") == 5, "processing index 5");
    CHECK(ziv_pattern_index("end-of-message") == 6, "end-of-message index 6");
    CHECK(ziv_pattern_index("nope") == -1, "unknown pattern -> -1");
    CHECK(ziv_pattern_index(NULL) == -1, "NULL pattern -> -1");
    CHECK(ziv_mark_index("ziv") == 0, "ziv mark index 0");
    CHECK(ziv_mark_index("buz") == 4, "buz mark index 4");
    CHECK(ziv_mark_index("zzz") == -1, "unknown mark -> -1");
    CHECK(ziv_tail_index("message") == 0, "message tail index 0");
    CHECK(ziv_tail_index("error") == 2, "error tail index 2");
    CHECK(ziv_tail_index("x") == -1, "unknown tail -> -1");
}

static void test_scripted_demo_full_timeline(void)
{
    ziv_app app;
    mock_drv m;
    drv2605_bus bus;
    mock_init(&m);
    mock_bus(&bus, &m);
    n_lines = 0;
    ziv_app_init(&app, &bus, sink, NULL);

    CHECK(app.demo_done == false, "demo not done before start");
    ziv_app_run_demo(&app);
    walk(&app);

    CHECK(app.demo_done == true, "demo finished");
    if (n_lines != (int) N_EXPECTED) {
        printf("FAIL: line count got %d want %d\n", n_lines, (int) N_EXPECTED);
        for (int i = (int) N_EXPECTED; i < n_lines; i++) {
            printf("  extra[%d]: %s\n", i, lines[i]);
        }
        failures++;
    }
    checks++;

    int limit = n_lines < (int) N_EXPECTED ? n_lines : (int) N_EXPECTED;
    for (int i = 0; i < limit; i++) {
        if (strcmp(lines[i], k_demo_expected[i]) != 0) {
            failures++;
            printf("FAIL: line %d\n  got:  %s\n  want: %s\n", i, lines[i], k_demo_expected[i]);
        }
        checks++;
    }
}

static void test_manual_play_and_stop(void)
{
    ziv_app app;
    mock_drv m;
    drv2605_bus bus;
    mock_init(&m);
    mock_bus(&bus, &m);
    n_lines = 0;
    ziv_app_init(&app, &bus, sink, NULL);

    /* A manual play overrides/cancels the demo bookkeeping. */
    CHECK(ziv_app_play_word(&app, "hi") == 0, "manual word play ok");
    walk(&app);
    CHECK(n_lines == 4, "word play = START + 2 buzzes + END");
    CHECK(strncmp(lines[1], "HAP 0 BUZZ WORD hi 13 230 420 0", 160) == 0,
          "h cell line (dots 1-2-5 = 0x13, 3 dots)");
    CHECK(strncmp(lines[2], "HAP 650 BUZZ WORD hi 0A 170 420 1", 160) == 0,
          "i cell line (dots 2-4, 2 dots)");

    /* An unknown console payload fails with an error, not a crash. */
    CHECK(ziv_app_play_pattern(&app, ziv_pattern_index("nope")) != 0,
          "unknown pattern rejected");

    /* Stop mid-play silences and reports idle without further lines. */
    n_lines = 0;
    CHECK(ziv_app_play_prefix(&app, ziv_tail_index("reminder")) == 0, "prefix play ok");
    (void) ziv_app_step(&app, 0);                       /* START */
    (void) ziv_app_step(&app, 0);                       /* first buzz */
    ziv_app_stop(&app);
    n_lines = 0;
    (void) ziv_app_step(&app, 9999);
    CHECK(n_lines == 1 && strncmp(lines[0], "HAP 9999 END", 12) == 0,
          "stop mid-play ends cleanly");
    CHECK(ziv_app_step(&app, 99999) == 0, "idle after stop returns 0");
}

int main(void)
{
    test_console_lookups();
    test_scripted_demo_full_timeline();
    test_manual_play_and_stop();

    printf("%d checks, %d failures\n", checks, failures);
    return failures == 0 ? 0 : 1;
}
