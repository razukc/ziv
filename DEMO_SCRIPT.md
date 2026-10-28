# Single-Take Demo Script — Ziv (≤3:00)

One page. Read top to bottom while recording; every expected line is the
real string (verified against the client and server source). Terminal B
commands run from `agent/`. Browser zoom 125%, desktop width, dev-band page
open at `http://127.0.0.1:8787/ziv_client/index.html`.

**Pre-roll (before REC):**

- [ ] Terminal A: `python -m pytest -m "not e2e"` → `232 passed, 5 deselected` (keep the tail on screen)
- [ ] Terminal B: `ZIV_FAKE_MODEL_SECONDS=8 python ziv_server.py` → `Uvicorn running on http://0.0.0.0:8787` (8 s fake-model = room to work; every turn ~10 s)
- [ ] Browser: open the dev-band page → tap **Open the band** → `connected`, `relay hello — spec v3, … patterns, mark: ziv`
- [ ] Badge reads `queue 0/8 · reminders 0/64`; no microphone prompt appears (this build has no capture path)
- [ ] Compose box cleared; wire log visible; REC ●

---

### 0:00–0:15 — cold open (the no-spoken-reply shot)

Phone face-down on the desk. Terminal B:

```bash
curl -s --max-time 90 -X POST http://127.0.0.1:8787/api/ziv/message -H "Content-Type: application/json" -d "{\"text\": \"taxi is here\"}"
```

*(Without `--max-time`, curl on Windows hangs until the whole turn completes —
always pass it; the POST returns only when the turn is done.)*

**Say (over the buzz):** "This is Ziv. The phone is face down. It buzzes, no
ring and no voice, and the message comes through as braille cells. The screen
shows the same text."
**Expect on page:** `▶ double-tap (kind cue) — 70,160,70,420 ms` →
`working… (working)` → `message: taxi is here` → 10 `cell` frames →
`▶ end-of-message (close) — 200,120,140,120,90,120,50,420 ms`.
Pick the phone up; feel the cells; put it down.

### 0:15–0:40 — the channel, read top-down

Type `call me back` → **Send as message**.

**Expect:** cue → `working…` → `message: call me back` → 10 cells → close.
**Say:** "A typed message enters the relay's turn pipeline: an arrival cue,
working ticks, the cells, then a close. The phone and the bench-tested wrist
firmware share one generated spec, so the pattern cannot drift. The text also
appears on the phone's reply screen and in the relay log."

### 0:40–1:10 — queue, refuse, redial

**0:40 —** set the starter turn going: send `hold that thought` →
**Send as message**. Keep the browser focused.

**0:45 —** the moment its `message: hold that thought` frame appears, paste
this ONE command in terminal B (fills all 8 slots in ~1 s; each curl
returns within 8 s, well after the queue accepted the message):

```bash
for w in alpha bravo charlie delta echo foxtrot golf hotel; do curl -s --max-time 90 -X POST http://127.0.0.1:8787/api/ziv/message -H "Content-Type: application/json" -d "{\"text\": \"$w\"}" -o /dev/null & done; echo "filled"
```

*(Background the curls (`&`, no `wait`): the command returns instantly, the
queue fills within a second, and each POST completes on its own as the
replays drain. Or skip the typing entirely: `python record_beat.py` records
this whole beat — clicks, refusal, redial — to `demo_beat.webm`, which is
the file attached to the `submission-v1` release.)*

**0:47 —** type `nine` in the box → **Send as message** — it's refused:

**Expect:** state `wrist is busy — try after the current message`, log
`✋ refused — the wrist is busy reading. It stays armed: the client redials it when the current message ends.`,
note `↻ redial armed — "nine" sends when the current message ends (3 chances left)`.
When the starter's close lands (~0:55): `↻ redial — resending "nine" (the close just landed)`
→ `POST ok — {…}` → the eight queued messages replay (badge drains to `0/8`).

**Say:** "The hard part isn't the buzz. It's the manners. The channel is serial:
while a message plays, new arrivals queue. When the queue is full, the sender
gets H T T P four twenty-nine — a refusal they can see. The refused message
stays armed and redials itself when the close lands. The badge drains as each
message plays."

