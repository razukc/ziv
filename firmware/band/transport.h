/*
 * transport.h — the band's side of the relay protocol (architecture §6)
 * behind a frame vtable, so framing is the adapter's job:
 *
 *   host:   newline-delimited JSON over TCP      (host/frame_tcp_host.c)
 *   band:   esp_websocket_client text frames     (esp/transport_ws_esp.c)
 *   tests:  an in-memory scripted io             (host/test_band.c)
 *
 * The protocol layer owns: `hello` first (device key, profile, spec
 * version, pace, last_acked, held ids); `hello.ack` (prefs, resend list);
 * `utterance.open` / `utterance.body` / `utterance.cancel` / `pref.set` /
 * `pong` / `error` in; `progress` / `played` / `nack` / `input.text` /
 * `control` / `pref.changed` / `ping` out.  Reconnect with exponential
 * backoff and jitter; resume by last_acked + held on every hello.
 *
 * It also owns the hand-off queue → turn → frames, because every hand-off
 * produces a frame: the queue head loads when the turn is idle (at once in
 * `advance: auto`, after the wearer's tap in `advance: tap`), progress
 * frames follow the turn's phases, `played` follows DONE and acknowledges
 * the head, `nack` follows FAILED with the reason.
 *
 * Playback never waits for the link: a held utterance plays offline, and
 * the relay learns of it from last_acked on the next hello.  Frames the
 * link cannot carry are dropped and counted, never buffered silently.
 *
 * Durations: the haptic ones come from haptic_timing.h through the turn.
 * The network cadences (backoff, ping) are configuration; their defaults
 * are multiples of the spec's WORKING_EVERY_MS so this module carries no
 * millisecond literal of its own.
 *
 * Host-portable: no ESP-IDF types; cJSON for frames.
 */
#ifndef ZIV_BAND_TRANSPORT_H
#define ZIV_BAND_TRANSPORT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "queue.h"
#include "turn.h"

#ifndef TRANSPORT_RX_MAX
#define TRANSPORT_RX_MAX 16384      /* one inbound frame; a hello.ack carries up to the resend list */
#endif
#define TRANSPORT_BACKOFF_STEPS 5    /* the backoff doubles this many times, then holds */
#define TRANSPORT_PING_REPEATS 15    /* ping every 15 × WORKING_EVERY_MS (30 s at spec v4) */

/* Framing adapter.  connect: 0 ok / -1 failed.  send_frame: 0 / -1.
 * recv_frame: the frame length written to buf (NUL-terminated), 0 when
 * nothing arrived within timeout_ms, -1 when the link is gone (or a frame
 * did not fit cap).  close: drop the link. */
typedef struct {
    int (*connect)(void *ctx);
    int (*send_frame)(void *ctx, const char *text, size_t len);
    int (*recv_frame)(void *ctx, char *buf, size_t cap, uint32_t timeout_ms);
    void (*close)(void *ctx);
    void *ctx;
} band_frame_io;

typedef struct {
    const char *device_key;       /* 16..128 chars; from config, never a URL */
    turn_profile profile;
    uint32_t backoff_base_ms;     /* 0 → WORKING_EVERY_MS */
    uint32_t backoff_max_ms;      /* 0 → base << TRANSPORT_BACKOFF_STEPS */
    uint32_t ping_every_ms;       /* 0 → TRANSPORT_PING_REPEATS × WORKING_EVERY_MS */
    uint32_t seed;                /* jitter PRNG seed; 0 → a fixed one */
} band_transport_config;

typedef enum {
    TRANSPORT_OFFLINE = 0,        /* no link; a connect is scheduled */
    TRANSPORT_HELLO_SENT,         /* link up, waiting for hello.ack */
    TRANSPORT_READY               /* acked: frames flow */
} band_transport_state;

typedef void (*band_log_cb)(void *ctx, const char *line);   /* content-free diagnostics */

typedef struct {
    uint32_t connects, disconnects, frames_in, frames_out, frames_dropped, bad_frames, nacks, played, pongs;
} band_transport_counters;

typedef struct {
    band_frame_io *io;
    band_queue *queue;
    turn *turn;
    band_transport_config cfg;

    band_transport_state state;
    bool connected;
    uint32_t next_connect_ms;
    uint8_t attempts;
    uint32_t rng;
    uint32_t next_ping_ms;
    bool pong_due;

    bool advance_auto;            /* prefs.advance: auto (true) | tap (false) */
    bool tapped;                  /* the wearer released the queue (tap mode) */
    char wearer[ZIV_UTT_ID_MAX + 1];
    char device[ZIV_UTT_ID_MAX + 1];
    int relay_spec_version;       /* from hello.ack; -1 before */

    band_transport_counters n;
    uint32_t now_ms;              /* the clock of the current step (for events) */
    uint8_t *blob; size_t blob_cap;   /* persistence buffer; NULL = no persistence */
    band_log_cb log; void *log_ctx;

    char rx[TRANSPORT_RX_MAX];
    ziv_utterance scratch;
} band_transport;

void transport_init(band_transport *t, band_frame_io *io, band_queue *q, turn *tn, const band_transport_config *cfg);
void transport_set_log(band_transport *t, band_log_cb cb, void *ctx);
void transport_set_blob(band_transport *t, uint8_t *blob, size_t cap);

/* All due work at now_ms: (re)connect, hello, pings, inbound frames that
 * are already there (non-blocking), the turn, the queue hand-off.  Returns
 * the next deadline (0 = nothing scheduled). */
uint32_t transport_step(band_transport *t, uint32_t now_ms);

/* Block in the adapter for up to timeout_ms for one inbound frame and
 * handle it.  1 = a frame was handled, 0 = none, -1 = the link dropped
 * (a reconnect is scheduled).  Offline it returns 0 at once. */
int transport_wait(band_transport *t, uint32_t now_ms, uint32_t timeout_ms);

/* Feed one inbound frame (the adapters and tests use this).  0 handled,
 * -1 not a frame the band knows (counted). */
int transport_handle_frame(band_transport *t, const char *text, size_t len, uint32_t now_ms);

/* Wearer input and controls (chord keys on the band, scripted in tests). */
int transport_send_input_text(band_transport *t, const char *const *words, uint8_t n, const char *in_reply_to);
int transport_control(band_transport *t, turn_control_t action, uint32_t now_ms);
uint16_t transport_set_pace(band_transport *t, uint32_t pace_ms);   /* wearer-side: turn + pref.changed */

/* Drop the link now (a test lever; the adapter's -1 does the same). */
void transport_disconnect(band_transport *t, uint32_t now_ms);

/* The next backoff delay for the current attempt count (exposed for tests). */
uint32_t transport_backoff_ms(band_transport *t);

band_transport_state transport_state(const band_transport *t);
const char *transport_state_name(band_transport_state s);
const band_transport_counters *transport_counters(const band_transport *t);

#endif /* ZIV_BAND_TRANSPORT_H */
