# Concept + MVP Plan — Ziv (working title), a Haptic AI Companion for Deaf-Blind Users

Concept and build plan for the **Personal AI track** submission. This doc
records the pivot decision, the problem, the device concept, the interaction
design, the architecture, and the MVP scope — it defines the build, it does
not contain it.

**Decision (Sep 7, 2026):** the second submission is the deaf-blind haptic
companion — **Ziv** (working title) — not the general push-to-talk pin. The direction was chosen from
[CAPABILITIES.md](./CAPABILITIES.md) problem candidates + the MimiClaw/Pi Pin
hardware research in [MIMICLAW_PIPIN_RESEARCH.md](./MIMICLAW_PIPIN_RESEARCH.md),
then pivoted to this accessibility angle. Facts below were captured Sep 5–7,
2026 from vendor docs, source trees, and reviews, with sources linked. Claims
we could not verify are listed under
[Open questions](#11-open-questions-verify-before-scoping) or flagged `⚠`
rather than asserted.

---

## TL;DR

- **The product:** **Ziv** (working title) — a ~$35 wearable pin (ESP32-S3 + microphone +
  6 vibration motors + 6 braille keys) that lets a deaf-blind person *hear*
  the world
  (speech → braille on the skin) and *converse* through it (braille chords
  in, haptic braille out), powered by **Nemotron-3-Nano-Omni on Nebius Token
  Factory**. One model hears; the user's skin is the display.
- **Why this wins the track:** it satisfies the full two-part sentence —
  always-on (relay + heartbeat + scheduled jobs), private (haptic output is
  private by physics; memory on flash; self-hosted relay), persistent memory,
  reusable skills, daily tasks — with **≥1 NVIDIA open model** (Omni + Nano)
  doing real work. Impact and Idea criteria are the strongest we can reach:
  no existing product pairs haptic braille with an always-on agent.
- **Why it's buildable in 8 weeks:** the pivot *removes* the hardest problems
  of the general voice pin. No speaker → no echo cancellation, no wake word,
  no TTS path. The output channel is 6 vibe motors on a ~$5 I²C haptic driver
  chip. The relay is thin, and Token Factory now serves an omni model that
  takes audio input directly — no separate STT service.
- **Week-1 spike gate:** one voice clip from the board → Token Factory Omni →
  reply text → vibro-braille pattern on the motors, end to end. If that works,
  build the MVP; if not, the fallback (text-agent floor, Route A from the
  research note) still ships and clears the bar.

---

## 1. Decision record — what changed and what carries over

| | Was (research note §7) | Now |
|---|---|---|
| Direction | "Submit B, built so it collapses to A" — push-to-talk wearable pin for a general user | **Deaf-blind haptic companion**; the pin form factor is kept, the user and I/O change |
| Primary user | anyone | **Deaf-blind** (combined hearing + vision loss) |
| Input | push-to-talk mic | push-to-talk mic **+ 6-key braille chord keyboard** |
| Output | Telegram text (later TTS + speaker) | **6-dot vibro-braille on the wrist** (no speaker, ever) |
| Brain | Nemotron text model + separate Whisper-class STT on a relay | **Nemotron-3-Nano-Omni** (audio in, text out) for voice turns; **Nemotron-3-Nano-30B-A3B** for cheap text turns |
| Hardest risks | AEC, wake word, streaming latency | vibro-braille learnability; motor choice |

What carries over unchanged from the research note: the board-selection table
(N16R8-class boards, §5 there), the `mimi_config.h` compile-time base-URL
caveat and the Nebius hosted-API surface facts (§4 there), the track criteria
and Stage One gate (§7 there), and SkillForge's reusable patterns (streaming,
auto-retry, telemetry, hermetic tests, mock mode). What is superseded: §7's
"submit B" recommendation and the Route C duplex plan — see §3 for why C's
hard problems disappear here.

### Naming

**Working title: Ziv.** The name has two layers, and the second is the one the wearer owns. The trail to this decision:

