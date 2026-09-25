# Judge Repro Guide — Ziv

Every claim in the DEVPOST posts maps to proof in this repo. Two ways in:
the **60-second test run** (no phone, no key, fully hermetic) and the
**two-minute live run-through** (real server, real restart, real HTTP).
Nothing here needs `NEBIUS_API_KEY`; the Omni path is proven at the wire
contract level with a mocked provider.

Quick index — claim → where it's proven:

| Claim | Proof |
|---|---|
| Turn journey order on the wire | `tests/test_ziv_server.py::test_turn_journey_reaches_the_wire_in_order` |
| Queue-don't-interrupt + 429 | `test_message_is_rejected_429_when_replay_queue_is_full` |
| Error long-buzz on provider failure | `test_omni_provider_failure_feels_the_error_long_buzz` |
| Z-I-V name mark + triple-pulse tail | `test_prefix_mark_order_is_mark_tail_then_turn` |
| Live fire loop fires reminders | `test_scheduled_reminder_fires_with_name_mark_over_the_wire` |
| Schedule survives restarts (durable) | `tests/test_ziv_store.py::test_schedule_roundtrip_across_instances` |
| Schedule: claim-before-play, one clock, corrupt recovery | `test_schedule_take_due_claims_then_releases`, `test_schedule_take_due_uses_one_now`, `test_schedule_clear_and_corrupt_recovery` |
| Concurrent arrivals: no loss, no dup, loud refusals | `tests/test_gate_concurrency.py` (3 tests) |
| Inbox replay is a self-naming turn | `test_reminder_stored_offline_replays_with_name_mark` |
| PWA badge contract (both sides pinned) | `tests/test_client_badge_contract.py` + `test_health_payload_serves_the_pwa_badge_contract` |
| Health surfaces the schedule (depth/cap/corrupt) | `test_health_payload_surfaces_the_schedule` |
| Redial give-up is a loud dead end | `tests/test_client_redial_contract.py` (+ browser proof in `test_redial_giveup_e2e.py`, marked `e2e`) |
| Timing spec: one source, drift-guarded | `tests/test_haptic_timing.py`, `test_rename_check.py` |
| Honesty audit trail | `HONESTY_CHANGELOG.md` |

---

## Step 0 — the 60-second test run

```bash
cd agent
python -m pytest -m "not e2e"
```

