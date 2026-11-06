/*
 * host_player.c — the band's conformance player (conformance/README.md).
 *
 *     host_player --profile <six_actuator|single_actuator> --pace <ms>
 *       stdin:  one utterance as JSON (a golden file, byte for byte)
 *       stdout: the timeline as JSON Lines, one beat per line:
 *               {"t_ms":int,"dot_mask":int,"buzz_ms":int,"label":str}
 *
 * This is the real renderer: the utterance decoder, the turn (the
 * renderer contract) and the haptic_out sequencer on the bench mock bus,
 * walked on a virtual clock exactly as the FreeRTOS loop walks it on the
 * band.  Every line comes from a HAPTIC_OUT_EV_BUZZ the sequencer itself
 * fired — the step's dot_mask and buzz_ms, at the virtual clock's now_ms —
 * so what the harness diffs against the reference is the firmware's own
 * testimony, not a model of it.
 *
 * A body_pending utterance is rendered as the reference renders it: the
 * header, one `processing` play, then the close — the player hands the turn
 * an empty body the moment the working phase starts, which is exactly "no
 * words ever came" without waiting device time for them.
 *
 * Exit 0 on success; 1 with the reason on stderr when the utterance does
 * not decode or the arguments are wrong.  Built by run_band_tests.py to
 * firmware/app/ziv_qemu/host_player, the path conformance/README.md names.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "haptic_out.h"
#include "drv2605.h"
#include "mock_drv2605.h"
#include "turn.h"
#include "utterance.h"

#define INPUT_MAX (64 * 1024)

typedef struct {
    turn *t;
    unsigned beats;
} player;

/* t_ms is the virtual clock, which starts at 0 with the utterance — the
 * same origin the reference uses (its first beat is at 0 unless a slot
 * cell's leading silence comes first, and then both say so). */
static void on_beat(void *ctx, uint32_t now_ms, const haptic_out_step_t *step, const char *label)
{
    player *p = (player *) ctx;
    printf("{\"t_ms\":%lu,\"dot_mask\":%u,\"buzz_ms\":%lu,\"label\":\"%s\"}\n",
           (unsigned long) now_ms, (unsigned) step->dot_mask,
           (unsigned long) step->buzz_ms, label);
    p->beats++;
}

static void on_event(void *ctx, turn_phase phase, int word_index, const char *label)
{
    player *p = (player *) ctx;
    (void) word_index; (void) label;
    if (phase == TURN_PHASE_WORKING) {
        /* the header part only: no body will ever come, play on to the close */
        (void) turn_set_body(p->t, NULL, 0);
    }
}

static int usage(const char *why)
{
    fprintf(stderr, "host_player: %s\nusage: host_player --profile <six_actuator|single_actuator> --pace <ms> < utterance.json\n", why);
    return 1;
}

int main(int argc, char **argv)
{
    int profile = -1;
    long pace = CELL_GAP_DEFAULT_MS;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--profile") == 0 && i + 1 < argc) {
            profile = turn_profile_from_name(argv[++i]);
            if (profile < 0) { return usage("unknown profile"); }
        } else if (strcmp(argv[i], "--pace") == 0 && i + 1 < argc) {
            char *end = NULL;
            pace = strtol(argv[++i], &end, 10);
            if (end == NULL || *end != '\0') { return usage("--pace wants an integer"); }
        } else {
            return usage("unknown argument");
        }
    }
    if (profile < 0) { return usage("--profile is required"); }
    if (pace < 0) { pace = 0; }

    static char input[INPUT_MAX + 1];
    size_t len = fread(input, 1, INPUT_MAX, stdin);
    if (len == INPUT_MAX && fgetc(stdin) != EOF) { return usage("utterance larger than the input buffer"); }
    input[len] = '\0';

    static ziv_utterance utt;
    ziv_utt_err err = utterance_decode_json(input, len, &utt);
    if (err != ZIV_UTT_OK) {
        fprintf(stderr, "host_player: utterance refused: %s\n", utterance_err_name(err));
        return 1;
    }

    static mock_drv mock;
    static drv2605_bus bus;
    static haptic_out h;
    static turn t;
    mock_init(&mock);
    mock_bus(&bus, &mock);
    if (drv2605_init(&bus) != HAPTIC_OK) { fprintf(stderr, "host_player: bus init failed\n"); return 1; }
    haptic_out_init(&h, &bus);
    turn_init(&t, &h, (turn_profile) profile, (uint32_t) pace);

    player p = { &t, 0 };
    turn_set_callbacks(&t, on_event, &p, on_beat, &p);
    if (!turn_load(&t, &utt)) { fprintf(stderr, "host_player: turn busy\n"); return 1; }

    /* the virtual clock: jump to each deadline the pull model returns */
    uint32_t now = 0;
    for (unsigned guard = 0; guard < 1000000u; guard++) {
        uint32_t next = turn_step(&t, now);
        if (next == 0) { break; }
        if (next > now) { now = next; }
    }
    if (turn_last_result(&t) != TURN_RESULT_PLAYED) {
        fprintf(stderr, "host_player: utterance ended with %s\n", turn_result_name(turn_last_result(&t)));
        return 1;
    }
    return 0;
}
