# Pre-Submission Honesty Changelog — Ziv

> Every claim in this submission has been checked against the code, and every
> deferral is named as deferred in the same sentence that claims what is built.
> This changelog is the audit trail: what was corrected, which bugs the test
> suite itself caught (two of them silent-data-loss bugs the demo would never
> have shown), and where the proof lives. Evidence references are real test
> names — run `cd agent && python -m pytest -m "not e2e"` to see all of them
> pass. `python tools/prove.py` runs every suite and prints the counts in one
> block — those numbers are generated, never hand-typed.

---

## 0. The re-scoping decision (the biggest change in this submission)

**The rule we settled on: the submission body claims only what the demo can
prove. Anything not provable on camera is held as asset and named once, at the
end, or not at all.** This is not modesty for its own sake — it is a
credibility rule. Naming something built but unprovable invites a
"can you show me that?" with no clean answer, and one unanswered question
costs more than the claim was ever worth.

### 0.1 The audio seam came out of the body
The submission originally led with a hearing layer: push-to-talk mic → an
Omni model transcribing → vibro-braille. Two facts, verified against the live
account rather than the model card, made that impossible to claim:

- `GET /v1/models` on this account lists **four Nemotron models and no
  `-Omni` variant at all**. The model id the relay was defaulting to
  (`nvidia/Nemotron-3-Nano-Omni`) returns **404 — it does not exist here**.
- Nebius's own cookbook page for Nemotron-3-Nano-Omni describes it as
  *"supporting vision, video, and text understanding"* — no audio modality.

So the hearing layer is now the **asset column**: the seam is still wired
(`POST /inject/audio`), still refuses loudly rather than guessing at a model id
(503 with no key *and* with no audio-capable endpoint configured), and its
request contract is still pinned by a mocked-provider test. It is just not
claimed. `ZIV_OMNI_MODEL` is now empty by default instead of naming a model
this account cannot serve.

### 0.2 The model claim moved to something that is provable
The relay's only `chat/completions` call had been the audio one, which meant
100% of the "we use an NVIDIA open model on Nebius" claim rested on the one
call that could not succeed. So the model claim moved to the **agent path**:
`POST /api/ziv/schedule` with an `intent` ("meds at nine"), and when it fires
the relay calls Nemotron and plays the line the model wrote
(`source: text_live` on the wire).

This is better in every direction, not just recoverable:
- The claim is now *demonstrable* rather than *disclaimed*.
- "Latency may be slow, never silent" is now illustrated by a real round-trip
  instead of `ZIV_FAKE_MODEL_SECONDS`, which is demoted to the offline
  fallback it always should have been.
- The questionnaire's required Nemotron answers became answerable from evidence.
- Without a key the promise still fires, verbatim, labelled `text_echo` — so
  the log can never claim a model ran when none did.

### 0.3 A payload bug the honesty work caught
While re-scoping we found the audio payload had been changed to
`"data": f"data:audio/{mime};base64,{audio_b64}"`. A `data:` URL is Gemini's
`inlineData` convention, not OpenAI's `input_audio` — whose `data` field is raw
base64 with the container named separately in `format`. Worse, the contract
test that used to pin the payload exactly had been **loosened** to
`assert ...["data"].endswith(_B64_PNG)`, which passes for the data-URL prefix.
Both are reverted: raw base64, and equality asserted on purpose. A drift guard
that loosens its own assertion is worse than no guard, because it looks green.

### 0.4 Numbers are generated now
`python tools/prove.py` runs the hermetic suite, the 274-check firmware bench,
the 49-check host suite and the timing drift guard, and prints one block. The
counts were previously hand-typed into six files and had already disagreed
(126/2, 127/3, 133 all present at once). `tools/haptic_timing.py --verify` also
now accepts the flag its own generated docs tell readers to run — it used to
exit 2 on a command printed in our own documentation.

### 0.5 What is deliberately still not claimed
The wrist hardware, braille-chord input, the hardware-gated mic, a
wearer-hosted relay, spoken replies, and the naming session. Named once in the
"held as asset" table, asked about on request, never in the body.

---

## 1. Bugs the honesty work itself caught

These were found *by building the proof*, not by a user — which is the point:
the live-loop test written to prove the fire loop honest instead caught the
fire loop lying.

