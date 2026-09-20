# Phone-Prototype Plan — Ziv, 4-Week Sprint (Oct 30 deadline)

> **Scope:** a phone-based prototype of an always-on AI companion for deaf-blind users, demoed on Android Chrome via the Vibration API. The wrist hardware (ESP32-S3 + DRV2605L + 6 LRA motors, ~$40 BOM) is the next revision — this sprint proves the companion loop on hardware everyone already owns.
>
> **Honest claim:** "a working prototype of a new channel" — not therapy, not a shipped product, not a wrist band yet. The demo is a real loop judges can open and feel.

---

## What exists today (the starting line)

| Component | Where | State |
|---|---|---|
| Relay server (FastAPI) | `agent/ziv_server.py` | Complete: WS transport, message turn pump through `MessageGate` + `TurnTimeline`, `/api/ziv/message`, `/inject/audio` (real Token Factory Omni call, `NEBIUS_API_KEY`-guarded, `simulate` stub for keyless demos), `/api/ziv/timing` (serves the generated module), inbox persistence, wearer prefs, health telemetry, optional auth |
| Phone client (PWA) | `agent/ziv_client/index.html` | Complete: connects via WS, renders haptics via Vibration API, bootstraps ALL timing from `/api/ziv/timing` (zero duration literals), mic recording → `/inject/audio` → Omni path, stub demo path (keyless), redial logic (arms retry on 429, fires on the `free` close), queue badge polling, spell-cell highlight |
| Wearer memory + inbox | `agent/ziv_store.py` | Complete: `WearerMemory` (atomic JSON per key, corrupt-file tolerant), `MessageInbox` (capped persistent inbox, gated delivery, redelivery-never-loss) |
| Relay seam (contract) | `agent/ziv_relay.py` | Complete: `MessageGate`, `TurnTimeline`, `TelemetryRing`, `TurnEvent` — self-standing, no SkillForge imports |
| Generated timing module | `tools/haptic_timing_gen.py` | Complete: spec v3, 7 attention patterns, 26-letter alphabet, 5 marks, prefix composition |
| Timing generator + drift guard | `tools/haptic_timing.py` | Complete: verifies all 7 consumers match the spec; `--write` regenerates them |
| Test suite | `agent/tests/` | 8 files, hermetic: server tests (29), e2e tests (12 incl. redial), seam contract test, timing drift guard, rename check, m1 summary, redial e2e |

**Gaps this sprint fills:** scheduled/always-on behavior, on-phone chord input UI, richer memory story, real Omni spike verification, reachable demo URL, demo video + Devpost write-up.

---

## Week 1 — Omni spike + reachable demo + always-on skeleton

**Goals:**
- Verify the real Token Factory Omni audio endpoint end-to-end (close the §11 open question: exact `input_audio` payload format TF expects).
- Get the relay + PWA onto a reachable URL (working demo URL requirement for Personal AI track).
- Add the always-on skeleton: one scheduled job that fires unprompted.

