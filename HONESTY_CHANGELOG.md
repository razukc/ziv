# Pre-Submission Honesty Changelog — Ziv

> Every claim in this submission has been checked against the code, and every
> deferral is named as deferred in the same sentence that claims what is built.
> This changelog is the audit trail: what was corrected, which bugs the test
> suite itself caught (two of them silent-data-loss bugs the demo would never
> have shown), and where the proof lives. Evidence references are real test
> names — run `cd agent && python -m pytest -m "not e2e"` to see all of them
> pass (126 passed, 2 skipped hermetically; 3 more pass in a real browser
> with `pytest -m e2e` — 129 green total as of this stamp).

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
  `queue_full` and the cap named. Stable across repeated runs.
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

- **Suite:** `python -m pytest -m "not e2e"` → **126 passed, 2 skipped**
  (skips = machines without a browser; collection is clean with no ignore
  flags). With a browser installed: `python -m pytest -m e2e` → **3 passed**
  in a real chromium — the full redial + give-up journeys, end to end.
- **Grand total: 129 passing tests, 0 failures** across hermetic + browser
  suites as of this stamp.
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