### 1.1 The maxlen-0 deque that silently ate reminders
- **Symptom:** a scheduled reminder was accepted, then never fired, never
  listed, never reported. Silent data loss — the exact failure mode the whole
  project exists to prevent ("redelivery, never loss").
- **Root cause:** `fire_due()` rebuilt its queue with
  `deque(remaining, maxlen=len(remaining))`. When nothing remained after a
  drain, that is a **maxlen-0 deque**, and a maxlen-0 deque discards every
  future `append`. Since the fire loop polls every second, any long-running
  relay poisoned its own schedule the first time the queue emptied.
- **How it was found:** the live-loop test passed in isolation but failed
  after a prior test — because the prior test's lifespan loop drained the
  queue and left the zero-cap deque behind. A standalone diagnostic script
  showed the loop polling, the queue consuming the reminder, and zero frames.
- **Proof now:** the durable rewrite (below) removes the deque entirely —
  every mutation rewrites the store from a plain list. Regression:
  `test_schedule_accepts_reminders_after_a_drain` (drain → add → survives),
  plus `test_schedule_roundtrip_across_instances` proving a fresh instance —
  a restart — still sees the reminder.

### 1.2 The `LOGGER` that didn't exist
- **Symptom:** the fire loop's misfire path called `LOGGER.warning(...)`, but
  `LOGGER` was never defined. Any misfire would raise `NameError` — silently
  swallowed by the loop's blanket `except`. The implicit claim "misfires are
  operator-visible" was false.
- **How it was found:** while stripping the ad-hoc `schedule_debug.log`
  debug-file logging, a grep for the logger's definition came back empty.
- **Proof now:** `LOGGER = logging.getLogger("ziv.relay")` is defined; the
  misfire warning path is real. (Ad-hoc debug writes to a hardcoded temp-file
  path — including the codemod that injected them — were removed; telemetry
  and health are the operator surface.)

### 1.3 Two defects caught in review before they shipped
- **Double clock-read in `take_due`:** the first draft read `time.time()`
  twice; a reminder whose `fire_at` passed between the two reads could be
  both fired *and* kept. Fixed to a single `now`;
  `test_schedule_take_due_uses_one_now` pins the contract.
- **Ids that could repeat:** the id high-water mark was read once at
  construction; a hand-edited file (or interleaved instance) could mint a
  duplicate id. The mark now rides every load;
  `test_schedule_malformed_rows_are_dropped_not_crashing` forced the fix by
  asserting id continuation past rows the file had never seen.

### 1.4 The stuck-gate wedge — a bug the seam tests could not see (fixed)
The third silent-data-loss bug, found by probing the seam rather than
reading it, and the one the existing suite was *structurally* unable to
catch.

**What happened.** `turn.begin_playback()` sets the gate's `playing` flag;
only `turn.finish_playback()` clears it. A turn that raised *between* the
two — the real case being a band that vanishes mid-content, where the next
`_push` raises `_NoDevices` — never reached the close, so `playing` stayed
`True` for the life of the process. Measured on the unfixed code: after one
abandoned turn, `gate.playing` stayed `True`; the next 12 arrivals gave
**7 queued, 5 refused, 0 played**, and the relay refused everything else
until restart. The in-flight text was in neither the queue (the gate had
taken it) nor the inbox — simply gone, contradicting the "never a silent
drop" claim the README leads with.

**Why the suite missed it.** `test_gate_concurrency.py` is thorough about
the gate *in isolation* (12 threads × 25 admits, no loss, no duplication,
loud bounded refusal) — and every one of those tests drives a gate the
driver has already put into `playing`. The wedge needs the *server's* call
order (`admit` → lock → `begin_playback` → … → `finish_playback`), which no
test exercised. The unit was correct; the composition was not.

**The fix, in two parts.**
- `MessageGate.abort()` — the interrupted counterpart to `close_event()`:
  releases the channel (so the next arrival plays instead of queueing) and
  hands back the still-queued texts so the caller can re-offer them. An
  abort drains nothing silently.
- `run_message_turn` now tracks every text it still owes the wearer and, on
  *any* failure, stores the remainder in the inbox before re-raising.
  Redelivery, never loss — the same rule the store already follows.