**Tasks:**
1. **Omni spike verification.** Set `NEBIUS_API_KEY` in `agent/.env`, hit `/inject/audio` with a real mic clip from the PWA (or a pre-recorded webm), confirm the `input_audio` content part (base64 + format) TF accepts, confirm the transcript comes back, confirm the transcript takes the same turn a typed message would (cue → ticks → cells → close). If it works: real voice path. If it fails: the `simulate` stub is already the fallback — honest about which.
2. **Reachable demo URL.** Decide hosting: (a) tunnel from the relay to the internet (ngrok/Cloudflare tunnel — quick, but URL may be ephemeral), or (b) deploy the relay on Nebius (Serverless Endpoint or a container on AI Cloud — stable URL, doubles as the "runs on Nebius" story). Week-1 decision. The relay already serves the PWA from `/ziv_client/index.html`, so one process is enough.
3. **Always-on skeleton.** Add a background task in the relay that fires one scheduled job unprompted — e.g., a "morning brief" reminder at a set time. The job plays the name mark + cue + content on any attached band, or stores to inbox if none attached. This is the "acts while you're away" beat. Keep it simple: a timed loop in the relay, not a full Nebius Serverless Jobs integration (add that later if time permits — don't claim it unless wired up).

**Deliverable:** a phone you can open on Android Chrome, connect to the relay, talk to Omni (or use the stub), feel the reply, and see a scheduled job fire unprompted.

---

## Week 2 — On-phone chord input + memory polish

**Goals:**
- Add a 3×2 chord button grid to the PWA (the braille-chord input the plan describes, rebuilt for phone).
- Fill in `WearerMemory` with a real memory story (profile, preferences, session log) that survives restarts.

**Tasks:**
1. **Chord input UI.** A 3×2 grid of on-screen buttons in the PWA, mirroring the braille dot layout (dots 1-2-3 left column, 4-5-6 right column). The wearer holds a chord (combination of buttons) → compose mode → text goes to the agent → reply plays as vibro-braille. This is the "two-way" story: input in the wearer's literacy, output on the skin. Start with a simple chord-to-letter mapping (the 6-key braille chord system); the 3-button fallback (read/stop/repeat) is the floor, chords are the upgrade path.
2. **Memory story.** Fill `WearerMemory` with: profile facts (wearer name, preferred pace, a contact list), a session log (what happened, when), and demonstrate it surviving a relay restart (the existing `ziv_data/` JSON files already persist across restarts — show that). The track wants "persistent memory" — show it.

**Deliverable:** a two-way conversation on the phone: you chord a reply, the agent answers, the reply plays as vibration. Memory persists across restarts.

---

## Week 3 — Always-on demo flows + hardening

**Goals:**
- 2-3 real scheduled jobs that fire unprompted (morning brief, reminder, ambient check on demand).
- Hardening: reconnect logic, error patterns, mock mode, telemetry with cost-per-turn.

**Tasks:**
1. **Scheduled jobs.** Build 2-3 real daily-workflow jobs: (a) morning brief — overnight job checks calendar/reminders, fires at a set time with name mark + brief content; (b) a timer/reminder — wearer chords "remind me in 10 minutes," the job fires unprompted; (c) ambient check on demand — long-press mic → 5s capture → Omni → reply on wrist. These are the "daily workflows" and "always-on" beats. At least one must be visible in the demo video firing unprompted.
2. **Hardening.** WS reconnect logic (the PWA already retries on disconnect — verify it works end-to-end). Error patterns (the `long-buzz` path — when Omni fails, the wrist feels the error, not silence). Mock mode for when the relay is unreachable (the `simulate` stub already exists — wire it as a toggle). Telemetry that shows cost-per-turn if you're using real TF calls.
3. **Demo video script.** Take shape from the plan doc's §8: the gap (price cards), the conversation (sighted helper speaks → phone feels reply → wearer chords back), the always-on (scheduled job fires live), the stack (Omni hears, Nano reasons, Nebius runs).

**Deliverable:** a phone that feels like an always-on companion — messages arrive unprompted, the wearer can check ambient, the relay survives restarts, errors are felt not silent.

---

## Week 4 — Demo video + Devpost + repo polish

**Goals:**
- Record the ≤3 min demo video.
- Write the Devpost submission (honest about phone vs. wrist hardware).
- Repo polish: README with setup instructions, license visible at top, highlight Nebius + NVIDIA usage.

**Tasks:**
1. **Demo video.** Record the ≤3 min public YouTube video. Script (adapted from the plan doc's §8): (a) 0:00–0:20 — the gap: price cards (braille display $4,000, Hable One $349, this device ~$40 phone prototype), one sentence of who it's for; (b) 0:20–1:10 — the conversation: a sighted helper speaks to the phone, the reply plays as vibration, the wearer chords a reply, the helper's phone shows the relay-pushed text; show the relay log + Omni call telemetry on screen (Token Factory + NVIDIA open model visible); (c) 1:10–1:50 — always-on: the scheduled job fires unprompted on camera, memory file shown; (d) 1:50–2:20 — the stack: Omni hears, Nano reasons, Nebius runs, cost-per-turn readout; (e) 2:20–3:00 — honest scope: "a phone prototype of an always-on companion; the 6-motor wrist band is the next hardware revision."
2. **Devpost submission.** Write the Devpost project page (the existing `DEVPOST_HAPTIC.md` is a draft for the 8-week plan — rewrite it for the phone-prototype scope). Be honest: "phone-based prototype; the wrist hardware is the next revision; reading temporal braille on phone vibration is an open research question; the demo demonstrates the always-on companion loop." Personal AI track. Working demo URL. Demo video. Public repo with Apache 2.0 license.
3. **Repo polish.** README: setup instructions (the track requires this — `cd agent && pip install -r requirements.txt && python ziv_server.py`, open the URL on Android Chrome). License visible at top (Apache 2.0 already exists). Highlight Nebius + NVIDIA usage (Token Factory inference for Omni + Nano, the relay's self-hosted story, the always-on scheduling). Update the roadmap to show the phone-prototype sprint as the current work.

**Deliverable:** a submitted hackathon entry — working demo URL, demo video, public repo, honest Devpost write-up.

---

## Honest scope statement (the line you don't cross)

> **Ziv is a phone-based prototype of an always-on AI companion for deaf-blind users.** A sighted person speaks to the phone; Nemotron-3-Nano-Omni on Nebius Token Factory transcribes and understands; the reply plays as temporal braille on the phone's vibration motor. The wearer replies with on-screen braille chords. Scheduled jobs deliver reminders unprompted. The device that speaks braille on a 6-motor wrist band (ESP32-S3 + DRV2605L + LRA motors, ~$40 BOM) is the next hardware revision — the phone demonstrates the companion loop now.

**Risks flagged openly:**
- Phone vibration is a weaker braille channel than 6 LRA motors — reading temporal braille on a single eccentric motor is harder than on dedicated motors. Handled honestly: "a phone prototype demonstrating the always-on companion loop; precise haptic braille on a 6-motor wrist device is the next hardware revision."
- The Omni audio payload format is verified in week 1 or you fall back to the `simulate` stub (already exists) — honest about which.
- No braille-reader usability sessions in 4 weeks — the learnability question is real and you say so: "reading temporal braille on vibration is an open research question; the phone prototype demonstrates the loop; reader validation is the next step."
- The "data under your control" story is decent but not deep — the relay is on your Nebius account, not the user's. Honest framing: "self-hosted relay on our Nebius account; the phone is the wearer's device; haptic output leaks nothing."

---

## What's scoped out (to keep it 4 weeks)

- ESP32 firmware, FreeRTOS, I²C driver bring-up, QEMU ladder — dropped (wrist hardware path).
- Braille-reader usability sessions — dropped (honest about it being the next step).
- Grade 2 contractions — dropped.
- BLE caregiver bridge — dropped.
- Qwen distillation path — dropped.
- Full "SOUL.md / MEMORY.md / session JSONL" memory architecture — simplified to "WearerMemory + inbox + session log."
- Per-contact people-marks, on-device practice mode — dropped.

## What's kept and built on

- The existing relay + PWA + timing spec + test discipline — all of it.
- The interaction invariants (queue-don't-interrupt, end-of-message close, processing ellipsis, name mark first) — in the code, proven in tests.
- The `simulate` stub path — hermetic demo fallback, already there.
- The redial logic on 429 — shows the queue gate is real.
- The "private by physics" story — haptic output on a phone is still private.

---

*Last updated: 2026-09-19 (week-1 start). The wrist-hardware plan lives in `HAPTIC_COMPANION_PLAN.md`; this doc is the 4-week phone-prototype sprint.*
