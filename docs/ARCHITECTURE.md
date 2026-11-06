# Ziv architecture — the target shape

**Status:** proposed target architecture, written 2026-11-06 after a full review
of the tree on the `product` branch. It describes the system Ziv should become.
Section 13 maps the current code onto it. Nothing here changes behaviour by
itself; it is the reference for the work that will.

**Scope:** the relay, the devices that render on the wearer's skin, the wire
between them, storage, the console, and how all of it is tested and deployed.
The product plan ([HAPTIC_COMPANION_PLAN.md](HAPTIC_COMPANION_PLAN.md)) says
*what* Ziv is for and which interaction invariants it must keep. This document
says *how* the software is shaped so those invariants hold by construction.

---

## 1. Principles

1. **The device renders; the relay sequences.** A haptic channel is slow,
   serial, and worn by a body that moves in and out of radio range. The only
   place that can keep a rhythm honest is the device, with its own clock. The
   relay decides *what* plays and *in what order*; it never paces a motor.
2. **One unit, owned whole.** Everything the wearer feels is an *utterance*
   (section 2): a complete, replayable thing a device can hold, play, pause,
   replay and acknowledge without asking the relay anything.
3. **Delivery means acknowledged.** An utterance is delivered when the device
   reports that its close played. Bytes leaving a socket prove nothing on a
   phone in a pocket.
4. **At-least-once, idempotent by id.** Reconnects resume from the last
   acknowledged id; devices de-duplicate by id. Redelivery is the failure
   mode, never silent loss.
5. **A pure core.** Every decision the relay makes is a function of state, an
   event and a clock reading. I/O lives in adapters around it. The core runs
   in milliseconds under property-based tests.
6. **Bounded and loud.** Every queue has a cap, every refusal reaches the
   sender with a reason, every drop is counted. Nothing degrades silently.
7. **One timing source.** `docs/haptic-timing.json` defines every buzz and
   gap. Generated tables feed every renderer, and a reference renderer turns
   an utterance into the expected timeline that real renderers are diffed
   against.
8. **Accessible by construction.** The wearer is deaf-blind. Any surface the
   wearer operates must work with a refreshable braille display and a screen
   reader, and nothing may depend on seeing or hearing a transient.
9. **Private by default.** The haptic output is private by physics; the rest
   of the system must not undo that with logs, histories or open endpoints.

### Why this shape

The review found that the current tree pacing playback from the server tied
the scheduler's control flags into cell timing, so pausing reminders froze
the event loop and quitting them collapsed every later dwell. It found
"delivered" set when a frame was sent, with nothing to tell a pocketed phone
from a felt message. It found three independent players of the same timing
spec with no shared contract. And it found the phone's single motor carrying
dot counts, not letters. Each of those is a consequence of where the
responsibilities sat, not of a typo, and each disappears once the device owns
rendering and the relay owns sequencing.

---

## 2. The utterance

An utterance is the unit the wearer feels. It carries words and intent, never
milliseconds.

```json
{
  "v": 1,
  "id": "01J9Z9W7K2Q7E8ZK9XQ4G2T1MB",
  "wearer": "w_1",
  "kind": "reminder",
  "from": { "sender": "agent", "label": "pills" },
  "prefix": { "mark": "ziv", "tail": "reminder" },
  "words": ["meds", "nine"],
  "body_pending": false,
  "not_before": "2026-11-06T09:00:00Z",
  "expires": "2026-11-06T10:00:00Z",
  "spec_version": 3
}
```

- `kind` selects the arrival cue and the tail after the name mark:
  `message`, `reminder`, `error`, `system`. New kinds are added to the spec,
  not to code.
- `prefix` is present on unsolicited utterances (plan §4 invariant 1: the
  wearer learns who is speaking before the content). A reply to the wearer's
  own compose has none.
- `words` are lower-case `a`–`z` words. The relay normalises input before
  admission: digits become words deterministically, punctuation is dropped,
  and any character without a cell is **refused** with a reason unless the
  sender opts into lossy transliteration. The admission response echoes the
  exact words that will be felt.
- `body_pending: true` is the agent path: the relay sends the header the
  instant an intent fires so the device can cue and tick while the model
  writes the line. A second frame carries the words, or an error.