- `fire_due`'s no-band branch no longer offers the reminder a second time
  (the turn already stored it), which would have double-stored one promise
  into two inbox entries.

**Evidence.** `test_band_vanishing_mid_turn_releases_the_gate`,
`test_band_vanishing_mid_turn_stores_the_in_flight_text`,
`test_band_vanishing_mid_turn_strands_queued_messages_not_drops_them`, plus
three `MessageGate.abort` contract tests in `test_gate_concurrency.py`. All
three server-level tests **fail on the pre-fix code and pass after** —
verified by reverting the fix and re-running, not by inspection.

**Superseded in part by §1.5.** The `abort()` pairing here was the right
symptom-level fix, but it left `admit()` *suggesting* a play rather than
reserving the channel — which is why the three bugs in §1.5 were reachable
in the first place. `abort()` stays; its motive is now the reservation.

---

### 1.5 The channel was described twice, and the two descriptions disagreed

Three more bugs, one cause. This is the deepest thing found in the whole
review, and it is a design fault rather than a coding slip.

**The fault.** The haptic channel had two owners-on-paper. `MessageGate`
tracked `_playing`, which read as "content is on the motors", and set it only
at `turn.begin_playback()`. `asyncio._turn_lock` tracked "a task is driving
the wrist right now". Those are not the same window: a turn spends most of
its life *not* vibrating. Between `admit()` and the first cell it waits for
the model — `ZIV_FAKE_MODEL_SECONDS` in the fake path, the 30 s provider
timeout in production — and in that whole stretch the gate said "idle".

**What that cost, measured on the unfixed code.**
- *The bound was decorative.* 20 simultaneous `run_message_turn` calls
  against an idle gate: **20 played, 0 queued, 0 refused.** Every one of
  them was answered `message:play`, so every one of them blocked on the
  turn lock and then played in turn. `MessageGate.MAX_QUEUED` (8) could not
  engage in exactly the situation it exists for — a burst.
- *A barging turn.* A message arriving during another turn's model wait was
  answered `message:play` and simply waited behind the turn lock: it jumped
  to the *front* of a queue it should have joined at the back.
- *Inbox delivery bypassed the gate entirely.* `deliver_inbox_one` drove the
  wrist without reserving anything, so a stored backlog could interleave
  into a live turn — and, symmetrically, a message that cued during a
  backlog drain sat in the gate until the *next* inbound message arrived to
  drain it. That is a "something arrived" cue with no content behind it:
  the loud-not-silent rule, broken quietly.

**The fix: the decision is the reservation.** `admit()` answering
`message:play` now holds the channel, inside the same lock that chose it.
The channel is therefore held for the turn's *entire* lifetime, and
`close_event()` / `abort()` are the only two ways to give it back — one
pairing, two releases, no second source of truth. Two smaller consequences
fell out of the same change:

- `MessageGate.reserve()` — the queue-less claim, for a caller whose
  content is already durable (an inbox entry must not wait behind a *turn*
  queue, nor interleave into a turn). It returns `False` rather than
  blocking, so a declined delivery leaves its entry pending and loses
  nothing.
- Inbox delivery now *drains*: whatever queued behind a stored backlog has
  already cued on the wrist, and the delivery is the owner that owes it
  content. If the band dies mid-drain, the stranded texts go to the inbox —
  the gate is a minutes-long buffer, and nobody is left who will ever play
  what it holds.

**Why the suite missed all three.** Every concurrency test in
`test_gate_concurrency.py` and `test_ziv_server_seam.py` drives a gate the
driver has *already* put into `playing` (`gate.begin_playback()` first), so
the idle→busy transition — the entire bug — is outside their frame. And the
new burst test, as first written, measured nothing: with instant dwells the
first turn ran to completion before `asyncio.gather` ever scheduled the
second, so 20 turns played serially and the test happily reported "no
bug". The test now *yields* the event loop at each dwell, which is what
makes the arrivals genuinely simultaneous; that detail is the reason the
bug survived a suite that looked thorough.

