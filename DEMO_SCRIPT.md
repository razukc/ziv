# Single-Take Demo Script — Ziv (≤3:00)

One page. Read top to bottom while recording; every expected line is the
real string (verified against the client and server source). Terminal B
commands run from `agent/`. Browser zoom 125%, desktop width, dev-band page
open at `http://127.0.0.1:8787/ziv_client/index.html`.

**Pre-roll (before REC):**

- [ ] Terminal A: `python -m pytest -m "not e2e"` → `126 passed, 2 skipped` (keep the tail on screen)
- [ ] Terminal B: `ZIV_FAKE_MODEL_SECONDS=8 python ziv_server.py` → `Uvicorn running on http://0.0.0.0:8787` (8 s fake-model = room to work; every turn ~10 s)
- [ ] Browser: open the dev-band page → `relay hello — spec v3, … patterns, mark: ziv`
- [ ] Click **Unlock vibration** → `vibration unlocked`; badge reads `queue 0/8 · reminders 0/64`
- [ ] Message box cleared; mic unmuted; REC ●

---

### 0:00–0:15 — cold open (the privacy shot)

Phone face-down on the desk. Terminal B:

```bash
curl -s --max-time 90 -X POST http://127.0.0.1:8787/api/ziv/message -H "Content-Type: application/json" -d "{\"text\": \"taxi is here\"}"
```

*(Without `--max-time`, curl on Windows hangs until the whole turn completes —
always pass it; the POST returns only when the turn is done.)*

**Say (over the buzz):** "A message only one person receives."
**Expect on page:** `▶ double-tap (kind cue) — 70,160,70,420 ms` →
`working… (working)` → `message: taxi is here` → 10 `cell` frames →
`▶ end-of-message (close) — 200,120,140,120,90,120,50,420 ms`.
Pick the phone up; fingers read it; put it down.

### 0:15–0:40 — the channel, read top-down

Type `call me back` → **Send as message**.

**Expect:** cue → `working…` → `message: call me back` → 10 cells → close.
**Say:** "Arrival cue, working ticks, braille cells, felt close — the same
timing the wrist firmware plays; no screen, no sound."

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

**Say:** "A full queue is a loud no — and the client redials by itself the
moment the close frees the channel."

### 1:10–1:35 — speech in (the Omni turn)

Hold **Talk to Omni** → `recording — speak, then tap again (10 s max)` →
say "who is calling" → tap again → `transcribing via Token Factory…` →
`mic clip: NN kB (audio/webm)` → `Omni heard — turn turn_complete, source audio_omni`
→ the turn plays (`message: who is calling` → 12 cells → close).

**Say:** "One model, audio in — the transcript runs the relay's single turn
pipeline. If the provider fails, the wrist feels the error long-buzz."

### 1:35–2:35 — the agent acts while you're away

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

**Say:** "It schedules, fires, and stores while you're away — nothing is
dropped, and every unsolicited arrival names itself first."

### 2:35–2:50 — the durability beat

Schedule a fresh reminder (`"text": "call grandma"`, `+3600`), then
terminal B: **Ctrl-C** the server → start it again →

```bash
curl http://127.0.0.1:8787/api/ziv/schedule
```

**Expect:** `{"reminders":[{…"text":"call grandma"…,"fired":false}]}` —
same id, same fire_at.

**Say:** "Kill the relay, restart it — the promise survives. Durable like
the inbox: atomic JSON, capped, corrupt-tolerant."

*(Cleanup after REC: `curl -X DELETE http://127.0.0.1:8787/api/ziv/schedule`.)*

### 2:50–3:00 — who it serves + proof

**Say:** "For meetings, kitchens, night shifts — and the deaf-blind
community nothing else is built for. Every claim here is reproducible:
JUDGE_REPRO.md maps claims to proof; HONESTY_CHANGELOG.md is the audit
trail. 129 green tests. This is Ziv — messages you can feel."

Cut to the title card: repo URL + tagline.

---

**Contingencies:** the refusal beat needs the queue *full* while a long turn
plays — if the starter closes early, re-send `hold that thought` and
continue; the mic beat needs `NEBIUS_API_KEY` set (otherwise use **Stub
demo** and say "keyless stub"); the serial channel is the design — always
wait for `end-of-message` before the next beat; if the reminder fires early
(scheduling slack), the replay-in-inbox path shows the same mark, so keep
rolling.
