/*
 * host_transport_test.c — the C side of ladder rung 3: the band's transport
 * on a virtual clock, over real loopback TCP, against host/fake_relay.py.
 *
 *     host_transport_test --port <n> [--host 127.0.0.1] [--key <device key>]
 *
 * The haptics run on a virtual clock (every deadline is jumped to, nothing
 * sleeps), the network runs in real time: after each step the test waits a
 * few real milliseconds for the relay's frames, so what the relay sees is
 * the band's real frame order.  The relay asserts that order; this side
 * asserts what the band observed (prefs applied, plays acknowledged, the
 * cancel honoured, the pong seen) and exits 0 only when both hold.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "drv2605.h"
#include "frame_tcp_host.h"
#include "haptic_out.h"
#include "mock_drv2605.h"
#include "queue.h"
#include "transport.h"
#include "turn.h"

#define B_ID "relay-open-b-0001"

static int failures = 0;
static int checks = 0;
#define CHECK(cond, msg) do { checks++; if (!(cond)) { failures++; printf("FAIL: %s\n", msg); } } while (0)

static void log_line(void *ctx, const char *line) { (void) ctx; fprintf(stderr, "  %s\n", line); }

int main(int argc, char **argv)
{
    const char *host = "127.0.0.1";
    const char *key = "band-test-key-0123456789";
    long port = 0;
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--port") == 0 && i + 1 < argc) { port = strtol(argv[++i], NULL, 10); }
        else if (strcmp(argv[i], "--host") == 0 && i + 1 < argc) { host = argv[++i]; }
        else if (strcmp(argv[i], "--key") == 0 && i + 1 < argc) { key = argv[++i]; }
    }
    if (port <= 0 || port > 65535) { fprintf(stderr, "usage: host_transport_test --port <n>\n"); return 2; }

    static mock_drv mock; static drv2605_bus bus; static haptic_out h; static turn t;
    static band_queue q; static band_transport tr; static frame_tcp_ctx tcp; static band_frame_io io;
    static uint8_t blob[BAND_QUEUE_BLOB_MAX];
    mock_init(&mock); mock_bus(&bus, &mock);
    (void) drv2605_init(&bus);
    haptic_out_init(&h, &bus);
    turn_init(&t, &h, TURN_PROFILE_SIX_ACTUATOR, CELL_GAP_DEFAULT_MS);
    band_queue_init(&q, NULL);
    frame_tcp_io(&io, &tcp, host, (uint16_t) port);
    band_transport_config cfg;
    memset(&cfg, 0, sizeof cfg);
    cfg.device_key = key;
    cfg.profile = TURN_PROFILE_SIX_ACTUATOR;
    cfg.seed = 7;
    transport_init(&tr, &io, &q, &t, &cfg);
    transport_set_log(&tr, log_line, NULL);
    transport_set_blob(&tr, blob, sizeof blob);

    bool saw_pace_300 = false, saw_pace_500 = false, saw_pong = false, sent_final = false;
    uint32_t vnow = 0;
    int lost = 0;
    for (int iter = 0; iter < 20000; iter++) {
        uint32_t next = transport_step(&tr, vnow);
        if (transport_state(&tr) == TRANSPORT_READY && turn_pace(&t) == 300) { saw_pace_300 = true; }
        if (turn_pace(&t) == 500) { saw_pace_500 = true; }

        /* real-time wait for the relay: longer when idle so a pong can land */
        bool idle = !turn_is_loaded(&t) && band_queue_count(&q) == 0;
        int got = transport_wait(&tr, vnow, idle ? 200 : 10);
        while (got > 0) { got = transport_wait(&tr, vnow, 2); }
        if (got < 0) { lost = 1; break; }
        if (tr.n.pongs > 0) { saw_pong = true; }

        /* the scenario's end: three played, queue empty, pref.set seen, a pong seen */
        if (!sent_final && tr.n.played == 3 && band_queue_count(&q) == 0 && !turn_is_loaded(&t) && saw_pace_500 && saw_pong) {
            (void) transport_set_pace(&tr, 350);
            (void) transport_control(&tr, TURN_CTL_REPLAY, vnow);   /* no utterance: the frame still shows its shape */
            const char *ws[1] = { "yes" };
            (void) transport_send_input_text(&tr, ws, 1, B_ID);
            sent_final = true;
        }
        if (sent_final) {
            /* wait for the relay to close */
            int r = transport_wait(&tr, vnow, 500);
            if (r < 0) { lost = 1; break; }
            continue;
        }
        if (next > vnow) { vnow = next; } else { vnow += 1; }
    }

    CHECK(saw_pace_300, "hello.ack prefs applied (pace 300)");
    CHECK(tr.n.played == 3, "three utterances played (resend, A, B)");
    CHECK(band_queue_count(&q) == 0, "queue empty at the end");
    CHECK(strcmp(band_queue_last_acked(&q), B_ID) == 0, "last_acked is B");
    CHECK(saw_pace_500, "pref.set applied (pace 500)");
    CHECK(saw_pong, "a ping was answered");
    CHECK(tr.n.nacks == 0, "no nack was needed");
    CHECK(sent_final, "the final frames were sent");
    CHECK(lost == 1, "the relay closed the link after input.text");
    printf("%d checks, %d failures (frames in %u, out %u, dropped %u)\n", checks, failures,
           (unsigned) tr.n.frames_in, (unsigned) tr.n.frames_out, (unsigned) tr.n.frames_dropped);
    return failures ? 1 : 0;
}
