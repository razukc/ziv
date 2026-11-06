# client — the web device renderer

The web renderer is a *device*, not a console: it implements the renderer
contract of [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) §5.1 for the
`single_actuator` profile — a phone's one motor, a letter as six time slots.
It speaks the wire from `ziv.wire` (hello first, `progress`, `played`,
`nack`, controls, prefs both ways), keeps a bounded persisted queue, plays
each utterance with a self-correcting local scheduler from durations derived
at runtime from the relay's `GET /spec`, and reports back when the close has
played. It is the **reference web implementation** of the contract and the
model the native phone app will follow.

It is also **foreground-only, by the browser's nature.** Browsers do not
vibrate a hidden page: when the tab is hidden or the screen locks, playback
stops, the device sends `nack hidden`, and the relay returns the utterance to
pending and offers it again after the next hello. The page says this at the
top. The wearer's renderer is the native phone app (not yet built); until it
exists this page is a foreground demo and operator view, labelled as exactly
that.

```
client/
  index.html          the page template; the build fills the hashed asset names
  build.mjs           esbuild -> dist/: the page, conformance.js, device-cli.js
  src/
    device.ts         the renderer state machine: queue, one playing, controls, frames
    sequencer.ts      (utterance, spec, pace, profile) -> timeline; the reference's model
    player.ts         deadline scheduler over an injectable clock and vibrate(); drift never accumulates
    queue.ts          held utterances, persisted (IndexedDB, memory otherwise) so a reload resumes
    transport.ts      the WebSocket: hello first, backoff, fresh hello with last_acked + held on reconnect
    spec.ts           GET /spec resolved into every duration the client uses (v4, with v3 fallbacks)
    wire.ts           the frames and their checks
    words.ts          compose-box normalisation (letters, digits spelled out, anything else refused)
    app.ts, main.ts   the page: DOM wiring with the environment injected
    conformance.ts    the conformance player entry
    device-cli.ts     the headless device driver entry
    virtual-clock.ts  the headless driver's instant/paced timers
  test/               node:test suites; the page mounts under happy-dom
  dist/               build output (gitignored): index.html, main.<hash>.js, app.<hash>.css, conformance.js, device-cli.js
```

## Build and test

Node 24 and npm. Dependencies are dev-only and pinned exactly.

```bash
cd client
npm ci
npm run typecheck     # tsc, no emit
npm test              # node --test: sequencer, player, queue, device, words, virtual clock, page (happy-dom), headless CLI, conformance
npm run build         # -> dist/
```

Last run: `npm test` — 55 tests, 55 pass. No service worker, by design.

The relay serves `dist/` at `/client/` when it exists (`ZIV_CLIENT_DIST`
overrides the path; `off` disables it). Open the page, paste the relay URL
and a device key — or an enroll code from the console under *Enroll this
browser as a device* — and press **Start**. The page shows status, what is
playing, the controls (Stop, Replay, Replay word, Skip word, Advance), the
preferences (pace; wait for a tap before the next message; an in-memory
session history, off by default), a compose box for replies, and a wire log
of frame types and ids — never message text.

## The headless device: `dist/device-cli.js`

The same `Device` as the page, with the DOM and the motor replaced by JSON
lines on stdout. The integration tests (`tests/test_integration_device.py`)
drive it against a live relay; it is also a bench tool.

```
node dist/device-cli.js --relay ws://127.0.0.1:8787 --key <device key> \
    [--profile single_actuator|six_actuator] [--clock instant|real] \
    [--utterances N] [--idle-exit MS] [--hidden-once]
```

| Flag | Meaning |
|---|---|
| `--relay URL` | the relay (`ws://`, `wss://`, `http://` or `https://`; `/ws` optional). The spec is fetched from its `/spec` over HTTP, as the page does |
| `--key KEY` | the device key for `hello` (at least 16 characters); or |
| `--enroll CODE [--name NAME]` | exchange an enroll code for a key first (`POST /devices/enroll`); the key is printed once in the `enrolled` event |
| `--profile P` | the renderer profile declared in `hello` (default `single_actuator`) |
| `--clock instant\|real` | `instant` (default): playback deadlines are jumped, so a 10 s utterance plays in milliseconds while `played.started_ms`/`closed_ms` report the real durations; the one wait on the relay (a pending body) runs at 1/`--pace-divisor` real time (default 100). `real`: wall-clock timers, as on a phone. The transport's ping and reconnect backoff are wall-clock in both modes |
| `--utterances N` | exit 0 once N utterances have been played |
| `--idle-exit MS` | exit 0 after MS real milliseconds with nothing held, playing or arriving |
| `--hidden-once` | `nack hidden` for the first `utterance.open`, then reconnect with a fresh hello after `--hidden-reconnect-ms` (default 250), so the relay's re-offer path is exercised |

stdout: one JSON object per line, each with `event` and `t` (real ms since
start): `spec`, `enrolled`, `socket`, `hello.ack`, `open`, `body`, `cancel`,
`progress`, `played`, `nack`, `error`, `refused`, `exit`. stderr: the wire
log (frame types and ids, never message text).

Exit codes: **0** done (`--utterances` reached or idle); **1** bad arguments
or no spec; **3** the relay refused the device key (socket closed 4401).

## Conformance

`dist/conformance.js` is this renderer's player for the cross-renderer
oracle: an utterance on stdin, the timeline as JSON Lines on stdout, under
fake timers so nothing waits.

```bash
cd ..   # the repository root
.venv/bin/python conformance/run.py --player "node client/dist/conformance.js" --profile single_actuator
.venv/bin/python conformance/run.py --player "node client/dist/conformance.js" --profile six_actuator
```

Last run: 12/12 PASS on both profiles. Flags: `--spec <path>` (default
`docs/haptic-timing.json` at the repo root), `--profile`, `--pace <ms>`. The
interface is documented in [conformance/README.md](../conformance/README.md).

## Limits

- Foreground only: nothing plays while the page is hidden or the screen is
  off. A message channel needs the native app; this page demonstrates the
  contract.
- Not yet exercised in a real browser on a phone. The page is tested under
  happy-dom and the renderer under fake timers; the browser e2e tests in
  `tests/e2e/` are written and collected but skip where Chromium cannot
  launch. Whether a 50 ms pulse and a 30 ms slot gap read on a phone motor is
  unknown until a wearer has felt them.
- Without a Vibration API (desktop browsers, iOS) the page is an operator
  view only; it still connects, acknowledges and shows the timeline.
- No plaintext history by default; the optional session history lives in
  memory and is cleared on reload.