**Expect: `126 passed, 2 skipped`** (the 2 skips are the Playwright browser
tests; they skip cleanly when Playwright isn't installed). ~2 minutes on a
laptop. This one command proves every row of the table above — each named
test is in the output.

Just the honesty-critical ones (~30 s total — the four fast contract files
run whole, the big server file is filtered to the felt-pattern tests):

```bash
python -m pytest -q tests/test_gate_concurrency.py tests/test_ziv_store.py \
  tests/test_client_badge_contract.py tests/test_client_redial_contract.py
python -m pytest -q tests/test_ziv_server.py -k "omni_provider_failure_feels \
  or prefix_mark_order or scheduled_reminder_fires or reminder_stored_offline \
  or health_payload"
```

---

## Step 1 — the two-minute live run-through

From the repo root (PowerShell or bash; adjust `ZIV_PORT` if 8791 is taken).
Every output below was captured live on this repo.

```bash
cd agent
ZIV_PORT=8791 python ziv_server.py        # terminal 1
```

**1. Schedule a reminder (10 s out) — beat 1, "acts while you're away":**

```bash
NOW=$(date +%s)
curl -X POST http://127.0.0.1:8791/api/ziv/schedule \
  -H 'Content-Type: application/json' \
  -d "{\"fire_at\": $((NOW+10)), \"text\": \"pills\"}"
# → {"scheduled":true,"id":1,...,"text":"pills","source":"scheduled",...}
```

**2. Watch it fire unprompted, name-mark first** — open the dev band in a
browser: `http://127.0.0.1:8791/ziv_client/index.html`, tap **Unlock
vibration**, then feel/read the wire log: `reminder: pills` → Z-I-V cells →
`triple-pulse` → breath → kind cue → cells → close. (No phone? The wire log
on the page shows the same journey; `reminder: pills` arrives on its own.)

**3. The durability beat — kill the relay, restart, the reminder survives:**

```bash
# Ctrl-C the server, then:
ZIV_PORT=8791 python ziv_server.py        # same terminal
curl http://127.0.0.1:8791/api/ziv/schedule
# → the SAME reminder comes back: same id, same fire_at, same text
```

Live-captured on this repo: `{"reminders":[{"id":1,...,"text":"judge repro
beat","source":"scheduled","fired":false}]}` — after a real kill.

**4. Fire-while-away (store, don't drop):**

```bash
# with NO band attached (close the browser tab first):
curl -X POST http://127.0.0.1:8791/inject/audio \
  -H 'Content-Type: application/json' -d '{"simulate": "who is calling"}'
# → {"event":"inbox:stored","stored":true,...}
curl -X POST http://127.0.0.1:8791/api/ziv/message \
  -H 'Content-Type: application/json' -d '{"text": "stored while away"}'
# → {"event":"inbox:stored",...}  (same no-band contract for typed input)
```

Reattach the band: hello reports the pending count, and each replay arrives
as a **self-naming turn** — mark first, content after (inbox replay claim).

**5. Health — the operator's view (badge numbers, telemetry):**

```bash
curl http://127.0.0.1:8791/api/ziv/health
```

Look for: `gate_queue`/`gate_queue_cap` (what the PWA badge renders),
`queue_rejections.per_minute`, `schedule_pending`/`schedule_cap`/
`schedule_corrupt`, `inbox_pending`, `store_problems`. The badge on the
dev-band page shows the same numbers live, polled every 2 s.

**Cleanup:** `curl -X DELETE http://127.0.0.1:8791/api/ziv/schedule`, then
Ctrl-C. Wearer state lives in `agent/ziv_data/` (gitignored); DELETE clears
your own test schedule.

---

## Step 2 — optional, 5 minutes: the full turn journey with your eyes

With the server running, open `http://127.0.0.1:8791/ziv_client/index.html`
on Android Chrome (or desktop Chrome — vibration needs Android, but the
wire log, cells box, badge, and redial note all render anywhere):

1. Send a message → read the wire log top-down: arrival cue → `processing`
   ticks → cue-as-content → one `cell` frame per letter → `end-of-message`
   close. On a phone, every frame vibrates with the exact pattern the
   firmware would play (both derive from `docs/haptic-timing.json`).
2. While it plays, send another → the second gets its cue only, queues, and
   replays after the close (`free: true` rides the LAST close — the redial
   trigger).
3. Keep sending until the badge shows `refusing` → the sender gets HTTP 429
   and the page shows the busy note; the refused typed message **redials
   itself** when the freeing close lands — and if three closes pass without
   luck, the red **dead-end note stays on screen** until you act.

The full browser-level redial/durability scenarios are scripted:
`python -m pytest -m e2e` (needs `pip install playwright && playwright
install chromium`).

---

## What each artifact is

| File | Role |
|---|---|
| `agent/ziv_server.py` | the relay: WS pump, schedule fire loop, health, Omni seam |
| `agent/ziv_relay.py` | the seam: `MessageGate` + `TurnTimeline` (the invariants) |
| `agent/ziv_store.py` | durable state: inbox, memory, **schedule** (atomic JSON, capped, corrupt-tolerant) |
| `agent/ziv_client/index.html` | the PWA dev band: timing bootstrap, badge, redial |
| `tools/haptic_timing_gen.py` | generates all 7 consumers from `docs/haptic-timing.json` |
| `HONESTY_CHANGELOG.md` | every corrected claim, test-caught bug, and soft spot |