- `not_before` and `expires` give late delivery a meaning. A reminder that
  arrives after `expires` is dropped and counted, or played with the late
  tail if the wearer prefers; it never replays hours later as if on time.
- `spec_version` lets a device refuse an utterance it cannot render
  faithfully instead of guessing.

There is no letter cap in the utterance. Length is a **time budget**: the
reference renderer computes how long the utterance takes on the target
device's profile at the wearer's current pace, and admission refuses anything
over the budget with a 413 that states the budget. The agent's composer is
held to the same function. Nothing is ever sliced.

---

## 3. Roles and data flow

```
 senders (contacts, console, webhooks)      the agent (intents, schedule)
            │                                          │
            │  POST utterance                          │  due → compose → utterance
            ▼                                          ▼
 ┌──────────────────────────────── relay ────────────────────────────────┐
 │  admission (auth, normalise, time budget, cap)                        │
 │  outbox per wearer:  pending → sent → playing → played                │
 │                                     ↘ failed | expired | cancelled    │
 │  delivery policy: primary device, failover after a window             │
 │  SQLite: wearers · devices · senders · utterances · schedule · prefs  │
 └───────────────┬───────────────────────────────────────▲───────────────┘
                 │ utterance.open / utterance.body        │ progress · played
                 ▼                                        │ nack · input · control
 ┌──────────────────────── device renderer ─────────────────────────────┐
 │  band: 6 LRAs, chord keys, pull-model sequencer, local queue, ack    │
 │  phone: native app, 1 motor in 6 time slots, background delivery     │
 └──────────────────────────────────────────────────────────────────────┘
```

Three roles, and the boundaries between them are data formats:

- **Senders** produce utterances through the HTTP API. The scheduler and the
  agent are senders too; they go through the same admission path as a
  contact's message.
- **The relay** admits, orders, targets and tracks. It holds the wearer's
  durable state: the outbox, the schedule, preferences, enrolled devices.
- **Device renderers** play one utterance at a time and report back. The
  wearer's controls live here.

---

## 4. The relay

### 4.1 The core

A pure module with no I/O. Its types: `Wearer`, `Device`, `Sender`,
`Utterance`, `OutboxEntry`, `ScheduleEntry`, `Prefs`. Its functions take the
relevant slice of state, an event and `now`, and return the new slice plus a
list of effects (`send_to_device`, `notify_sender`, `log_event`). Events are:
`utterance_submitted`, `device_hello`, `device_progress`, `device_played`,
`device_nack`, `device_gone`, `schedule_due`, `compose_finished`,
`compose_failed`, `tick`.

The outbox state machine:

| State | Meaning | Leaves on |
|---|---|---|
| `pending` | admitted, no device has it | a device with capacity connects → `sent` |
| `sent` | handed to one device, not yet started | `progress(cue)` → `playing`; no ack within the window → failover, back to `pending` for the next device |
| `playing` | the device reported the cue or a word | `played` → `played`; `nack` → `failed`; device gone → `pending` |
| `played` | the device acknowledged the close | retention |
| `failed` | device refused or the body never came | retention; the sender is told |
| `expired` | passed `expires` before playing | retention; counted |
| `cancelled` | the sender or wearer withdrew it | retention |

One cap bounds `pending + sent + playing` per wearer. At the cap, admission
refuses with 429 and the reason. There is no separate "inbox" and no separate
"queue": an utterance waiting for a device and an utterance waiting behind the
current one are the same row in different states.

### 4.2 Admission

In order: authenticate the sender; validate the body against the schema with
hard size limits; normalise text to words and refuse unencodable characters;
compute the time budget for the wearer's primary device profile and pace;
check the cap; write the row and return the normalised words, the id and the
state. A sender can poll or subscribe to that id's state changes.

### 4.3 Delivery policy

Each wearer has an ordered list of enrolled devices and a primary. An
utterance is `sent` to the primary if it is connected and has capacity. If no
`progress` arrives within the handoff window, the relay sends
`utterance.cancel` to that device and offers the utterance to the next one.
A slow primary that already started may still play it; that is a duplicate,
which the rule prefers to a loss, and the event log records it.

Devices de-duplicate by id across reconnects. On `hello` a device reports its
last acknowledged id and the ids it still holds; the relay reconciles and
resends only what is missing.