**Evidence.** `test_burst_of_arrivals_plays_one_and_bounds_the_rest` and
`test_arrival_during_the_model_wait_queues_instead_of_barging` **fail on the
pre-fix code and pass after** — verified by removing the reservation and
re-running (20 played before, 1 played / 8 queued / 11 × 429 after).
Gate-level: `test_a_stampede_on_an_idle_gate_produces_exactly_one_winner`,
`test_reserve_races_admit_without_a_double_owner`,
`test_seam_is_proven_a_play_decision_reserves_the_channel`,
`test_seam_is_proven_reserve_claims_the_idle_channel_or_declines`.
Inbox: `test_inbox_delivery_drains_what_arrived_behind_it`,
`test_inbox_delivery_strands_what_it_could_not_play`,
`test_inbox_delivery_declines_while_a_turn_holds_the_channel`.

#### 1.5.1 The reservation, and the abort that reached past it

The reservation had a bug of its own, found by adversarial review of the
change above rather than by any test — every test in the section passed
while it was live.

`abort()` releases the channel unconditionally. But a turn releases the
channel at its *close* (`finish_playback` → `close_event`) and then keeps
playing drained replays for seconds afterwards. In that window the next
arrival legitimately finds the channel idle, reserves it, and waits on the
turn lock. If the dying turn's failure path then called `abort()`, it
released a channel it did not own and pulled that arrival's queue into its
own inbox.

Measured on the code as written, with a band that vanished at the first
replay frame:

```
B admitted: message:play | gate held: True | queue: 1
>>> after the abort path:
    gate.playing = False      <- B owns it, so this must be True
    gate queue   = 0          <- B's queue was drained away
    inbox        = ['queued one', 'queued behind B']
```

Nothing was lost — both texts are durable in the inbox — but B now believes
it owns a channel the gate says is idle, so a third arrival would be
admitted as a second owner, and B's queued text sat waiting for a phone
attach instead of playing after B's close. The cue had already fired.

**The fix.** A turn tracks whether the channel is still *its* (`released`,
set at the release, with no await in between so the two are simultaneous
as far as the event loop is concerned) and aborts only while it is. This is
the residue of having two release paths: a state change needs an owner, and
`released` is the only record of who that is.

**Evidence.** `test_an_aborting_turn_does_not_release_the_next_arrival_s_channel`,
which **fails when the guard is removed and passes with it** — verified by
editing the guard out and re-running.

#### 1.5.2 What the reservation still does not fix

- **An inbox drain declines rather than waits.** `reserve()` returns `False`
  rather than blocking, so if an arrival takes the channel in the gap
  between one delivery's drain and the next, the attach loop stops early.
  The entries stay pending and are delivered on the next attach: no loss, a
  real delay. This is a deliberate trade (a blocking wait would need the
  gate — a thread-safe, lock-based object — to grow an asyncio-facing wait,
  and `MessageGate` is deliberately independent of any event loop).
- **The channel is released before the replays play**, because that is the
  seam's documented order (`close_event` releases and drains). A message
  arriving during the replay therefore reserves the channel rather than
  queueing, and is serialised behind the replays by the turn lock. Correct,
  but the policy is "one turn at a time", not strictly "one message at a
  time" during a drain.

### 1.6 The auth gap: the senders were gated, the readers were not

Found by reading the routes against each other, not by testing them. With
`ZIV_RELAY_TOKEN` set, `/api/ziv/message` and `/inject/audio` required
`Authorization: Bearer`. Nothing else did. So an unauthenticated caller on
the LAN could:

- read a private reminder's text out of `GET /api/ziv/schedule`,
- read the wearer's entire message inbox out of `GET /api/ziv/inbox`,
- clear either one (`DELETE /api/ziv/schedule`, `DELETE /api/ziv/inbox`),
- read and rewrite the wearer's preferences.

**The fix.** One `require_auth` dependency, declared once and attached to
every route that can carry or reveal content: `/api/ziv/message`,
`/inject/audio`, `/api/ziv/schedule` (GET/POST/DELETE), `/api/ziv/ready`,
`/api/ziv/inbox` (GET/DELETE), `/api/ziv/prefs` (GET/POST). Declared as a
dependency rather than an in-body call so the next endpoint added inherits
the rule instead of forgetting it.

