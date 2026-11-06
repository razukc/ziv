# firmware/band — the band as a device renderer

The band side of the architecture (docs/ARCHITECTURE.md §5.1–§5.3, §6):
an utterance arrives on the wire, the band holds it whole, plays it exactly
as the reference renderer defines, acknowledges it, and keeps time with its
own clock whatever the link does. The existing `haptic_out` sequencer stays
the heart; this module is everything around it.

```
firmware/band/
  utterance.h/.c    the decoded utterance (cJSON) — every schema cap a distinct error, nothing truncated
  turn.h/.c         the renderer contract: one utterance → segments → haptic_out_play_beats()
  queue.h/.c        the bounded queue (cap 20, de-dup by id, last_acked, a persistence vtable)
  transport.h/.c    the relay protocol behind a frame vtable; backoff, resume, queue→turn→frames
  host/
    host_player.c          the conformance player → firmware/app/ziv_qemu/host_player
    frame_tcp_host.c/.h    the host frame adapter: newline-delimited JSON over TCP
    queue_file_host.c/.h   the host persistence adapter: one file
    test_band.c            the C unit tests
    fake_relay.py          a relay for the transport test (validates frames with ziv.wire)
    host_transport_test.c  the C side of the loopback transport test
  esp/                     the ESP-IDF glue — written, NOT compiled here (see esp/README.md)
  run_band_tests.py        builds and runs all of the above
../third_party/cJSON/      cJSON 1.7.18 (MIT), the host's JSON; the device uses IDF's `json`
```

## What runs where

| Piece | Host (bench) | Band (ESP32-S3) |
|---|---|---|
| `haptic_out` sequencer, `drv2605` driver | mock bus (`mock_drv2605.c`) | `drv2605_i2c_esp32.c` on `driver/i2c_master.h` |
| `utterance`, `turn`, `queue`, `transport` | as is | as is |
| JSON | `firmware/third_party/cJSON` | IDF `json` component (the same library) |
| frame adapter | `host/frame_tcp_host.c` (TCP lines) | `esp/transport_ws_esp.c` (websocket text frames) |
| queue store | `host/queue_file_host.c` | `esp/queue_nvs_esp.c` |
| clock | virtual (every deadline jumped to) | `esp_timer`, blocking in the websocket inbox |
| main | `host_player.c`, `host_transport_test.c` | `esp/band_main.c` |

Everything above the adapters is one code path. The host proofs run the
same `turn.c` and `transport.c` the band will run.

## The renderer contract, as implemented

A turn plays one utterance in the reference's order
(`ziv/haptics/reference.py`): the prefix when present (mark cells at the
pace, `PREFIX_BREATH_MS` after the last, the kind's tail from
`HAPTIC_KIND_TAIL_TABLE`), the kind's cue from `HAPTIC_KIND_CUE_TABLE`,
`processing` repeated every `WORKING_EVERY_MS` while the body is pending,
the words (the pace inside a word, `WORD_GAP_MS` between words),
`TAIL_GAP_MS`, then `end-of-message`. It compiles one segment at a time
into a bounded `haptic_beat_ex` buffer (32 letters × 6 slots) and hands it
to `haptic_out_play_beats()`, so the HAP log and the step model are the
sequencer's own.

Profiles: `six_actuator` drives a cell's dots together for
`haptic_cell_ms()`; `single_actuator` plays six slots in `HAPTIC_SLOT_ORDER`
(`SLOT_MS` per raised dot, `SLOT_GAP_MS` after every slot but the last,
`COLUMN_GAP_MS` more after the third). A beat list has no "silence before
the first beat", so a slot cell's leading silence rides on the previous
beat's gap — or, for a segment's first cell, delays the segment's start.

Phase events (`cue`, `working`, `word n`, `close`, `done`, `failed`) become
`progress` / `played` / `nack` frames in the transport. Controls: `stop`
(silent, kept for replay), `replay`, `replay_word`, `skip`, `advance`
(mid-play: `nack cancelled_by_wearer`). Pace is a runtime variable, clamped
to the spec envelope, applied from the next segment, synchronised both ways
(`pref.set` in, `pref.changed` out). Another utterance arriving mid-play
gets its cue interjected at the next segment boundary ("announce, then
wait").

Body timeout is a count, not a millisecond: `TURN_BODY_TIMEOUT_REPEATS`
(12) `processing` repeats, then the error pattern and `nack body_timeout`.
A relay-reported body error plays the error pattern and is not nacked (the
relay already knows).

Every duration comes from `haptic_timing.h`. The network cadences
(backoff base/cap, ping period) are configuration whose defaults are
multiples of `WORKING_EVERY_MS`.

## The protocol, as implemented

`hello` first (device key, profile, spec version, pace, `last_acked`, held
ids). `hello.ack` applies prefs and pushes the resend list. `utterance.open`
decodes and enqueues (duplicate ids are ignored; the 21st is `nack
queue_full`; a spec mismatch is `nack spec_mismatch`; unencodable letters
`nack unencodable`). `utterance.body` completes the current or a held
utterance (or marks it failed). `utterance.cancel` drops it silently.
`pref.set` applies. `ping`/`pong` is liveness: an unanswered ping drops the
link. Reconnect: exponential backoff with equal jitter, doubling
`TRANSPORT_BACKOFF_STEPS` times then holding; every reconnect resumes by
`last_acked` + held. Playback never waits for the link; frames the link
cannot carry are dropped and counted.

## Running the proofs

```sh
python3 firmware/band/run_band_tests.py
```

Builds with the repo's `-std=c11 -Wall -Wextra -Werror`, then:

1. `host/band_tests` — the unit tests (decoder, queue + file store, turn
   goldens hand-derived from `haptic_timing.h` on both profiles, beat mode,
   controls, transport against a scripted adapter);
2. `firmware/app/ziv_qemu/host_player` — the conformance player, then
   `.venv/bin/python conformance/run.py --player … --profile
   six_actuator` and `--profile single_actuator` (both must be 12/12);
3. `host/host_transport_test` against `host/fake_relay.py` over loopback:
   the relay validates every up frame against `ziv.wire` and asserts
   progress(cue) → progress(word…) → progress(close) → played, in queue
   order, with a cancel honoured and a ping answered.

Exit 0 = green; 1 = a build or check failed; 2 = no compiler or no venv.
The player alone:

```sh
firmware/app/ziv_qemu/host_player --profile single_actuator --pace 420 < conformance/golden/message_two_words.json
```

## What is unverified

- Everything in `esp/` and `firmware/haptic_out/drv2605_i2c_esp32.c`'s
  device path: written against ESP-IDF 5.x, never compiled (no IDF here).
  The host build compiles `drv2605_i2c_esp32.c` to its stubs so the file at
  least parses under the warning flags.
- The feel. The host proves timing to the millisecond against the oracle;
  whether a 30 ms slot gap reads on skin is ladder rung H.
- TLS and the real relay's websocket: the fake relay speaks the frames over
  plain TCP lines; the websocket adapter is the unverified part above.