### 4.4 The scheduler

One background task. Every tick it claims due rows under a lease
(`lease_until = now + window`, in one `BEGIN IMMEDIATE` transaction), turns
each into an utterance through admission, and deletes the schedule row in the
same transaction that inserts the outbox row. A crash between claim and
insert lets the lease expire and the row is claimed again: redelivery, never
loss. The schedule cap refuses new rows at the cap; it never evicts the
soonest. Pausing reminders, if ever needed, is a wearer preference the
scheduler reads, not a control plane.

### 4.5 The composer

An interface with one method, `compose(intent, budget) -> words`, and three
implementations: `Echo` (the intent itself, normalised), `Fake` (tests), and
the model provider. The relay converts digits to words before and after the
call, measures the result with the same budget function admission uses, asks
once more with the stated defect if it does not fit, and otherwise fails
loudly. Every attempt is recorded content-free. The source label on the
utterance says which path produced the words (`live`, `echo`), so the wire
never implies a model ran when it did not. A bring-your-own-key compose is
the same call with a caller-supplied credential used once and never stored.

### 4.6 Adapters

- **Store:** SQLite, WAL mode, one file, versioned migrations. Every core
  transition is applied in one transaction by a repository that loads the
  slice, calls the core, writes the result and emits the effects.
- **Device transport:** WebSocket over TLS. Authentication is the first frame
  (`hello` with the device key), never a query string, so no credential
  reaches an access log.
- **Sender API:** HTTP, bodies validated by generated models, bearer tokens
  scoped per sender.
- **Clock:** injected; tests drive it.
- **Assembly:** `create_app(settings)` wires the above. No module-level state
  anywhere; a test builds its own app in milliseconds.

---

## 5. Devices

### 5.1 The renderer contract

A renderer holds a small bounded queue of utterances, plays exactly one at a
time, and speaks the protocol in section 6. For each utterance it:

1. plays the arrival cue as soon as it can do so between cells, even while
   another utterance is playing (plan §4 invariant 4: announce, then wait);
2. when its turn comes, plays the prefix if present, then the words with the
   spec's cell and word gaps at the wearer's pace, then the close;
3. if `body_pending`, repeats the working pattern on its own clock until the
   body arrives or the timeout passes, then plays the body or the error
   pattern;
4. reports `progress` at the cue, at each word, and at the close; sends
   `played` when the close has finished on the actuator; sends `nack` with a
   reason when it cannot play (hidden, muted, spec mismatch, timeout).

Wearer controls are renderer operations: stop, replay the last word, replay
the utterance, skip a word, change pace, and advance to the next utterance.
Whether the next utterance starts by itself after a close or waits for the
wearer is a preference (`advance: auto | tap`). That is where "the wearer,
not the sender, releases the queue" lives.

Pace is a runtime variable on the device, synchronised as a wearer preference
through the relay in both directions.

### 5.2 Renderer profiles

A device declares its profile at enrollment. The profile decides how a cell
is encoded, and the reference renderer knows every profile.

- **`six_actuator`** (the band): a cell is the raised dots driven together
  for the cell's duration. Word gaps and the close come from the spec.
- **`single_actuator`** (a phone): a cell is six time slots in column order
  (dots 1, 2, 3, then 4, 5, 6); a raised dot is a pulse in its slot. This
  carries letters, not dot counts, at roughly twice the cell length. The
  exact slot timing is spec work, validated on the feel-tool first, and the
  time budget already accounts for the slower profile.

### 5.3 The band

The existing pull-model sequencer stays the heart of it. Around it: an
utterance decoder, the bounded queue with acknowledgement, a transport client
with reconnect, backoff and resume by id, chord input producing `input.text`
frames, and a runtime pace variable. The six DRV2605L drivers sit behind the
mux; the bus writes a bitmask to select a channel. The firmware emits the HAP
timeline log it emits today; that log is the conformance evidence.

### 5.4 The phone

The phone renderer is a **native Android app**, not a web page. Browsers do
not vibrate a hidden page, and a message channel that works only while the
screen is on and the app is in front is not a channel. The native app runs a
foreground service, plays amplitude-capable waveforms, keeps its queue across
process restarts, and implements the same contract as the band with the
`single_actuator` profile. Until it exists, a web client may serve as a
foreground demo and operator view, labelled as exactly that.

