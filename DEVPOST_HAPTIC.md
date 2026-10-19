# Devpost Submission — Ziv (DRAFT)

> **Track: Best Apps and Agents.** Copy-paste the sections into the Devpost project page when the submission goes live. The project ships under the working title **Ziv** — final naming authority rests with the deaf-blind community (validation sessions are planned, not yet held). Whatever is deferred is named the *next revision* in the same sentence that claims what is built; nothing deferred is claimed for this submission. House rule from the plan: **no clinical or efficacy claims** — the claim is "a working prototype of a new channel," not therapy.

---

## Project Name

Ziv *(working title — the final name is validated with, or given by, the deaf-blind community)*

## Tagline

Hears for people who can't hear, speaks braille on their skin.

## Short Description (one-liner)

Ziv is a phone-based haptic message channel for deaf-blind users: the wearer's phone plays what arrives as braille patterns a deafblind wearer can feel — no screen, no sound. The demo runs the relay's keyless stub path, so the turn plays without a live provider call. (AI-composed replies are not part of this submission.)

---

## Description (paste into "Description" field)

### The Problem

~2.4 million Americans live with combined hearing and vision loss (~45–70k at the deaf-blind core), and almost nothing is built for them:

- **Refreshable braille displays cost $1,500–$12,000** — and have no microphone, no agent, no always-on awareness.
- **Braille keyboards (Hable One, $239–$349) are input-only** — no output channel, no brain.
- **Research prototypes** have played braille through phone vibration for 15 years (V-Braille, HoliBraille, BrailleBand) — prototypes, never products: no brain that could *hear* them, no path to market.
- **"AI pins" serve eyes and ears** — useless to someone who cannot see or hear the reply.

The gap: **no existing product pairs a haptic braille output channel with an AI that can hear.**

### Our Solution

Ziv (working title) is a phone-based haptic message channel for deaf-blind users: the phone's vibration motor plays the words that arrive as braille patterns on the wearer's skin — no screen, no sound, nothing for the room to see or overhear. The demo runs the relay's keyless stub path, so the turn plays without a live provider call.

1. **Speaks braille.** The text is rendered as Grade-1 braille and played as *temporal braille* — one letter at a time as vibration dot-patterns, with the wearer's pacing preference applied (a first-class, API-set control, clamped into the spec's envelope).
2. **Acts while they're away.** Scheduled reminders fire unprompted as full haptic turns — the always-on assistant beat, proven by the relay's scheduler. The schedule is durable like the inbox (atomic JSON, corrupt-tolerant, capped): a reminder promised for tomorrow survives a restart tonight.
3. **Private by physics.** Nothing to overhear, nothing to glance at: a message vibrates on the phone and is invisible to the room. The mic is push-to-talk (not always-on listening).
4. **A cheaper device class against a more expensive one.** The wrist hardware (held as asset, not part of this submission) is ~$40 BOM — against $1,500–$12,000 refreshable braille displays.

### Why It Matters

- **A ~$40 device against a $1,500–$12,000 device class** (wrist BOM, next revision — this submission runs the same channel on a phone), for a population no mass-market product is built for.
- **Dignity, not just access:** for people who already depend on others for information, the device that tells you things *without telling the room* is a different kind of assistant.
- **The channel doubles as the identity:** the generated timing spec defines a haptic name mark — Z-I-V spelled in vibro-braille (heavy-light-heavy) — and the relay plays it today: every scheduled reminder opens as its own turn with the mark spelled in cells, the reminder's triple-pulse tail, then a breath before the content. It is a haptic "name mark," the same way DeafBlind communities identify people by tactile signs rather than descriptions.

### Grounded in Deafblind Practice, Not Just Built for Deafblind People

The interaction rules are borrowed from the field's own guidance. Sense UK's early-years resource for parents of children with deafblindness (published via Insight, Jan 2025) opens with the problem this device exists to solve: a child with deafblindness receives little information from the world, and what arrives "may be inconsistent and distorted" — so events must be cued before they happen, routines must be consistent, waiting must be patient, and the child must stay in control. What serves that child serves Ziv's wearer: an adult with the same sensory reality deserves a device that holds itself to the same rules. They are written into the plan as four **interaction invariants**:

| Invariant | What it forbids |
|---|---|
| 1. No content without a kind cue first | a buzz that says "something" but not "what kind" |
| 2. Cues mark the start *and* the end of an event | a message that just stops |
| 3. Waiting is legible | dead air during a model round-trip |
| 4. Queue, don't interrupt | an announcement barging into playback |