### 1:10–1:35 — the model-path beat (live only with a key)

Schedule an *intent* and let the relay write the line — **if a funded
Nebius Token Factory key is set**. Without a key the same beat fires the
promise verbatim, labelled `text_echo`, and the wire log names the path it
took rather than claiming a model ran. This walkthrough defaults to the
no-key path; flip to the live path only if you have a key and want the video
to show a live model call (see the contingency note at the end).

```bash
curl -X POST http://127.0.0.1:8787/api/ziv/schedule \
  -H 'Content-Type: application/json' \
  -d "{\"intent\": \"meds at nine\", \"fire_at\": $((NOW+8))}"
```

When it fires (key present): the relay calls Nemotron-3-Nano-30B-A3B on
Nebius Token Factory → `source: text_live` on the wire → `reminder: <the
model's line>` text frame → the Z-I-V mark cells → `▶ triple-pulse` → the
line spelled cell by cell → `▶ end-of-message (close)`.

**Say (live path only):** "Now I'll give the relay an intent instead of a
message: \"meds at nine.\" When it fires, NVIDIA Nemotron 3 Nano on Nebius
Token Factory writes the line, and the phone spells it. The model call finishes
before the turn starts. The ticks are the demo's fixed wait."

**Say (no-key path, the default):** "Now I'll give the relay an intent instead
of a message: \"meds at nine.\" With no live model path, the promise fires
verbatim, labelled text echo, and the log names the path. No model is claimed
when none ran."

Either way the beat is the same turn pipeline: cue → working ticks → cells →
close, and the refusal beat's fills queue behind it. No Omni model is shown or
named in either path — it is held as asset, not demonstrated.

### 1:35–2:35 — the relay keeps the promise

**Live fire** — terminal B (fresh `$NOW`):

```bash
NOW=$(date +%s); curl -X POST http://127.0.0.1:8787/api/ziv/schedule -H "Content-Type: application/json" -d "{\"fire_at\": $((NOW+8)), \"text\": \"pills\"}"
```

Hands off. ~9 s later, unprompted: `reminder: pills` narration → Z-I-V
cells → `▶ triple-pulse — 70,160,70,160,70,420 ms` → close.

**Stored-while-away** — schedule a second reminder the same way
(`"text": "water the plants"`), then **close the browser tab**. ~9 s later
reopen it: hello ends `…, 1 message(s) waiting`, and the replay arrives as
a self-naming turn (`reminder: water the plants` → mark → `triple-pulse` →
content → close).

**Say:** "Scheduled reminders fire from the relay, and a message that arrives
while the phone is away waits in the capped inbox. Reopening this tab is the
attach; the replay names itself first. The phone renders only while this page
is open — nothing wakes a closed browser."

### 2:35–2:50 — the durability beat

Schedule a fresh reminder (`"text": "call grandma"`, `+3600`), then
terminal B: **Ctrl-C** the server → start it again →

```bash
curl http://127.0.0.1:8787/api/ziv/schedule
```

**Expect:** `{"reminders":[{…"text":"call grandma"…,"fired":false}]}` —
same id, same fire_at.

**Say:** "Kill the relay, restart it — the promise survives. It is written to
disk, atomically, capped, and corrupt-tolerant. No microphone in this build:
Ziv receives; it does not listen."

*(Cleanup after REC: `curl -X DELETE http://127.0.0.1:8787/api/ziv/schedule`.)*

### 2:50–3:00 — who it serves + proof

**Say:** "This is a phone prototype, not the wrist. The wrist is next: same
relay, same timing, a hardware-gated mic, and chord input. For a deaf-blind
person who reads braille, this is a channel worth testing — not a proven
reading method. Ziv. Messages you can feel."

Cut to the title card: repo URL + tagline.

---

**Contingencies:** the refusal beat needs the queue *full* while a long turn
plays — if the starter closes early, re-send `hold that thought` and
continue; the model beat needs `NEBIUS_API_KEY` set (otherwise use **Stub
demo** and say "keyless stub"); the serial channel is the design — always
wait for `end-of-message` before the next beat; if the reminder fires early
(scheduling slack), the replay-in-inbox path shows the same mark, so keep
rolling.