**What deliberately stays open**, and why: `/ws` (a WebSocket handshake
cannot carry an `Authorization` header — it keeps its own `?token=`),
`/api/ziv/timing` (the generated spec; the PWA bootstraps from it before it
can hold a credential), `/api/ziv/health` (the operator view the queue
badge polls — counts, caps, model wiring, turn telemetry, no message text),
and the client page. `test_auth_leaves_the_bootstrap_routes_open` pins that
`health` stays content-free by storing a private message and a private
reminder and asserting neither appears in the payload, so widening it stays
a deliberate act.

**Not fixed, stated plainly.** The PWA itself sends no token: it opens `/ws`
without `?token=` and posts without an `Authorization` header. So with a
token set, the dev band client cannot connect or send at all. That is
pre-existing and unchanged — the relay is a LAN dev band and the token is
unset by default — but it means "auth on" and "the demo works" are
mutually exclusive today. Making the client token-aware is a feature, not
part of this fix.

---

## 2. Claims corrected

| Claim | Was | Now | Evidence |
|---|---|---|---|
| Error long-buzz | "defined in the spec; server wiring the next step" | wired into the Omni transcription-failure path: provider 502 → wrist feels `long-buzz` + `error:` text, sender still gets the 502 | `test_omni_provider_failure_feels_the_error_long_buzz` |
| Name mark (Z-I-V) | "rendering it as the prefix of unsolicited messages is the next wiring step" | live: every scheduled reminder opens with mark cells → triple-pulse tail → breath, inside the turn lock | `test_prefix_mark_order_is_mark_tail_then_turn`, `test_scheduled_reminder_fires_with_name_mark_over_the_wire` |
| Inbox replay | "delivered as a full event on the next attach" (plain cue) | self-naming replay: mark first (reminder → triple-pulse, message → double-tap), content after | `test_reminder_stored_offline_replays_with_name_mark`, rewritten `test_inbox_is_delivered_on_next_attach` |
| Reminder schedule | "in-memory in the prototype; persistent schedules are the next step" | durable like the inbox (atomic JSON, corrupt-tolerant, capped, claim-before-play) — a restart keeps pending reminders | `test_schedule_roundtrip_across_instances` + 5 more store tests |
| Auto-redial scope | "the client re-sends its refused message automatically" (all paths) | scoped honestly: typed/stub messages auto-resend; a refused mic clip stays a manual retry (it would need re-transcription) | client source + `test_redial_e2e.py` (e2e) |
| Redial give-up | quiet log line, note vanished (read as "sent") | loud dead-end: red note naming the message and the spent budget stays on screen; cleared only by wearer action | `test_client_redial_contract.py` (4 hermetic) + `test_redial_giveup_e2e.py` (e2e) |
| Demo scene quote | a 19-letter sentence the 12-letter spell cap would truncate mid-read | "taxi is here" (10 letters) — fits what the motors actually play | `SPELL_MAX_LETTERS = 12` in the generated timing module |

The generic-angle DEVPOST also gained a concrete mechanism where it had a
slogan ("one generated timing source" → names `GET /api/ziv/timing`), and its
What's-next list lost the items this work built.

---

## 3. Known soft spots (open, named — not silently patched)

- ~~**Browser-level proof is gated**~~ — closed: Playwright + chromium were
  installed and the e2e suite ran in a real browser — **3 passed** (~50 s).
  First-execution green, with one latent harness bug fixed on the way:
  `e2e_helpers.browser_page()` required a `playwright` argument its only
  call sites never passed (invisible until now because the suite had never
  executed); it is now a self-contained context manager matching its
  callers. Proven live: the give-up dead-end (three refused redials → the
  red note stays, wearer action clears it), exact-one-redial on the raw
  wire (refused once, redialed exactly once, `drained == 8`), and the
  free marker on exactly one close — the last one. Client invariants
  remain pinned hermetically by source-contract tests for machines without
  a browser.
- ~~**DEVPOST_HAPTIC.md demo scene** still quotes a 22-letter utterance~~ —
  closed: the scene now quotes "who is calling?" — twelve letters, exactly
  what the spell cap plays, nothing truncated — and says so in the sentence.
