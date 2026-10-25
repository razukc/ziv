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
#ifndef ZIV_DEMO_SEQUENCE_H
#define ZIV_DEMO_SEQUENCE_H

#include "haptic_out.h"

/* demo_stage_t: one entry per stage; mode picks the union member. */
typedef struct {
    haptic_out_mode_t mode;
    union {
        haptic_pattern pat;
        haptic_tail tail;
        const char *word;
        uint8_t mark;
    } u;
} demo_stage_t;

#ifdef __cplusplus
extern "C" {
#endif

extern const int k_demo_stage_count;
extern const demo_stage_t k_demo_sequence[];
extern const char *const k_demo_expected[];
extern const int k_demo_expected_count;

#ifdef __cplusplus
}
#endif

#endif /* ZIV_DEMO_SEQUENCE_H */