1. **"Tact" withdrawn** (Sep 7, 2026) — too literal; it named the feature from the sighted-hearing perspective.
2. **"Raz" tried and retired** — the founder's own name and a perfect mark (R-A-Z = heavy-light-heavy), but the word collides with **RAZ Mobility** (razmobility.com), an established US assistive-tech company for blind and low-vision users: the RAZ Memory Cell Phone (sold by Verizon since Jul 2025), SmartVision 3, and Lucia; founder Robert Felgar, previously founder of Odin Mobile, the first wireless carrier for blind users. Identical word, same industry, same channels — a textbook likelihood-of-confusion case.
3. **Ten names screened** — Ziv (cleanest), Boaz (clean), Razu (clean), Tov (TOV Furniture holds marks); later probes rejected: Viz (Viz.ai, a $1.2B AI-healthcare company with FDA-cleared "Viz" products; EZVIZ in class 9), Buz (Neosensory Buzz — a shipped haptic wrist wearable for deaf users; same category, same audience, phonetic twin), A2Z (on Amazon's own trademark list, next to the A-to-Z Guarantee; the most generic surface of the ten, and its digit forces a number-sign cell into the mark). The pattern after ten names: every sensory-feeling word is already claimed inside this industry; the arbitrary personal names are the ones that stay clean. (The alphabet-span idea survives as a name for the device's braille-teaching mode, not the product.)
4. **The rule the trail produced: the mark is the name; the word is a handle.** The word is chosen by cost, not meaning — legal cleanliness, sayability for the sighted-hearing people who buy and install the device, and braille agreement (the word's spelling is exactly what the mark plays). Meaning is the mark's job. Arbitrary personal signs, not descriptive labels, remain the cultural anchor — people in Deaf/DeafBlind communities are identified by name signs and tactile name cues, felt patterns rather than descriptions (sources under Sources).
5. **The word: *Ziv* (working title)** — Hebrew "radiance"; one syllable; Z-I-V = heavy-light-heavy, the identical felt identity Raz had, with none of its collisions (spec in §4).
6. **The community holds final naming authority.** In DeafBlind practice, name marks are given by the community, not self-declared. The submission ships under "Ziv (working title)"; the week-6 braille-reader sessions (§7, §9) formally validate the mark and the word — or rename the device.

---

## 2. Problem brief

**Who:** people with combined hearing and vision loss — deaf-blind. Scale:
~45,000–50,000 deaf-blind people in the US per the classic estimate used by
HKNC-related material; ~70,000 per Wikipedia's summary of HKNC data; ~2.4
million Americans with *combined* hearing and vision loss per HKNC's 2026
DeafBlind Awareness Week statement (ACS 2022 analysis). The population is
small enough that no mass-market product is built for it, and large enough
that the gap is real.

**What they need daily** (from the daily-workflow list the track asks for):

1. **Announcements** — what just happened: a knock, a doorbell, a timer, an
   incoming message, a smoke alarm, a name called across the room.
2. **Two-way conversation** — a sighted/hearing person speaks; the wearer
   reads and replies.
3. **Ambient awareness on demand** — "what's around me right now?"
4. **Agent tasks** — reminders, renewals, scheduling, lookups — the
   always-on assistant part, acting while the wearer is away.

**Why current assistive tech fails this:**

| Device class | Price | What it does | The gap |
|---|---|---|---|
| Refreshable braille displays | **$1,500–$12,000** (40-cell ~$4k–6k; 80-cell ~$8k–12k; piezo cells ≈ $35/cell ≈ $4.38/dot) | renders text as braille | no microphone, no agent, no always-on awareness; priced like medical equipment |
| Braille keyboards (e.g. Hable One) | $239–$349 | 6-key braille input to a phone | **input only** — no output channel, no agent |
| Phone vibro-braille research (V-Braille, HoliBraille, UbiBraille, BrailleBand) | research prototypes | haptic braille via phone vibration | no microphone, no agent, no wearable form factor |
| "AI pins" (Humane lineage, modern clones) | $$ | voice + screen/audio | useless to someone who cannot hear or see the reply |

**The moat sentence:** *no existing product pairs a haptic braille output
channel with an always-on agent.* Consumer "pins" serve eyes and ears; braille
displays serve eyes but not ears; nothing serves both at once with a brain
behind it. This combination falls directly out of the stack we already have —
an omni-modal NVIDIA model that hears, and a $5 haptic driver that speaks
braille — which is exactly the "combinations only this stack enables" method
CAPABILITIES.md prescribes.

**Privacy note (this is a feature, not a footnote):** a haptic output channel
is **private by physics**. Nobody sees a screen, nobody overhears a speaker;
a private message vibrates on the wearer's wrist and is invisible to everyone
else. For a population that already depends on others for information, the
device that tells you things *without telling the room* is a dignity feature.

---

## 3. Device concept — "the pin that speaks braille"

A wrist-worn (or pinned) unit, roughly the footprint of the Xiaozhi-class
board plus a battery, with:

- **6 vibromotors** arranged in the 3×2 braille dot layout (dots 1-2-3 left
  column top-to-bottom, 4-5-6 right column), driven by one DRV2605L I²C
  haptic driver (~$5; drives ERM and LRA motors, 123-effect library, ESP32 +
  Arduino/ESP-IDF drivers exist; I²C address 0x5A). One motor per dot.
- **6 tactile keys** in the same 3×2 layout (per-key GPIO, no matrix needed
  for 6 keys) — a braille chord keyboard, the Hable One pattern rebuilt for
  ~$3 of buttons.
- **One MEMS microphone** (I2S, on-board on Xiaozhi-class kits) — for
  *other people's* speech and ambient sound, on push-to-talk or a hardware
  listen switch. The wearer never needs to speak: their channel in is braille
  chords, out is vibration.
- **ESP32-S3 N16R8** (16 MB flash + 8 MB PSRAM — the MimiClaw requirement)
  with WiFi; BLE kept available for future phone pairing but not in the MVP.
- **LiPo + charge circuit** (most N16R8 kits carry one; per-revision ⚠).

**Deliberate omissions, and why:**

| Omitted | Why |
|---|---|
| Speaker / amp | the wearer can't hear it; removing it kills AEC, wake word, and the TTS pipeline — Route C's entire hard-problem list |
| Screen | the wearer can't see it |
| Camera | out of MVP scope; Omni could take image input later (scene description is a natural v2) |
| Always-on mic | privacy-first: capture only on push-to-talk / hardware switch; ambient eventing starts from *digital* events (messages, timers, integrations), not continuous listening |
| Telegram as the primary channel | a third-party chat app is not the interface for this user; the WebSocket gateway is the primary channel (Telegram may remain as a caregiver bridge later) |

**Bill of materials (MVP, one unit):**

| Part | Est. cost | Notes |
|---|---|---|
| ESP32-S3 N16R8 board with mic (Xiaozhi-class kit) | ~$10 | board table in research note §5 |
| DRV2605L breakout (Adafruit 2305 / SparkFun 14538) | ~$5–8 | I²C, STEMMA QT |
| 6× LRA vibe motors (or 6× small ERM) | ~$6–12 | LRA crisper for braille; ⚠ ERM acceptable MVP fallback |
| 6× tactile buttons | ~$3 | braille chord input |
| LiPo (400–600 mAh) + charger/boost | ~$8 | kit-dependent ⚠ |
| Wrist strap / printed case | ~$5 | |
| **Total** | **~$37–46** | fits the ~$150 credit/hardware envelope with relay costs |

---

## 4. Interaction design v0**Haptic vocabulary (attention + lifecycle layers)** — short motor patterns that
are *not* letters, learned in minutes:

| Pattern | Meaning |
|---|---|
| double tap | new message arrived |
| long buzz | error / attention needed |
| triple pulse | scheduled task completed |
| ramp up | device booting / connecting |
| heartbeat tick | alive check (configurable, off by default) |
| processing | working — your request is being handled (repeats while a turn is in flight) |
| end of message | message complete — the wrist is quiet until you ask |

The last two are **lifecycle** patterns, added spec v3 after early-years
deafblind practice (Sense UK, via Insight — see Sources) sharpened the
interaction design: a device whose user receives little and distorted
information must make every wait legible and every event endable. `processing`
is two slow ticks — an ellipsis that spans capture → model → playback; latency
may be slow, never silent. `end-of-message` is ramp-up's mirror (four ticks
descending 200→140→90→50) — until it plays, the silence after a last cell was
indistinguishable from the gap before a next one.