The phone app keeps no plaintext message history by default. If the wearer
turns history on, it is stored encrypted with the platform keystore and
bounded.

---

## 6. Wire protocol

JSON frames over WebSocket, each with a `v` and a `type`. The schema is
generated from the relay's models and published with the repo, so the band,
the phone and the console build against one definition.

| Direction | Frame | Carries |
|---|---|---|
| device → relay | `hello` | device key, renderer profile, spec version, pace, last acknowledged id, held ids |
| relay → device | `hello.ack` | wearer id, prefs, utterances to resend |
| relay → device | `utterance.open` | the utterance (section 2), possibly `body_pending` |
| relay → device | `utterance.body` | id, words, or an error |
| relay → device | `utterance.cancel` | id, reason |
| relay → device | `pref.set` | pace, advance mode |
| device → relay | `progress` | id, phase (`cue`, `working`, `word n`, `close`) |
| device → relay | `played` | id, device monotonic timestamps of start and close |
| device → relay | `nack` | id, reason |
| device → relay | `input.text` | words typed on the chord keys, in reply to an id or unaddressed |
| device → relay | `control` | stop, replay, skip, advance |
| device → relay | `pref.changed` | pace, advance mode |
| both | `ping` / `pong` | liveness only, never state |

Senders use HTTP: `POST /utterances`, `GET /utterances/{id}`,
`GET /utterances?state=`, `DELETE /utterances/{id}` (cancel),
`POST /schedule`, `GET /schedule`, `DELETE /schedule/{id}`, `GET /prefs`,
`PUT /prefs`, `GET /devices`, `POST /devices/enroll`, `GET /health`.
Health carries counts, caps, versions and the last compose outcome, never
text. Everything except health and the enrollment handshake is
authenticated.

---

## 7. Storage

One SQLite database per relay.

| Table | Holds | Notes |
|---|---|---|
| `wearers` | id, display name, created | one row in the wearer-hosted shape; many when hosted |
| `devices` | id, wearer, profile, key hash, primary flag, order, last seen | keys hashed at rest |
| `senders` | id, wearer, label, token hash, scopes, rate limit | the agent is a row |
| `utterances` | the outbox: everything in section 2 plus state, device, timestamps, source label | indexed by wearer + state |
| `schedule` | id, wearer, fire_at, intent or words, kind, lease_until | refused at cap |
| `prefs` | wearer, pace, advance mode, history, late policy | validated on write |
| `replies` | wearer, in reply to, words, created, delivered to sender | the chord-input path |
| `events` | append-only log: time, wearer, kind, reason, counts | content-free, bounded retention, the source of health and metrics |

Rules: every transition is one transaction; `BEGIN IMMEDIATE` around claims;
`PRAGMA journal_mode=WAL` and `synchronous=FULL`; migrations are numbered and
applied at start; an integrity check at start reports into `events` rather
than crashing or silently discarding. Retention is a policy per table with a
counter, applied by the scheduler's tick.

---

## 8. The console

The console is the surface for senders, caregivers and the wearer: send a
message, see its state, manage contacts and devices, set the schedule, set
pace and advance mode, read health. It is a small typed web application with
a real build, generated API types, and a content-hashed asset manifest. It is
built for a screen reader and a refreshable braille display: semantic
structure, every control reachable and labelled, state changes announced
through live regions, and nothing that depends on reading a transient. The
console never plays haptics; it is not a renderer.

---

## 9. Security and privacy

- TLS everywhere off loopback. Plain HTTP only with an explicit flag intended
  for a LAN bench.
- Devices authenticate with per-device keys presented in the first WebSocket
  frame; senders with scoped bearer tokens; the console with the wearer's
  admin token. Comparisons are constant-time. Keys are hashed at rest.
- Request bodies have hard size limits; senders have rate limits; every
  refusal names its reason.
- No message text in logs, health or metrics. The `events` table is
  content-free by construction.
- Played utterances are retained only as long as the wearer's policy says;
  the default is short.
- A bring-your-own-key credential is used for one call, scrubbed from any
  provider text, and never written anywhere.