- ~~**"the same turn a typed message takes" repeats ~6×**~~ — closed: the
  prominent spots (and the main file's audio-in bullet) now carry the one
  precise sentence — the transcript enters the relay's single turn
  pipeline, `run_message_turn`, the exact code path, gate, and timing a
  typed message takes; the only added wait is the Token Factory round-trip,
  felt as `processing` ticks — and the remaining spots use short honest
  variants instead of the repeated slogan.
- ~~**"concurrent arrivals never lose or duplicate" slightly overreaches**~~ —
  closed: the claim now has its own teeth. `test_gate_concurrency.py` races
  12 threads × 25 admits against a full gate (and, in one test, against
  begin/close flips mid-race) and proves the three properties the sentence
  promises: every message accounted exactly once (set-exact, buckets
  partition), the drain returns every queued text with no duplication, and
  every refusal beyond the cap is a loud `message:rejected` with reason
  `queue_full` and the cap named. Stable across repeated runs. **Caveats
  added by §1.4 and §1.5:** those tests drive the gate *in isolation*,
  always from an already-`playing` state — which is exactly why they could
  not see the interrupted-turn bug, nor the idle-gate window that made the
  cap unreachable under a burst. The gate is now also pinned through the
  server's real call order (`admit` → lock → … → `finish_playback` /
  `abort`), *and* from the idle side: a stampede on an idle gate must
  produce exactly one winner, so the claim rests on the composition, not
  only the unit.
- ~~**External statistics need source links**~~ — closed: both DEVPOST files
  now carry a "Sources (every external claim, checkable)" block before the
  License: the 2.4M figure (HKNC DeafBlind Awareness Week 2026), the 45–70k
  core (HKNC summaries + ACS 2022 analysis), the $1,500–$12,000 display
  range (Helen Keller Services $1,499–$3,695 anchor + Hackaday/ScienceDirect
  high end), the $239–$349 keyboards (Hable One + NFB), the early-years
  practice (Sense UK-created resource on Insight, Jan 2025), its reach via
  Sense International's Nepal programme, and the protactile name-sign
  grounding (Annual Review of Linguistics). The load-bearing links were
  re-verified live while adding them.
- ~~**The badge contract is one-sided pinned**~~ — closed: the contract is
  now two-sided. `test_client_badge_contract.py` parses the client's badge
  source for the health keys it actually reads (exactly
  `gate_queue`, `gate_queue_cap`, `queue_rejections.per_minute` — a 4th read
  fails the suite) and matches them against the server payload's literals;
  the typeof guards and the polled endpoint are pinned too. Mutation-checked:
  renaming the key on either file, or deleting a guard, fails the suite.

---

## 4. Verification stamp (as of this changelog)

Generated by `python tools/prove.py` — do not hand-edit the numbers:

```
PASS  hermetic relay suite            159 checks
PASS  haptic bench                    274 checks
PASS  QEMU host suite                  49 checks
PASS  drift guard                     7 consumers in sync
```

- **Suite:** `python -m pytest -m "not e2e"` → **159 passed, 3 deselected**
  (deselected = e2e, needs a browser; collection is clean with no ignore
  flags). With a browser installed: `python -m pytest -m e2e` → **3 passed**
  in a real chromium — the full redial + give-up journeys, end to end.
- **Health contracts pinned hermetically, two-sided:** the PWA badge shows
  the queue line (`gate_queue`, `gate_queue_cap`,
  `queue_rejections.per_minute`) and the schedule line
  (`schedule_pending`, `schedule_cap`, `schedule_corrupt`) beside it, with
  a corrupt schedule turning the badge red even at zero depth. The key set
  is pinned from BOTH sides — server payload values AND the client
  source's actual reads, exact-equality both ways — and the corrupt flag
  and `store_problems` are guaranteed to come from one drain. The ordering
  rule that makes it honest (corruption-discovering loads run before the
  drain) is asserted by the corruption-lifecycle test.
- **Claim sweep:** grep for "next wiring step", "wiring is next",
  "schedule is in-memory", "in-memory in the prototype", "schedule in-memory"
  → **zero matches** across `DEVPOST_HAPTIC.md`, `DEVPOST_HAPTIC_GENERIC.md`,
  `README.md`.
- **Client syntax:** the edited inline PWA script passes `node --check`.
- **Debug residue:** no `schedule_debug.log` writes remain; the scratch
  scripts from the debugging episode (8 files, including the codemod that
  injected the trace logging) were deleted after their one useful idea
  (concurrent adds) was folded into a real test:
  `test_schedule_survives_concurrent_adds`.