Every pattern's exact beats live in [HAPTIC_TIMING_SPEC.md](./HAPTIC_TIMING_SPEC.md): the phone feel-tool, the `haptic_out` firmware, and the Python consumer (`tools/haptic_timing_gen.py` — what tests, the relay, and tools import) are generated from the same [haptic-timing.json](./haptic-timing.json), so the mock, the band, and every Python-side derivation play identical patterns by construction.

**Device identity — the name mark.** The pin identifies itself haptically: at boot, and as the first element of any message that arrives *unprompted*, it plays its name — **Z-I-V spelled in vibro-braille** on the 6 motors (Z = dots 1-3-5-6 → four motors pulse as one heavy beat; I = dots 2-4 → two motors, a light beat; V = dots 1-2-3-6 → four motors, heavy again: a *heavy-light-heavy* arc that ends decisive — the identical arc "Raz" would have played). This mirrors how DeafBlind communities identify people by tactile name signs rather than descriptive labels — the wearer learns the device's name as a felt pattern, and the same learning reinforces the braille alphabet. A second device (caregiver bridge, v2 form factor) gets its own mark, so multi-device haptic "caller ID" falls out for free.

**Vibro-braille playback (content layer)** — the reply text is rendered as
braille and played onto the 6 motors, one cell at a time: the motors
corresponding to that character's raised dots pulse together (e.g. "b" = dots
1,2 → left-top and left-middle motors pulse as one beat), then a short gap,
then the next cell. Reading is *temporal* braille — the same alphabet the
user already knows, played as rhythm instead of shown as pins.

- **Grade 1 (uncontracted) English braille** for the MVP. Contractions
  (Grade 2) compress ~20–40% of cells but add a translation surface; parked
  behind a config flag (see open questions).
- Playback controls via chord keys: **replay last cell**, **pause/resume**,
  **skip forward/back a word**, **speed** (inter-cell gap), **stop**.
- Letter-by-letter pacing is the MVP; word-shape "corner" cues (space
  signals, capital signal, number sign) included from day one because
  experienced braille readers navigate by them.

**Reply flow (input layer):**

1. wearer holds a chord on the 6 keys (or presses a dedicated key) →
   **compose mode**: keys now type braille chords (dot combinations per
   character), displayed nowhere — it goes straight into the message buffer;
2. send chord → text goes to the agent → reply comes back → played as
   vibro-braille;
3. at any time, **push-to-talk** lets a *sighted helper* speak to the pin:
   their speech goes to Omni, and the answer lands on the wearer's wrist.
   This is the demo's core moment: a conversation where one party hears and
   the other feels, with no screen or sound in between.

**Escape hatches:** every mode is exited with a long-press chord; the device
has exactly two modes (read / compose) plus attention patterns — no menus to
get lost in. ⚠ All of this is a v0 design to be validated with braille
readers; the learnability risk is real and is treated as a first-class risk
in §9, not a footnote.

### Interaction invariants (from early-years deafblind practice)

What early-years deafblind education teaches — and what a device for adults
with the same sensory reality must honor — stated as rules the firmware, relay,
and every future pattern must keep. Sources: Sense UK's early-years guidance
(Sources).

1. **No content without a kind cue first.** Unprompted content always opens
   with the name mark and its attention tail (§4 prefix). A buzz that means
   "something" with no "what kind" is the inconsistent-information problem
   the device exists to solve.
2. **Cues mark the start *and* the end of an event.** The `end-of-message`
   pattern plays after the last cell of any played content; a message is over
   when the wearer feels it is over, not when the buzzing merely stops.
3. **Waiting is legible.** A turn in flight repeats `processing` (~2 s)
   until content or error plays; latency may be slow, never silent.
4. **Queue, don't interrupt.** An incoming message during playback plays its
   attention cue only and queues its content; nothing barges into what the
   wearer is already reading. They release the queue — the wearer stays in
   control (first relay behavior, `agent/ziv_relay.py`).
5. **Structure is universal, parameters are personal.** The same event always
   plays the same cue; per-wearer tuning (cell gap, vocabulary toggles) lives
   inside the spec envelope and never changes a cue-to-event mapping.
6. **Every state transition is feelable.** Boot, connect, reconnect, error —
   no silent state changes (ramp-up, long-buzz, error tails).

