/* GENERATED FILE - do not edit by hand.

 * Single source of truth for the ziv_qemu scripted boot demo:
 *   - the stage table k_demo_sequence[] is defined once (in the .c)
 *   - the HAP fixture k_demo_expected[] is DERIVED from the same
 *     stage table + the generated timing tables, so reordering or
 *     extending the demo cannot silently desync the fixture from
 *     the demo it describes.

 * Demo intent: ramp-up -> prefix(message) -> word ok ->
 *   end-of-message -> heartbeat (every playback mode).

 * Regenerate: python tools/haptic_timing.py --write
 * Drift guard: tools/haptic_timing.py --verify diffs both files,
 *   same as the other generated consumers (feel-tool JS block,
 *   firmware header, Python timing module).
 */
#include "ziv_demo_sequence.h"

/* The stage table -- the demo itself. ziv_app.c chains this at runtime. */
const demo_stage_t k_demo_sequence[5] = {
    { HAPTIC_OUT_MODE_PATTERN, .u.pat = 3 },
    { HAPTIC_OUT_MODE_PREFIX, .u.tail = 0 },
    { HAPTIC_OUT_MODE_WORD, .u.word = "ok" },
    { HAPTIC_OUT_MODE_PATTERN, .u.pat = 6 },
    { HAPTIC_OUT_MODE_PATTERN, .u.pat = 4 }
};
const int k_demo_stage_count = 5;

/* The derived rung-2 fixture -- host_demo.c asserts the live HAP stream
 * against this, line by line.  A pure function of k_demo_sequence[] plus
 * the generated timing tables; never hand-edited. */
const char *const k_demo_expected[27] = {
    "HAP 0 START PATTERN ramp-up",
    "HAP 0 BUZZ PATTERN ramp-up 00 50 90 0",
    "HAP 140 BUZZ PATTERN ramp-up 00 90 120 1",
    "HAP 350 BUZZ PATTERN ramp-up 00 140 160 2",
    "HAP 650 BUZZ PATTERN ramp-up 00 200 420 3",
    "HAP 1270 END",
    "HAP 1270 START PREFIX message",
    "HAP 1270 BUZZ PREFIX message 35 290 420 0",
    "HAP 1980 BUZZ PREFIX message 0A 170 420 1",
    "HAP 2570 BUZZ PREFIX message 27 290 550 2",
    "HAP 3410 BUZZ PREFIX message 00 70 160 3",
    "HAP 3640 BUZZ PREFIX message 00 70 420 4",
    "HAP 4130 END",
    "HAP 4130 START WORD ok",
    "HAP 4130 BUZZ WORD ok 15 230 420 0",
    "HAP 4780 BUZZ WORD ok 05 170 420 1",
    "HAP 5370 END",
    "HAP 5370 START PATTERN end-of-message",
    "HAP 5370 BUZZ PATTERN end-of-message 00 200 120 0",
    "HAP 5690 BUZZ PATTERN end-of-message 00 140 120 1",
    "HAP 5950 BUZZ PATTERN end-of-message 00 90 120 2",
    "HAP 6160 BUZZ PATTERN end-of-message 00 50 420 3",
    "HAP 6630 END",
    "HAP 6630 START PATTERN heartbeat",
    "HAP 6630 BUZZ PATTERN heartbeat 00 70 120 0",
    "HAP 6820 BUZZ PATTERN heartbeat 00 70 420 1",
    "HAP 7310 END",
};
const int k_demo_expected_count = 27;