Invariants 2–3 demanded two haptic patterns that did not exist, so we built them into the timing spec (v3) — the single JSON the phone feel-tool and the wrist firmware are both generated from, so they play identical patterns by construction — and exercised them in the hermetic test suite:

- **Processing** — two ticks whose *middle gap is the signal*: 350 ms of silence where the "new message" pattern has 160 ms. An ellipsis: your request is being handled, content follows. Latency may be slow, never silent.
- **End of message** — four ticks descending (200→140→90→50 ms), the exact mirror of the spec's ramp-up ascent (50→90→140→200). Until it plays, the silence after a message's last letter was indistinguishable from the pause before the next one.

Invariant 4 became the relay's first real behavior, proven in code: **queue, don't interrupt.** If a message arrives while the wearer is mid-playback, it may announce itself (the "new message" cue) but its content waits; when the event closes — the end-of-message close has played — the queue releases oldest-first, and every queued message still opens with its kind cue (invariant 1 holds for queued content too). The wearer, not the sender, decides when the next message begins.

*Design rules adopted from published practice, not clinical claims: the guidance informs interaction design; nothing here asserts therapeutic or developmental outcomes — the plan's no-clinical-claims rule applies to every line of this submission.*

### Competition

The nearest assistive wearables each substitute one missing sense — and pay the user back in the other one. Five products closest to Ziv:

| Company | What they ship | The gap for a deaf-blind wearer |
|---|---|---|
| [Neosensory](https://neosensory.com/) (Buzz / Duo) | 4-motor haptic wristband translating ambient sound into vibration — sound awareness for deaf/HoH users and tinnitus therapy; shipping since 2019 | Awareness, not language: abstract vibration patterns — no braille, no speech understanding, no input, no agent. Validates that haptic wrist wearables sell. |
| [RAZ Mobility](https://www.razmobility.com/) | Smartphones for blind/low-vision and senior users — RAZ Memory Cell Phone (sold by Verizon since Jul 2025), SmartVision 3 | Every output path is spoken audio or a screen — a deaf-blind wearer is the one customer they cannot serve. |
| [OrCam MyEye](https://www.orcam.com/) | AI camera clipped to glasses; reads text and recognizes faces, spoken aloud via bone conduction ($2,450–$4,500) | Best-in-class vision substitution with a *spoken* output — unusable for a deaf wearer; no haptic channel, no conversation, no input keys. |
| [Dot Inc.](https://www.dotincorp.com/) | The closest hardware cousin: Dot Watch put a 4-cell braille display on a wrist (first generation discontinued Jun 2018); today's line is multi-line braille and tactile-graphics pads | A *display*, not an agent: it mirrors phone notifications — no microphone, no hearing, no AI — and static 4-cell pins are slow to read. |
| [Hable One](https://www.iamhable.com/) | $239–$349 six-key braille keyboard for smartphones | Input in the wearer's own literacy — but the reply comes back as the phone's *spoken* screen reader: no output channel of its own, no haptics, no brain. |

The pattern: **spoken output (OrCam, RAZ Mobility, Hable's screen reader) excludes deaf users; notification mirroring (Dot) excludes agency; abstract vibration (Neosensory) excludes language.** None of the five pairs haptic braille with a device that can hear and act. What only Ziv combines:

- **Thinks for you** — an NVIDIA open model on Nebius Token Factory composes the line a wrist reads. You set an intent while busy; the reminder fires on its own and the phone spells what the model wrote.
- **Speaks their literacy** — temporal braille on the skin; no pins, no screen, no audio.
- **Acts while they're away** — scheduled relay jobs; no competitor ships an agent at all.
- **At a ~$40 BOM (wrist hardware, next revision)** — against $239–$4,500+ across the table.

None of the five is the enemy — each validates one pillar. The combination is the submission.

*Sourcing: Dot Watch discontinuation and 4-cell detail — [AFB review via Dot Inc. news](https://www.dotincorp.com/en/news/27); OrCam pricing — [dealer listings](https://lowvisionsource.com/product-category/lowvisionwearabledevices-com/orcam/) and [AFB Accessworld (MyEye 2.0 at $4,500)](https://afb.org/aw/19/8/15066).*

---

## Key Technologies Used

- **NVIDIA Nemotron-3-Nano-30B-A3B** — text in → the line a wrist reads; the model behind the agent path this demo runs, on Nebius Token Factory
- **Nebius Token Factory** — inference for the agent model: one OpenAI-compatible endpoint, one key, no GPU to provision
- **FastAPI + WebSockets** — the thin relay: WS gateway, optional shared-token auth, per-wearer memory files, capped inbox, scheduler loop
- **The phone Vibration API** — the wearer feels each message (Android Chrome); the wrist hardware (ESP32-S3 + DRV2605L + 6 LRA motors) is the next revision
- **ESP32-S3 N16R8 + DRV2605L + 6 LRA motors** — the next revision's hardware (~$40 BOM); the firmware is written against it (`firmware/haptic_out/`), boards are not shipped in this prototype

---

## How We Built It

### Architecture

```
[phone: Android Chrome PWA]
  mic ──► MediaRecorder (push-to-talk only) ──► base64 audio
  Vibration API ◄── vibro-braille + attention patterns
        │  text JSON frames over WebSocket; audio posted base64 over HTTP
        ▼
[relay — thin FastAPI service]
  WS gateway (optional shared-token auth; open on the LAN by default)
  intent → Nemotron-3-Nano-30B-A3B on Nebius (writes the line the wrist spells)  [wire source: text_live]
  memory: per-wearer memory files + capped inbox
  scheduler: a poll loop fires reminders while nobody is "chatting" (schedule durable like the inbox)
        ▼
[Nebius Token Factory — NVIDIA open models]
  Nemotron-3-Nano-30B-A3B  (text in → the line a wrist reads)
```

### Design Decisions

1. **No speaker, by design.** The wearer can't hear one — and removing it deletes echo cancellation, wake word, and the TTS pipeline: the entire hard-problem list of voice wearables. The output channel is a vibration motor.
2. **Temporal braille, Grade 1.** The same alphabet braille readers already know, played as rhythm instead of shown as pins. Word-shape corner cues (space, capital, number sign) are planned — the prototype plays plain Grade-1 letters (a–z), one cell at a time; pacing is the first-class control (per-wearer, clamped into the spec envelope).
3. **A haptic name mark.** The timing spec defines the mark — Z-I-V spelled in vibro-braille (Z = four motors, heavy; I = two motors, light; V = four motors, heavy — the mark ends decisive, the same heavy-light-heavy arc "Raz" would have played) — and the phone's timing bootstrap ships it (`/api/ziv/timing`); the relay plays it as the prefix of unsolicited turns — scheduled reminders open with the mark spelled in cells, the kind's triple-pulse tail, and a breath before the content. Grounded in how DeafBlind communities use tactile name signs: the name is a felt pattern, not a label.
4. **Push-to-talk mic (this prototype).** Audio capture only on the mic button — not always-on listening. The wrist hardware's hardware-gated mic (ESP32 pin) is the next revision.
5. **The timing spec is generated, never hand-edited.** `docs/haptic-timing.json` is the single source of truth; seven consumers are generated from it (phone feel-tool + firmware header + Python consumer + ladder tables), so the phone and the wrist firmware play identical patterns by construction. The drift guard fails on any hand edit.
6. **Durable wearer state.** Memory files + a persistent, capped inbox: a message arriving with no band attached is stored, not dropped, and delivered on the next attach as a self-naming turn — the Z-I-V mark first, the stored content after. Mark-after-play: redelivery, never loss.
7. **Honest scope for the hackathon.** This submission is a phone-based prototype to the Best Apps and Agents track. The full private, wearer-controlled personal AI system (wrist device with hardware-gated mic + wearer-hosted relay) is the next revision. The haptic output is private by physics; the mic is push-to-talk; the relay runs on our infrastructure, not the wearer's, in this prototype.

---

## Inspiration

**Who we built this for.** ~2.4 million Americans live with combined hearing and vision loss (~45–70k at the deaf-blind core), and almost nothing is built for them. Refreshable braille displays cost $1,500–$12,000 and have no microphone, no agent, no always-on awareness; braille keyboards ($239–$349) are input-only; existing haptic wristbands (Neosensory, Dot) give awareness or pins, not language with a brain. The gap that motivated this project is the gap no product currently fills: **a haptic braille output channel paired with an AI that can hear**.

**Where the interaction rules come from.** We did not invent the interaction design by intuition. They come from published early-years deafblind practice — Sense UK's guidance for parents of children with deafblindness (via Insight, Jan 2025), which starts with the exact problem this device exists to solve: a person with deafblindness receives little information from the world, and what does arrive "may be inconsistent and distorted." So events must be cued before they happen, routines must be consistent, waiting must be patient, and the person must stay in control. What serves that child serves Ziv's wearer: an adult with the same sensory reality deserves a device that holds itself to the same rules. Those rules became the four interaction invariants in the plan, and two of them demanded patterns that did not exist yet — which is why the timing spec gained a "working" cue and an end-of-message close.

**Why a phone for the hackathon.** The wrist device (ESP32-S3 + DRV2605L + 6 LRA motors + 6 chord keys + hardware-gated mic, ~$40 BOM) is the real product shape — but it is not on hardware for this submission. For the hackathon we built the *constructed channel* first: a phone that plays vibro-braille through its vibration motor using the same timing the firmware would use, connected to a thin relay that calls an NVIDIA open model on Nebius Token Factory. The phone is a dev band, not a compromise we pretend is the product. That framing is deliberate: we would rather submit the honest thing than a wrist-shaped fiction.

**A note on the user.** Deaf-blind is the use case that proves the channel, not the only one. The same private-by-physics output — vibration felt by the wearer and invisible to everyone else — is useful any time a reply should be private, glance-free, and sound-free: hands-busy or noisy environments, shared spaces, anywhere a screen and a speaker would leak the message to the room. The deaf-blind companion is the sharpest version of that claim; the phone is what made it buildable in the time we had.

---

## What it does

Ziv (working title) is a private, always-on AI companion for deaf-blind users — always-on is the relay's property: it schedules, composes, and stores while the wearer is away, and the phone renders each event while its page is open. A reminder you set while busy is an *intent*, not a finished sentence; when it fires, **Nemotron-3-Nano-30B-A3B on Nebius Token Factory** writes the line, and what it wrote plays as braille vibration patterns on the wearer's phone — no screen, no sound, nothing for the room to see or overhear. The wearer can reply by text, and a scheduled relay job delivers reminders unprompted.

**This submission is the built core of Ziv, demoed as a phone-based prototype for the hackathon.** The wrist device (hardware-gated mic + chord input + wearer-hosted relay) is the next revision, scoped honestly rather than claimed.

Concretely, the prototype does this now:

- **A demo turn that plays without a live provider call.** The relay's keyless stub path hands a transcript to the relay directly, so the turn plays on the phone without a live provider call — cue, processing ticks, braille cells, felt close, queue release.
- **Speaks braille.** The text is rendered as Grade-1 braille and played as *temporal braille* — one letter at a time as vibration dot-patterns, with the wearer's pacing preference applied (a first-class, API-set control, clamped into the spec's envelope).
- **Acts while they're away.** A scheduled relay job buzzes a reminder unprompted — the always-on assistant beat, proven live: the scheduler loop fires it, and `/api/ziv/ready` + health telemetry record it.
- **Private by physics.** Nothing to overhear, nothing to glance at: a message vibrates on the phone and is invisible to the room. The mic is push-to-talk (not always-on listening).
- **Stays polite to the wearer.** If a message arrives while the wearer is already feeling one, it only announces itself and queues its content — it never barges in. The wearer releases the queue by closing the message (the same end-of-message close they feel). The phone stays silent for a refused message; the sender is told no.
- **Remembers the wearer.** Per-wearer memory files (atomic JSON, corrupt-file recovery surfaced in health — never silently swallowed) plus a capped persistent inbox: a message that arrives with no band attached is stored, not dropped, and replayed on the next attach as a self-naming turn — mark first, content after.
- **Boots its timing from one source.** The phone's vibrate patterns come from `GET /api/ziv/timing` — the serialized generated module — so the phone and the feel-tool play identical patterns by construction, not by convention.

**A scene from the demo.** A sighted helper hands a transcript to the relay through the keyless stub path, and the phone, face-down and silenced, taps the arrival cue, ticks while the relay works, spells the message cell by cell, and closes. What was said appears on the wearer's phone as vibro-braille. The wearer replies by text. The helper's side is shown honestly: the reply is visible as text in the relay's wire log (there is no separate helper client yet), and because there is no speaker in the room, the helper does not hear it. The demo shows the friend's side rather than leaving it to the room to guess.

---

## How we built it

### Architecture

```
[phone: Android Chrome PWA]
  mic ──► MediaRecorder (push-to-talk only) ──► base64 audio
  Vibration API ◄── vibro-braille + attention patterns
        │  text JSON frames over WebSocket; audio posted base64 over HTTP
        ▼
[relay — thin FastAPI service]
  WS gateway (optional shared-token auth; open on the LAN by default)
  intent → Nemotron-3-Nano-30B-A3B on Nebius (writes the line the wrist spells)  [wire source: text_live]
  text  → the transcript runs the relay's one turn pipeline (same code path as a typed message)
  memory: per-wearer memory files + capped inbox
  scheduler: a poll loop fires reminders while nobody is "chatting" (schedule durable like the inbox)
        ▼
[Nebius Token Factory — NVIDIA open models]
  Nemotron-3-Nano-30B-A3B  (text in → the line a wrist reads)
```

The phone is the visible output channel for the hackathon; the wrist firmware is generated from the same timing source the phone boots from, but it is not on hardware for this submission.

### Design decisions

1. **No speaker, by design.** The wearer cannot hear one — and removing it deletes echo cancellation, wake word, and the TTS pipeline: the entire hard-problem list of voice wearables. The output channel is a vibration motor.
2. **Temporal braille, Grade 1.** The same alphabet braille readers already know, played as rhythm instead of shown as pins. Word-shape corner cues (space, capital, number sign) are planned — the prototype plays plain Grade-1 letters (a–z), one cell at a time; pacing is the first-class control (per-wearer, clamped into the spec envelope).
3. **A haptic name mark.** The timing spec defines the mark — Z-I-V spelled in vibro-braille (Z = four motors, heavy; I = two motors, light; V = four motors, heavy — the mark ends decisive, the same heavy-light-heavy arc "Raz" would have played) — and the phone's timing bootstrap ships it (`/api/ziv/timing`); the relay plays it as the prefix of unsolicited turns — scheduled reminders open with the mark spelled in cells, the kind's triple-pulse tail, and a breath before the content. Grounded in how DeafBlind communities use tactile name signs: the name is a felt pattern, not a label.
4. **Push-to-talk mic (this prototype).** Audio capture only on the mic button — not always-on listening. The wrist hardware's hardware-gated mic (ESP32 pin) is the next revision.
5. **The timing spec is generated, never hand-edited.** `docs/haptic-timing.json` is the single source of truth; seven consumers are generated from it (phone feel-tool + firmware header + Python consumer + ladder tables), so the phone and the wrist firmware play identical patterns by construction. A drift guard fails on any hand edit to a generated block.
6. **Durable wearer state.** Memory files + a persistent, capped inbox: a message arriving with no band attached is stored, not dropped, and delivered on the next attach as a self-naming turn — the Z-I-V mark first, the stored content after. Mark-after-play: redelivery, never loss.
7. **Queue, don't interrupt — enforced as a relay behavior, not a UI hint.** `MessageGate` is the seam's serialization point: while content plays, an incoming message gets its attention cue only and queues its text; the wearer releases the queue by closing the event, and drained messages play FIFO, each opening with its kind cue. The close frame that frees the channel is marked on the wire (`free: true`), so the client's auto-redial fires on the frame the wearer feels — not on a timing guess.
8. **Honest scope for the hackathon.** This submission is a phone-based prototype to the Best Apps and Agents track. The full private, wearer-controlled personal AI system (wrist device with hardware-gated mic + wearer-hosted relay) is the next revision. The haptic output is private by physics; the mic is push-to-talk; the relay runs on our infrastructure, not the wearer's, in this prototype.

---

## Challenges we ran into

1. **Naming for the audience.** "Tact" was too literal (withdrawn); "Raz" was a perfect haptic mark but its word collided with RAZ Mobility, an established assistive-tech company for blind users. Ten names screened in total — every sensory-feeling word collided with an assistive-tech incumbent. The trail produced the rule: the mark is the name, the word is a handle chosen by cost, not meaning. The submission ships as "Ziv (working title)" — final naming authority rests with the deaf-blind community.
2. **Rendering braille as rhythm.** cell → dot bitmask → vibration waveform timing, with pacing as the first-class control.
3. **Keeping the always-on economics honest.** The relay runs on our infrastructure, not the wearer's (model inference runs on Nebius Token Factory); the wearer does not yet self-host or control their data — that is the next revision, scoped honestly rather than claimed.
4. **Avoiding voice-wearable hard problems entirely by removing the speaker** (no AEC, no wake word, no TTS in the critical path).
5. **Finding the model id that is actually deployed.** An id read off a model card is not an id the account serves — it earns a 404. The honest source is the account's own `GET /v1/models`, which is where the relay's model comes from; a wrong guess costs one round-trip and answers itself in one line.
6. **Grounding the interaction design in practice rather than intuition.** Adopting Sense UK's early-years deafblind guidance (via Insight) as design law exposed two missing patterns — a "working" cue and an end-of-message close — and produced the queue-don't-interrupt rule. The haptic channel is serial, so courtesy has to be architectural.
7. **Making the demo's conversation honest without a speaker.** A conversation where one party hears and the other feels is the demo's core moment — but a room that only sees a wearer feeling something and a helper speaking can wrongly assume the helper heard a spoken reply. The fix is to show the friend's side (the reply as text in the relay's wire log — there is no separate helper client yet) rather than leaving it to the room to guess. Spoken replies are v2 (TTS), not this submission.

---

## Accomplishments that we're proud of

- **A working channel the wearer can feel on a phone.** A message arrives, the phone plays the kind cue, the processing ticks while the relay works, the braille cells, the end-of-message close — the whole turn journey, on hardware everyone already owns, using the same timing the wrist would use. This is not a mock of the channel; it is the channel, on a dev band.
- **A single timing source that the phone and the wrist share by construction.** One JSON (`docs/haptic-timing.json`) generates the phone feel-tool, the firmware header, the Python consumer, and the ladder doc's demo table; a drift guard refuses any hand edit to a generated block. If the phone and the wrist ever play different patterns, the submission is untrustworthy — so we made that impossible by derivation, not by hoping.
- **A relay that enforces the right behavior by default.** Queue-don't-interrupt, processing-while-waiting, end-of-message close before release, mark-after-play redelivery — these are the rules early-years deafblind practice says a device for this population must hold, and we made them real in the relay seam and the turn timeline, with a threaded concurrency guard so concurrent arrivals never lose or duplicate a message.
- **A refusal path that is loud and sender-visible.** A full queue answers 429 with a reason; the phone shows a plain-language "wrist is busy" note and keeps the drafted text; a live queue badge shows how close the queue is to refusing; health surfaces the rejection count and rate so the operator can see the 429s instead of only the sender feeling them.
- **A model inside the channel, not beside it.** The hearing layer is designed and held as asset; what the demo proves is the other direction — a live NVIDIA open model on Nebius Token Factory composing the line a wrist reads, through the relay's one turn pipeline.
- **Honest scope.** We could have written "always-on AI companion wrist device" and let the reader fill in the gaps. We did not. The built things are proven; the wrist hardware, chord input, hardware-gated mic, and wearer-hosted relay are scoped and de-risked, and the submission says so in the same sentence that claims what is built.

---

## What We Learned

- **The channel is the product, not the form factor.** A vibration motor that plays braille is the same channel on a phone or a wrist. That is what made this buildable for the hackathon: we did not need the wrist to build the thing that matters.
- **Honesty is a credibility strategy, not a modesty strategy.** The submission is stronger when it says exactly what is built and exactly what is deferred, because a reviewer can hold the real claim in one sentence — and because the honest claim is already impressive.
- **The hardest problems went away by removal, not by solving.** Removing the speaker removed echo cancellation, wake word, and TTS from the critical path. That is a real design move, not a shortcut — it is the reason this is buildable at all.
- **Courtesy has to be architectural when the channel is serial.** A vibration channel cannot interrupt without confusing the wearer, so queue-don't-interrupt became a relay behavior, not a UI preference.
- **A conversation demo can lie by implication.** With no speaker in the room, the friend's reply is text in the relay log — and the demo has to show that, or a reviewer will assume the wrong thing. We learned to make the missing side visible rather than silent.

*(For the build plan, milestones, and open questions, see [docs/HAPTIC_COMPANION_PLAN.md](docs/HAPTIC_COMPANION_PLAN.md) and [CHANGELOG.md](CHANGELOG.md).)*

---

## What's next for Ziv

**Next revision (after the hackathon):** the wrist device — ESP32-S3 + DRV2605L + 6 LRA motors, ~$40 BOM — with a hardware-gated mic and 6-key braille chord input, running the same relay protocol and the same generated timing source the phone uses now. The phone prototype already generates the firmware header from the same timing JSON the phone feels, so the wrist step is a bring-up, not a rebuild.

After the wrist lands:

1. **Hardware-gated mic** — the ESP32 pin; push-to-talk becomes a physical property, not a software choice.
2. **Wearer-hosted relay** — the wearer runs their own relay so their data is under their control (the honest answer to "private / data under your control").
3. **Spoken replies (v2)** — TTS on the relay, so the friend hears the wearer's answer.
4. **Grade 2 contractions** — 20–40% fewer cells per message, tuned with braille readers.
5. **Per-contact people-marks (v2)** — a known contact's own tactile cue before their message.
6. **On-device practice mode (v2)** — the device plays a letter, the wearer answers on the chords; sensory play with no instructions.

Open now (decision points, not promises):

- **Naming validation** with the deaf-blind community — does the Z-I-V mark read as identity, and does "Ziv" survive contact, or do the readers rename the device? The submission ships under working title by design; the mark is validated with, or given by, the community.
- **Vibro-braille learnability** is the #1 risk and is unproven at product level — the honest claim is "a working prototype of a new channel," not a proven reading method. The fallback ladder (attention vocabulary + 30-phrase set, then a 3-button read/stop/repeat mode) is specified in advance in the plan, so the project has a designed fallback even if long-form temporal reading does not.

---

## Devpost-Specific Answers

### What hackathon track are you in?

Best Apps and Agents Track

### What does your project do?

Ziv (working title) is a private, always-on AI companion for deaf-blind users — always-on is the relay's property (it schedules, composes, and stores while the wearer is away); the phone renders events while its page is open. A reminder you set while busy is composed by **Nemotron-3-Nano-30B-A3B on Nebius Token Factory**, and what the model wrote plays as braille vibration patterns on the wearer's phone — no screen, no sound, nothing for the room to see or overhear. This submission is the built core of Ziv, demoed on a phone. The wrist device (chord input + wearer-hosted relay) is held as asset, not claimed.

### What makes your project unique?

No existing product pairs a haptic braille output channel with a model that thinks for you behind it. Braille displays ($1,500–$12,000) don't speak; braille keyboards ($239–$349) don't either; existing haptic wristbands (Neosensory, Dot) give awareness or pins, not language with a brain. Ziv is built from the combination only this stack enables: an NVIDIA open model on Nebius Token Factory writing the line a wrist reads — and a phone's vibration motor that speaks braille. And the interaction design is grounded in the field's own guidance rather than intuition: four invariants adopted from early-years deafblind practice (Sense UK, via Insight), with the lifecycle patterns and the queue-don't-interrupt rule already enforced in code and tests.

The channel is the part that generalizes beyond the deaf-blind use case. The phone's vibration motor speaks braille for the wearer who cannot hear or see the reply; the same private-by-physics channel — vibration felt by the wearer and invisible to everyone else — is the reason the device works in any context where a reply should be private, glance-free, and sound-free: hands-busy or noisy environments, shared spaces, anywhere a screen and a speaker would leak the message to the room. The deaf-blind companion is the sharpest version of that claim; the phone is the dev band that makes it buildable for the hackathon.

### What challenges did you face?

1. **Naming for the audience:** "Tact" was too literal (withdrawn); "Raz" was a perfect haptic mark but its word collided with RAZ Mobility, an established assistive-tech company for blind users. Ten names screened in total — every sensory-feeling word collided with an assistive-tech incumbent. The trail produced the rule: the mark is the name, the word is a handle chosen by cost, not meaning. The submission ships as "Ziv (working title)" — final naming authority rests with the deaf-blind community.
2. **Rendering braille as rhythm:** cell → dot bitmask → vibration waveform timing, with pacing as the first-class control.
3. **Keeping the always-on economics honest:** the relay runs on our infrastructure, not the wearer's (model inference runs on Nebius Token Factory); the wearer does not yet self-host or control their data — that is the next revision, scoped honestly rather than claimed.
4. **Avoiding voice-wearable hard problems entirely by removing the speaker** (no AEC, no wake word, no TTS in the critical path).
5. **Finding the model id that is actually deployed.** An id read off a model card is not an id the account serves — it earns a 404. The honest source is the account's own `GET /v1/models`, which is where the relay's model comes from; a wrong guess costs one round-trip and answers itself in one line.
6. **Grounding the interaction design in practice rather than intuition:** adopting Sense UK's early-years deafblind guidance (via Insight) as design law exposed two missing patterns — a "working" cue and an end-of-message close — and produced the queue-don't-interrupt rule. The haptic channel is serial, so courtesy has to be architectural.

### What technologies did you use?

NVIDIA Nemotron-3-Nano-30B-A3B, Nebius Token Factory, FastAPI, WebSockets, Android Vibration API, ESP32-S3 (ESP-IDF, C), DRV2605L, LRA vibration motors.

---

## Demo Video Outline (≤3 min)

1. **0:00–0:20** — the gap: price cards ($4,000 display / $349 keyboard / ~$40 Ziv wrist BOM — held as asset; the demo band is a phone). Who it's for in one sentence.
2. **0:20–1:10** — the conversation: a friend hands a transcript to the relay through the keyless stub path, the phone plays braille, the wearer replies by text; relay log on screen. **Show the friend's side:** the reply is visible as text in the relay's wire log (there is no separate helper client yet) — there is no speaker in the room, so the friend does not hear it. The demo must not imply the friend heard a spoken reply.
3. **1:10–1:50** — the timing source: the spec is generated from one JSON; the drift guard proves the phone and the feel-tool share the same patterns. The demo beat plays cue, processing ticks, braille cells, felt close, queue release.
4. **1:50–2:30** — private by physics: a message vibrates on the phone, invisible to the room. Held as asset: the wrist device and the audio-in hearing layer. Show the always-on beat: a scheduled reminder buzzes unprompted, with the relay's ready/health telemetry as the proof.
5. **2:30–3:00** — the ask: "a new channel for people mass-market product ignores."

---

## Sources (every external claim, checkable)

The submission's external facts, with the sources a judge can open. The plan
(`docs/HAPTIC_COMPANION_PLAN.md`, §Sources) carries the full research trail.

- **"~2.4 million Americans live with combined hearing and vision loss"** —
  Helen Keller National Center, DeafBlind Awareness Week 2026
  ([helenkeller.org/dbaw2026](https://www.helenkeller.org/dbaw2026/)).
- **"~45–70k at the deaf-blind core"** — HKNC's data summaries: the classic
  ~45–50k estimate, ~70k per the HKNC summary on Wikipedia, and the HKNC's own
  ACS 2022 analysis
  ([helenkeller.org/hknc](https://www.helenkeller.org/hknc/)),
  ([ACS 2022 analysis](https://www.helenkeller.org/american-community-survey-acs-2022-data-on-people-who-are-deafblind-2024/)),
  ([Wikipedia summary](https://en.wikipedia.org/wiki/Helen_Keller_National_Center_for_Deaf-Blind_Youths_and_Adults)).
- **"Refreshable braille displays ($1,500–$12,000)"** — the low end from
  Helen Keller Services' five-display comparison, $1,499–$3,695 for 40-cell
  units ([helenkeller.org](https://www.helenkeller.org/40-cells-to-empowerment-a-comparison-of-five-braille-displays-to-fortify-your-success-in-2023/));
  the high end from Hackaday's 80-cell build analysis
  ([hackaday.io](https://hackaday.io/project/191181-electromechanical-refreshable-braille-module))
  and the ≈$35/cell economics in a ScienceDirect review
  ([sciencedirect.com](https://www.sciencedirect.com/science/article/pii/S0141938225001702)).
- **"Braille keyboards ($239–$349) are input-only"** — Hable One's product
  page ([iamhable.com](https://www.iamhable.com/en-am/products/hable-one-keyboard))
  and the NFB's review at $350
  ([nfb.org](https://nfb.org/blog/hable-one-quality-braille-keyboard-your-smartphone)).
- **Early-years practice (cues mark start and end, waiting stays legible,
  the wearer releases)** — "How to support a child with deafblindness in
  their early years," created by **Sense UK**, published by **Insight**
  (Jan 2025)
  ([insightdeafblind.org](https://insightdeafblind.org/resource/how-to-support-a-child-with-deafblindness-in-their-early-years)).
- **The practice's reach ("Sense UK in Nepal")** — the same organisation's
  global sister charity, **Sense International**, runs deafblindness
  programmes in Nepal (and seven other countries), including educator
  training and day centres
  ([senseinternational.org.uk](https://www.senseinternational.org.uk/our-work/where-we-work/our-work-in-nepal/)).
- **Tactile name signs (the name-mark's grounding)** — the protactile
  literature: "Protactile Language, Modality, and Community," Annual Review
  of Linguistics
  ([annualreviews.org](https://www.annualreviews.org/content/journals/10.1146/annurev-linguistics-011724-121536)).

---

## License

Apache License 2.0 — mirrors the repo's [LICENSE](LICENSE).