These rules are executable, not prose: `TurnTimeline` (`agent/ziv_relay.py`)
walks one turn through cue → processing ticks → playing → end-of-message →
gate release, wired to the queue gate, and the e2e suite proves the order —
a relay bug that skips the wait or closes what never played crashes in the
seam instead of reaching the wrist (invariant 5, enforced structurally).

### The four flows (demo-shaped)

1. **The morning brief.** Overnight, a scheduled relay job checked the calendar and email. At 8:00 the wearer feels the name mark, then a double-tap: new message. They press read: the wrist plays *"9 AM — nurse visit. 2 PM — pharmacy refill."* They chord back *"ok"*. Thirty seconds, nothing seen or heard by anyone else.
2. **The conversation.** A sighted friend leans in: *"The taxi's here — should we go?"* The wearer presses talk; the friend's speech goes to Omni; the reply vibrates onto the wrist: *"Taxi arrived. Leave now?"* The wearer chords *"yes, 2 min"*. Honest scope note: in the MVP the reply reaches the friend as text on their phone (relay push); spoken replies are v2 — Token Factory serves no TTS. One party hears, the other feels, and the room perceives nothing.
3. **Ambient check on demand.** Long-press → the mic opens for 5 seconds *only because the wearer chose it* → *"Someone knocked twice. Your timer is ringing."* Privacy-consistent: no always-on listening, ever — the mic is hardware-gated.
4. **The agent task.** The wearer chords *"remind pills 9pm"*. At 9pm a triple pulse arrives unprompted, then *"Pills."* The track's "acts while you're away" beat, proven by the overnight cron log.

---

## 5. Architecture

```
[wearable: ESP32-S3 N16R8]
  I2S mic ──► WAV/Opus capture (push-to-talk)
  6 keys ──► braille chord input
  DRV2605L (I²C) ◄── vibro-braille + attention patterns
        │  text JSON + binary audio frames over WSS
        ▼
[relay on Nebius — thin FastAPI service, self-hosted by us]
  WS gateway (auth: per-device key, allow-list of device ids)
  audio → Token Factory Omni (chat/completions, audio input part)
  text  → Token Factory Nano-30B-A3B (cheap text turns)
  memory: sessions + MEMORY.md-style state (flash on device; relay keeps history)
  cron/heartbeat: scheduled jobs fire even with nobody "chatting"
        ▼
[Nebius Token Factory — NVIDIA open models]
  Nemotron-3-Nano-Omni  (audio in → text out; hearing)
  Nemotron-3-Nano-30B-A3B (text agent turns; cheap)
  Nemotron-3-Super-120B-A12B (optional: hard reasoning / long planning)
```

**Firmware modules** (ESP-IDF, C, MimiClaw-style file conventions):

| Module | Job |
|---|---|
| `audio_capture` | I2S → WAV frames on push-to-talk; upload as binary WS frames |
| `haptic_out` | DRV2605L driver; pattern vocabulary + vibro-braille sequencer (cell → dot bitmask → LRA waveforms; per-dot timing); timing constants + per-letter dot bitmasks generated from [haptic-timing.json](./haptic-timing.json) via `tools/haptic_timing.py` (header: [firmware/haptic_out/haptic_timing.h](../firmware/haptic_out/haptic_timing.h)) |
| `braille_in` | 6-key GPIO polling/debounce → chord decode → text buffer |
| `ws_client` | WSS to relay; text JSON frames + binary audio; reconnect/backoff |
| `memory` | SOUL.md / MEMORY.md / session JSONL on SPIFFS (the MimiClaw pattern, kept) |
| `config` | NVS: device key, relay URL, playback speed, pattern toggles |

**Simulation:** the firmware is built to run without hardware —
[QEMU_SIMULATION_LADDER.md](./QEMU_SIMULATION_LADDER.md) specs the ladder: the
real binary boots in Espressif's QEMU fork (rung 1) with the bench mock bus as
the haptic backend and the sequencer's own event stream printed as `HAP`
timeline lines, bench-vs-QEMU equivalence is diffed (rung 2), and WiFi/mic
return later behind transport/audio vtables (rungs 3–4). Hardware appears only
at bring-up.

**Relay** (FastAPI, mirroring SkillForge backend patterns): SSE/WS streaming,
bounded auto-retry with backoff on every model round-trip, `compose_stats`-style
telemetry, hermetic tests with a faked model client, mock mode for the device
when the relay is unreachable. It is thin on purpose: auth, frame routing,
model calls, memory, cron.

**Shared-layer seam (what exists today vs what does not):** the SkillForge
backend already owns the hard parts a Ziv relay would want — SSE event
machinery, bounded retry with backoff, a thread-safe capped telemetry ring,
and a fake-model harness used by the hermetic tests. Those reusable pieces were
extracted into a small shared core at `agent/ports.py` (no robot-track imports),
and a placeholder relay module was created at `agent/ziv_relay.py` as the
*seam* a future Ziv relay would implement — it documents the adapter contract
(``is_ready`` + ``run_turn``) and imports the shared layer, but is **not**
implemented yet. What does **not** exist yet is the relay itself: no mic/audio-in
path, no braille-chord input, no WebSocket/SSE relay, no ESP-IDF FreeRTOS task,
no Token Factory Omni audio payload wired up. When the relay is built, it fills
in `ziv_relay.py`'s adapter; the shared layer stays ignorant of braille chords,
FreeRTOS tasks, and haptic cells.

**Model routing (cost-aware autonomy, carried from SkillForge):** voice turns
→ Omni (only when audio arrived); plain text turns → Nano-30B-A3B; a
per-device daily token budget with automatic degradation to the cheaper model
— the always-on economics the track's Run layer asks for. Omni pricing on TF
⚠ ~$0.06 in / $0.24 out per 1M tokens per third-party trackers — verify on
the TF model page.