- Enrollment of a new device is a short-lived code shown in the console,
  exchanged once for a device key.

---

## 10. Timing spec and conformance

The spec stays exactly what it is: one JSON file, a generator, and generated
tables for every consumer, with a drift guard in the hook, the suite and CI.
Two things are added to it: a renderer profile section with the
single-actuator slot encoding, and a word gap.

The **reference renderer** is a pure Python function:
`timeline(utterance, profile, pace) -> [(t_ms, dot_mask, buzz_ms)]`. It is
the definition of correct playback. From it come:

- the time budget admission uses;
- golden timelines for a checked-in set of utterances;
- the oracle for conformance: the C sequencer on a virtual clock and the
  phone renderer under fake timers each emit their timeline for the same
  utterances, and a differ compares them with the tolerance the spec allows.

The test pyramid, bottom up:

1. **Core:** property-based tests on the outbox and admission. No loss, no
   duplication, bounded, every refusal visible, every transition legal.
   Milliseconds.
2. **Conformance:** reference versus C versus phone timelines over the golden
   set. Seconds.
3. **Integration:** the app factory with a temp database, the fake composer
   and the fake clock, driving HTTP and WebSocket end to end. Seconds.
4. **Device:** the band under QEMU against a fake relay; the phone app with
   an instrumented actuator. Minutes, on demand and in a nightly job.

Nothing in the suite sleeps for real time. Counts in documentation are
produced by the suite, not typed.

---

## 11. Deployment and operations

The wearer-hosted shape is one process and one database file: a `ziv-relay`
entry point, a systemd unit, TLS from a reverse proxy or built-in ACME, and a
backup that is a checkpointed copy of the file. Configuration is one settings
object read from environment or a file, with a single default for every
provider URL. The same binary serves many wearers when hosted. Health is a
public counts-only endpoint; the `events` table is the operator's view, with
a small CLI to query it.

---

## 12. Non-goals for this revision

Audio input is a separate sender service that produces utterances; the relay
core never learns what audio is. Spoken replies, per-contact marks, Grade-2
contractions, fine-tuned models and multi-relay federation are out of scope
until the channel itself is validated with braille readers.

---

## 13. Path from the current tree

What exists today maps onto the target like this.

| Today | Becomes |
|---|---|
| `MessageGate` queue, `MessageInbox`, the turn lock, `DeviceHub`, sessions keyed by browser tab | the per-wearer outbox and the device registry |
| server-side cell pacing in `_dwell` | device-side rendering; the relay never sleeps through playback |
| `FAKE_MODEL_SECONDS` and the processing loop in the turn pump | `body_pending` headers; the device ticks while the real compose runs |
| letter cap by slicing, `ui.spell_max_letters` as the product limit | time budget at admission, 413 beyond it, words with gaps |
| JSON files rewritten whole | one SQLite database, one transaction per transition, leases for firing |
| `/api/ziv/control/*`, `/api/ziv/ready`, `/inject/audio` simulate path | removed; a wearer preference where a behaviour is still wanted |
| the PWA as both band and console, inline script | a native phone renderer and a separate accessible console |
| service worker and cache-bump guard | a built console with content-hashed assets; no hand-bumped cache name |
| `TurnTimeline` ordering and the gate's invariants | kept as the device renderer's state machine and the core's admission rules |
| `haptic_out` sequencer, bench, HAP log, QEMU ladder | kept; gain a decoder, a queue, transport and a pace variable |
| `tools/haptic_timing.py` and the drift guard | kept; gain the profile section and the reference renderer |

Order of work, each step leaving the suite green:

1. Package the relay, add the app factory and the injected clock, remove
   module state. Mechanical.
2. Add the schema and generated models for frames and bodies; validate at the
   edge with size limits.
3. Introduce the utterance and the reference renderer; switch admission to
   the time budget.
4. Move to SQLite with the outbox state machine and leased firing.
5. Device-side rendering with acknowledgement on the web client, behind a
   flag, then make it the only path and delete server pacing.
6. Composer interface; `body_pending` for the agent path.
7. Device identity, enrollment, sender tokens, first-frame auth.
8. The band's transport and decoder; conformance across all renderers.
9. The native phone renderer and the separate console.