**Always-on (Run):** the relay is the 24/7 presence (heartbeat + scheduled
jobs via Nebius Serverless Jobs or a long-running container); the device
sleeps between events and wakes on button/capture/WiFi activity. The demo
must show a scheduled job firing while nobody touches anything.

**Assemble / Secure / Run mapping for this build:**

| Verb | This build |
|---|---|
| **Assemble** | memory on flash (SOUL/MEMORY), skills as markdown files the agent can load, the WS gateway as the chosen channel, Omni+Nano as the routed model pair |
| **Secure** | per-device key + device allow-list on the relay (the "agent only answers me" beat, from MimiClaw's own P1 TODO); relay egress allow-list (only Token Factory hosts); mic is hardware-gated (no always-on capture); haptic channel leaks nothing |
| **Run** | relay heartbeat + scheduled jobs on Nebius; device deep-sleep between events; cost-aware model routing |

---

## 6. Track mapping — why this satisfies the full sentence

- **Always-on:** relay-side heartbeat + scheduled jobs (provable in the demo:
  a reminder the wearer receives as a buzz they didn't ask for at that
  moment).
- **Private / data under control:** memory on device flash; self-hosted
  relay on our Nebius account; no third-party messaging channel in the
  critical path; the haptic output is the strongest privacy claim available —
  **private by physics**.
- **Persistent memory + reusable skills:** MimiClaw-style flash memory;
  skills as markdown the agent loads (the Hermes SKILL.md pattern, adapted).
- **Tools and channels of the wearer's choosing:** braille chords + mic +
  WS gateway; integrations (calendar, reminders) added as relay tools.
- **≥1 NVIDIA open model:** two, doing real work — Omni hears, Nano reasons.
- **Nebius tooling for assemble/secure/run:** Token Factory (Run), Serverless
  Jobs/Endpoints (Run), the relay's egress allow-list + device allow-list
  (Secure, mirroring OpenShell's policy-as-code posture), skills + memory
  (Assemble).
- **Impact/Idea:** a $37 device against a $1,500–$12,000 device class, for a
  population nothing else is built for, with a channel nobody else uses.

Stage One fit: this is a genuine attempt at the track's stated goal from a
capability-first analysis, not a rebrand — and the two existing docs
demonstrate the decision trail.

---

## 7. MVP scope + 8-week milestones

**MVP definition (the demoable bar):** a wearer receives a message as
vibro-braille, replies by braille chords, a sighted helper speaks to the pin
and the wearer reads the answer, and a scheduled job buzzes unprompted. No
screen, no sound, no phone in the loop.

| Week | Milestone | Gate |
|---|---|---|
| 1 | **Spike:** board mic clip → Token Factory Omni → reply text → DRV2605L pattern. Buy boards + motors + driver now (long-lead risk). The phone-mic half is already real: the PWA records via MediaRecorder and the relay transcribes with Nemotron-3-Nano-Omni on Token Factory (`/inject/audio`, `NEBIUS_API_KEY`-guarded) — only the board half waits on hardware. | end-to-end works or fallback decision |
| 2 | vibro-braille sequencer (alphabet + pacing + controls) on bench hardware; chord-key input decode | read a 5-word sentence by touch |
| 3 | WS relay v1 (auth, text frames, memory files) + firmware `ws_client`; text round-trip device ↔ relay ↔ Token Factory; compose mode has **no server-side timeout** (§4 invariants: chord composition is slow by design). The dev-band relay already carries the durable half (memory files + persistent inbox, `agent/ziv_store.py`) — messages survive restarts and the wearer's pace is a stored, spec-clamped preference | two-way text convo from the device |
| 4 | voice path live: push-to-talk capture → Omni → vibro-braille reply | the §4 conversation demo works |
| 5 | scheduled jobs + heartbeat + attention vocabulary; battery + deep-sleep polish | unprompted buzz demo; overnight runtime measured |
| 6 | usability pass with braille readers (sighted-proxy protocol, see §9); speed + pattern tuning; naming-validation session ([NAMING_VALIDATION_PROTOCOL.md](./NAMING_VALIDATION_PROTOCOL.md)) | reading-speed target met or scoped; mark + word validated, or rename queued |
| 7 | hardening: reconnect logic, error patterns, mock mode, hermetic relay tests, telemetry | test suite green; failure modes behave |
| 8 | demo video (≤3 min), Devpost write-up, repo polish, license/README | submission |

**Fallback ladder (decided in advance, not improvised):** if the week-1 spike
fails → ship the text-agent floor (Route A: WS gateway + Nano-30B-A3B +
vibro-braille of *text the agent already has*, no voice) — it still clears
always-on + memory + NVIDIA model. If Omni audio input proves unusable on TF
→ relay-side STT (Whisper-class on a Serverless Endpoint) behind the same
interface; only the relay changes.

---

## 8. Demo script (≤3 min video)

1. **0:00–0:20 — the gap.** Price cards: braille display $4,000, Hable One
   $349, this device ~$40. One sentence of who it's for.
2. **0:20–1:10 — the conversation.** A sighted helper speaks to the pin
   ("what's on my calendar today?"); cut to the wearer's wrist: vibro-braille
   playing; the wearer chords a reply; on the helper's phone, the reply arrives
   as text pushed by the relay (the friend reads it, there is no speaker in the
   room). Nobody touched a phone. Show the relay log + Omni call telemetry on
   screen (Token Factory + NVIDIA open model visible), with the relay log's
   friend-side text visible so the room can follow the reply.
3. **1:10–1:50 — always-on.** Show the heartbeat/cron log from overnight; a
   scheduled reminder buzzes the wearer live on camera; memory file on flash
   shown (`MEMORY.md`).
4. **1:50–2:20 — secure.** The device allow-list rejecting an unknown device
   (the "agent only answers me" beat); relay egress allow-list shown; mic
   hardware switch shown off.
5. **2:20–2:50 — the stack.** Diagram: Omni hears, Nano reasons, Nebius runs;
   cost-per-turn readout from telemetry.
6. **2:50–3:00 — the ask.** "Private by physics" closing line.

---

## 9. Risks & mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| **Vibro-braille learnability** — reading temporal braille on 6 motors is unproven at product level (research prototypes exist: V-Braille, HoliBraille, BrailleBand; none shipped) | **highest** | treat as a research question, not a certainty: week-2 bench tests with sighted blindfolded proxies first, then braille-reader sessions via community orgs (HKNC regional reps, NFB chapters); publish the protocol; Grade 1 only; make pacing/speed a first-class control. **No clinical or efficacy claims anywhere in the submission** — the claim is "a working prototype of a new channel," not therapy. |
| Motor choice — LRAs give crisp dots but need per-unit tuning; ERMs are mushy | medium | DRV2605L's effect library + auto-calibration handles LRA tuning; ERM fallback acceptable for MVP ⚠ |
| Omni audio-input payload format on TF unverified | medium | week-1 spike answers it; fallback = relay-side Whisper-class STT (§7 ladder) |
| Latency: capture + upload + Omni + playback must feel conversational | medium | budget ≈ clip length + 2–5 s (Route B anchor); keep clips short; stream text cells as they arrive if Omni streams |
| Board availability / N16R8 variant confusion | low | order week 1; the research note's board table lists 6 candidates |
| Battery life with WiFi bursts | low–medium | deep sleep between events; no continuous streaming; measure in week 5 |
| I²C address conflicts / wiring on small boards | low | all six DRV2605L share fixed 0x5A behind a TCA9548A mux at 0x70 (see [HARDWARE_BRINGUP.md](./HARDWARE_BRINGUP.md)); devkit bench first |
| Vocabulary crowding — every added non-letter pattern (now 7) shrinks the felt distance between signals and enlarges the week-6 confusion screen | medium | each new pattern declares its discriminating feature in the timing spec (e.g. `processing`'s 350 ms middle gap vs double-tap's 160); M1/M3 screens all of them; retire a pattern that confuses rather than tune it |
| Motor ability varies as much as sensory ability — chord input assumes dexterity many wearers lack (generalized from the early-years personal-care guidance) | medium | the 3-button fallback (read / stop / repeat) is load-bearing, not a footnote; chords are the upgrade path, never the floor |

**Challenge → exercise → fallback (ladders wired in advance):**

1. **Temporal braille learnability** (the #1 risk) — *exercise:* the week-2 bench protocol with sighted blindfolded proxies learning the 26 letters (letters/minute + error rate), then week-6 sessions with real braille readers via HKNC regional reps / NFB chapters. *Fallback ladder:* full reading → attention vocabulary + a 30-phrase fixed vocabulary ("yes/no/come/error/pills"): most of the value survives even if long-form temporal reading doesn't. **Gated: the protocol runs on the founder's call** — speced, not scheduled.
2. **Chord-input learnability** — chords assume braille literacy; not every deaf-blind person reads braille ⚠. *Exercise:* the same week-2 bench covers input. *Fallback:* a 3-button mode (read / stop / repeat) plus the mic for everything else — the device stays useful input-light.
3. **Battery** — *exercise:* week-5 overnight runtime measurement. *Fallback:* deep-sleep tuning first, then a charge-cradle routine (the pin lives on a bedside dock at night — which doubles as the morning-brief beat).
4. **Omni payload format** — *exercise:* the week-1 spike. *Fallback:* relay-side Whisper-class STT behind the same interface (§7 ladder); only the relay changes.
5. **Cost creep** — *exercise:* BOM re-checked at order time (week 1). *Fallback:* demo on a devkit + hand-wired motors; the enclosure is cosmetic, not functional.
6. **Caregiver-bridge scope creep** — *exercise:* none (it is a scope risk). *Fallback:* parked to v2 by default (§11); the push-to-friend's-phone flow demos the caregiver value without BLE.

**v2 ideas parked from early-years practice (Sense UK, via Insight — Sources):**

- **Per-contact people-marks** — objects of reference, generalized: an
  incoming message from a known contact plays that contact's short tactile
  mark before its content — caller ID generalized to touch. Needs the
  caregiver-bridge/phone integration; parked with it.
- **An on-device practice mode** — the §1 alphabet-span idea, repurposed:
  the device plays a letter, the wearer answers on the chord keys; sensory
  play with no instructions, and the gentlest way to learn the vocabulary
  itself.

---

## 10. Fine-tuning: what the Token Factory catalog adds

Token Factory's fine-tuning catalog (captured Sep 7, 2026:
[docs.tokenfactory.nebius.com/post-training/models](https://docs.tokenfactory.nebius.com/post-training/models))
supports **DeepSeek V3/V4, Gemma 4 (E2B/E4B/31B), GPT-OSS 20b/120b, the full
Qwen3 / 3.5 / 3.6 / Qwen2.5 range, and Llama 3.1/3.2/3.3** — LoRA or full
fine-tuning, context up to 131,072. **No Nemotron models are in the fine-tuning
catalog**, so the track's "≥1 NVIDIA open model" requirement is satisfied by
the *served* Nemotron pair (Omni + Nano), not a fine-tuned one — that's fine;
the requirement says "use", and two Nemotron models do the core work.

What the catalog does buy this project:

| Candidate | Why it fits this device | Role |
|---|---|---|
| **Qwen3-1.7B / 0.6B** (LoRA, Apache 2.0) | smallest trainable models; could be distilled into a **braille-output style model** — replies compressed to short, contraction-aware, dot-friendly sentences before they reach the motors | optional post-processing pass (v2, not MVP) |
| **Qwen3-4B / 8B** (LoRA) | same idea with more headroom; could also learn the wearer's own phrasing from their braille-chord history — personalization that lives in *our* weights on *our* account | personalization experiment |
| **Gemma-4-E2B/E4B** (full FT, Apache 2.0) | tiny dense instruct models; alternative distillation hosts | alternative, not chosen |
| Everything larger (DeepSeek, Qwen3-235B, GPT-OSS-120b, Llama-70B) | no role: the device needs short replies, not big reasoning; routing already covers hard turns via Nemotron Super | none |

**Honest assessment: fine-tuning is a v2 lever, not MVP scope.** The MVP's
bottleneck is the haptic channel, not model quality — prompt-level "answer in
≤6 short sentences" costs nothing and ships in week 3. But the catalog makes
a credible stretch story: a LoRA-tuned small model that compresses replies
into braille-friendly phrasing (and optionally learns the wearer's style)
is a genuine Technological-Implementation beat, it runs as an occasional
Serverless Job (fits the credit envelope), and the fine-tuned weights are
*ours* — which doubles as a data-control argument for the Secure story.

## 11. Open questions (verify before scoping)

- [ ] **Token Factory Omni audio input:** exact payload format (base64 audio
      in message content vs file upload vs both) and any context-length or
      audio-length limits on the TF endpoint. The vLLM blog confirms the
      model takes audio; TF's serving format is the spike's first question.
- [ ] Omni pricing/context on TF (third-party trackers say ~$0.06/$0.24 per
      1M tokens, 66k context ⚠ — verify on the TF model page).
- [ ] LRA vs ERM for braille dot legibility — needs a bench comparison in
      week 2 (crispness vs cost vs driver complexity).
- [ ] Grade 2 contraction scope: defer entirely, or a small set of common
      contractions? Decide with braille readers in week 6.
- [ ] Reading-speed target for temporal braille (cells/second) — literature
      on vibro-braille is thin; set from week-2/6 measurements, not assumption.
- [ ] Board revision specifics: battery charge IC, mic model, key placement
      ergonomics on a wrist form factor (cells flagged ⚠ in the research note).
- [ ] Whether BLE pairing to a phone (for caregiver bridge / setup) is worth
      MVP scope — parked unless week 5 goes fast.
- [ ] If the §10 distillation path is pursued: whether fine-tuned Qwen
      adapters can be *served* on Token Factory (dedicated endpoint) or only
      run as batch Jobs — the Llama 3.3 70B row notes "deployment only via
      Dedicated endpoints", which hints adapter serving is possible but is
      not confirmed for LoRA adapters.
- [ ] **Naming validation (week 6):** does the Z-I-V mark read as *identity*, distinct from message content, or does it need a non-letter signature rhythm? And does the word "Ziv" survive community contact, or do the braille readers rename the device? Name marks are given by communities, not founders — the submission ships under a working title by design; fallback is a pure-rhythm mark that encodes no letters. Session script: [NAMING_VALIDATION_PROTOCOL.md](./NAMING_VALIDATION_PROTOCOL.md) — 45 minutes: teach, measure M1–M4, rename.
- [ ] **Braille literacy of the target wearers:** what share of the target population reads braille ⚠, and does that reshape the input mix (chords vs 3-button vs caregiver relay)? Shapes the week-6 usability pass.

---

## 12. Founder pitch (the short version)

Two million Americans live with combined hearing and vision loss; for the ~45–70k at the deaf-blind core, there is no product that tells them what is happening and lets them answer. Braille displays cost $1,500–$12,000 and have no microphone and no agent; braille keyboards are input-only; the research world has played braille through phone vibration for 15 years and shipped nothing — the missing piece was a brain that could hear. That piece now costs fractions of a cent per turn: **Nemotron-3-Nano-Omni on Nebius Token Factory** takes audio in natively, and a **$5 haptic driver** speaks braille. **Ziv** (working title) is a ~$40 wrist pin — six motors in a braille layout, six chord keys, one mic — whose output channel is *private by physics*: nothing to overhear, nothing to glance at. It hears for people who can't hear and speaks braille on their skin, and it stays on when they're away — reminders arrive as rhythm, not as notifications they would never see. Its interaction rules are borrowed from the best practice that serves this population from birth (Sense UK's early-years guidance): every event is announced before it happens, ends with a felt close, and never makes the wearer wait in silence. We have already shipped one agent on this exact NVIDIA/Nebius stack (SkillForge: natural language → costed robot skill pipelines, 86 hermetic tests, live end-to-end); Ziv is the second, pointed at the population nobody else is building for.

*This section feeds the Devpost draft ([DEVPOST_HAPTIC.md](../DEVPOST_HAPTIC.md)) and the video's opening and closing lines. It is a pitch, not a claim set: every number traces to §2 or the research note, and §9's no-clinical-claims rule applies.*

---

## Sources

- Model: [Nemotron-3-Nano-Omni on Nebius Token Factory](https://nebius.com/services/token-factory/nemotron) · [TF cookbook model list](https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/README.md) · [TF announcement (Apr 28, 2026)](https://x.com/nebiustf/status/2049178914962989203) · [vLLM blog: serving Nemotron 3 Nano Omni — audio input modality](https://vllm.ai/blog/2026-04-28-nemotron-omni) · [model card](https://build.nvidia.com/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning/modelcard)
- Haptic driver: [Adafruit DRV2605L (2305)](https://www.adafruit.com/product/2305) · [SparkFun hook-up guide](https://learn.sparkfun.com/tutorials/haptic-motor-driver-hook-up-guide/all) · [esp-cpp DRV2605 driver](https://esp-cpp.github.io/espp/haptics/drv2605.html)
- Vibro-braille prior art: [V-Braille (mobile-phone haptic braille)](https://dl.acm.org/doi/10.1145/1878833.1878866) · [HoliBraille (W4A '15)](http://web.tecnico.ulisboa.pt/hugo.nicolau/publications/2015/Nicolau-W4A-2015.pdf) · [BrailleBand](https://www.semanticscholar.org/paper/BrailleBand%3A-Blind-support-haptic-wearable-band-for-Savindu-Achintha/b1fc667ca7f2cbbbaf412b75f0cbc6a0bdb3fa66) · [FeelU (Gemma 3n hackathon write-up)](https://www.kaggle.com/competitions/google-gemma-3n-hackathon/writeups/feelu-is-a-mobile-assistant-for-deaf-blind-individ) · [wearables for the deaf-blind community (review, Feb 2025)](https://nelowvision.com/exploring-wearable-technologies-for-the-deaf-blind-community/)
- Braille display pricing: [Perkins — low-cost refreshable braille (~$320 potential)](https://www.perkins.org/a-low-cost-revolution-in-refreshable-braille/) · [Hackaday — 40-cell $4k–6k / 80-cell $8k–12k](https://hackaday.io/project/191181-electromechanical-refreshable-braille-module) · [ScienceDirect review — ≈$35/cell ≈ $4.38/dot](https://www.sciencedirect.com/science/article/pii/S0141938225001702) · [Helen Keller — five-display comparison $1,499–$3,695](https://www.helenkeller.org/40-cells-to-empowerment-a-comparison-of-five-braille-displays-to-fortify-your-success-in-2023/)
- Braille keyboard: [Hable One — product](https://www.iamhable.com/en-am/products/hable-one-keyboard) · [NFB review — $350](https://nfb.org/blog/hable-one-quality-braille-keyboard-your-smartphone)
- Population: [HKNC](https://www.helenkeller.org/hknc/) · [HKNC ACS 2022 analysis](https://www.helenkeller.org/american-community-survey-acs-2022-data-on-people-who-are-deafblind-2024/) · [2026 DeafBlind Awareness Week — 2.4M with combined loss](https://www.helenkeller.org/2026-deafblind-awareness-week-proclamations/) · [Wikipedia — ~70,000](https://en.wikipedia.org/wiki/Helen_Keller_National_Center_for_Deaf-Blind_Youths_and_Adults)
- Fine-tuning catalog: [Token Factory post-training models](https://docs.tokenfactory.nebius.com/post-training/models) (captured Sep 7, 2026)
- Naming / DeafBlind name signs: [Protactile Language, Modality, and Community — Annual Review of Linguistics](https://www.annualreviews.org/content/journals/10.1146/annurev-linguistics-011724-121536) · [MN DOE — tactile name cues vs name signs](https://education.mn.gov/mdeprod/idcplg?IdcService=GET_FILE&dDocName=PROD034266&RevisionSelectionMethod=latestReleased&Rendition=primary) · [interpretereducation.org — ProTactile module](http://www.interpretereducation.org/teaching/classroom-modules/deafblind/instructor-guide/)
- Early-years practice (invariants + v2 ideas, plan §4/§9): [How to support a child with deafblindness in their early years — Sense UK via Insight](https://insightdeafblind.org/resource/how-to-support-a-child-with-deafblindness-in-their-early-years) (Jan 2025) — consistency and anticipation, cues marking start and end, taking time, wearer control; consulted Sep 12, 2026
- Naming collisions: [RAZ Mobility](https://www.razmobility.com/) — assistive tech for blind/low-vision users ([Verizon distribution of the RAZ Memory Cell Phone, Jul 2025](https://www.razmobility.com/news/verizon-starts-selling-the-raz-memory-cell-phone-to-help-seniors-and-caregivers/)) · [National Press Club — Robert Felgar speaker bio (RAZ founder; ex-Odin Mobile founder)](https://nationalpress.org/speaker/robert-felgar/) · [Trademarkia — TOV Furniture marks](https://www.trademarkia.com/owners/tov-furniture) · [Neosensory — Buzz/Duo haptic wristband for deaf users](https://neosensory.com/) · [Viz.ai — AI care coordination](https://www.viz.ai/) — ten names screened Sep 7, 2026; screening only, not legal clearance
- Carried over: [MIMICLAW_PIPIN_RESEARCH.md](./MIMICLAW_PIPIN_RESEARCH.md) (boards, Nebius API surface, route anchors) · [CAPABILITIES.md](./CAPABILITIES.md) (track text, criteria, stack)

## How this doc is used

1. Week 1: order hardware (§3 BOM), run the spike (§7), answer the Omni
   payload question (§11).
2. Each milestone updates this doc's status only if scope changes — progress
   logs live in CHANGELOG.md per repo convention.
3. The §6 mapping and the §12 pitch feed the Devpost draft
   ([DEVPOST_HAPTIC.md](../DEVPOST_HAPTIC.md)); the §8 script is the video
   storyboard.
4. Any claim that can't be sourced stays in §11 or keeps its ⚠ — nothing
   graduates into the Devpost text unverified.
