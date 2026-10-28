# Devpost Submission — Ziv (DRAFT, generic-angle variation)

> **Track: Best Apps and Agents.** This is the product-first variation of [DEVPOST_HAPTIC.md](DEVPOST_HAPTIC.md): the same built artifact, presented as what it is — a message channel that needs no glance, with an agent behind it — without leading with any accessibility story. The deaf-blind use case appears **only** in [Use cases](#use-cases), where it belongs. Same working title (**Ziv**), same house rules: **no clinical or efficacy claims**; nothing deferred is claimed for this submission — deferrals are named the *next revision* in the same sentence that claims what is built.

---

## Project Name

Ziv *(working title)*

## Tagline

Messages you can feel. No spoken reply.

## Short Description (one-liner)

Ziv is a message channel for your phone: the phone plays what arrives as braille-rhythm vibrations you feel — no audio output, no spoken reply. The relay schedules reminders and stores messages while the phone is away; a scheduled intent is composed live on Nebius Token Factory when the relay has a key, and otherwise fires verbatim, labelled `text_echo`. The phone renders each event only while its page is open and connected.

---

## Description (paste into "Description" field)

### The Problem

Every notification channel you own spends either your eyes or your ears:

- **The screen demands your eyes** — and leaks to everyone near it. Reading a message in a meeting, on a shop floor, or across a dinner table is either rude or impossible.
- **Sound demands your ears — and the room's.** A ring or a spoken reply is a public broadcast in any shared space.
- **The third channel — touch — is wasted.** Every phone carries a vibration motor, and every app uses it as a doorbell: one buzz means "something happened," never *what*. Haptic wearables translate ambient sound into abstract vibration — awareness, not language.

So the contexts where eyes and ears fail — meetings, kitchens, workshops, libraries, night shifts, shared bedrooms — are exactly the contexts where the message doesn't get through.

The gap, in the five products we surveyed: **we did not find one that turns vibration into a channel carrying language, with an agent behind it.**

### Our Solution

Ziv is a thin relay plus the phone you already own, used as a display for a channel whose output is vibration, not broadcast to the room:

1. **Plays in rhythm.** Text is rendered as Grade-1 braille cells and played one cell at a time as vibration patterns — at the wearer's own pacing preference, clamped into the spec's envelope. Every event is framed by an attention vocabulary: an arrival cue before content, working ticks while the relay handles the turn, a descending close that says *this message is over*.
2. **Stays polite.** The haptic channel is serial — it cannot interrupt without confusing the reader. If a message lands mid-playback, it announces itself (cue only) and queues; when the current event closes, the queue drains oldest-first, each message opening with its cue. A full queue answers the sender with HTTP 429 and a plain-language note — a loud no, never a silent drop.
3. **The relay acts while the phone is away.** Scheduled reminders fire unprompted as their own full turns — arrival cue, working ticks, cells, close. A message that arrives with no phone attached is stored in a capped inbox and replays on the next attach as the same self-naming turn reminders take — mark first, content after. At the 20-message cap the oldest pending message is evicted, counted in health. The phone renders a turn only while its page is open and connected; there is no background push or lock-screen delivery in this build.
4. **No spoken reply, not a broadcast.** The phone plays the message as vibration; Ziv synthesizes no speech and reads nothing aloud. That is the output choice, not a guarantee about everyone nearby: the words are also shown on the phone's reply screen and in the relay log, the motor is not silent, and we have not measured its acoustic level. The mic is push-to-talk, never always-on.

### Why It Matters

- **No spoken reply, not a broadcast** — of the channels a phone already carries (screen, speaker, buzz), vibration can deliver a message to the holder without speaking to the room; no new device required. The demo's screen and relay log still show the text.
- **Dignity, not just convenience:** the device that tells you things *without telling the room* changes what you can read, and where. Under a table. Mid-shift. Anywhere a lit screen is rude and sound is worse.
- **Courtesy is architecture, not a setting.** Queue-don't-interrupt, legible waiting, a felt end-of-message: the rules are enforced in the relay, so the channel behaves the same no matter who sends.

### What it does (this submission)

Concretely, the prototype does this now:

- **A turn that runs with or without a provider.** A typed message never reaches the model; a scheduled intent is composed live when the relay has a key and otherwise fires verbatim, labelled `text_echo` — either way: cue, processing ticks, braille cells, felt close, queue release.
- **Plays in rhythm.** Grade-1 braille cells, one at a time, at the wearer's persisted pacing preference (an API-set control, clamped into the spec envelope). The attention vocabulary — arrival cue, working ticks, end-of-message close — frames every turn; an error long-buzz answers a failed transcription, and a scheduled reminder opens with its triple-pulse tail.
- **The relay acts while the phone is away.** A scheduler loop fires reminders as full turns, proven live by `/api/ziv/ready` + health telemetry — and the schedule is durable like the inbox (atomic JSON, corrupt-tolerant, capped), so a restart does not drop a pending reminder; the 64-reminder cap can evict the oldest. The phone renders a turn only while its page is open and connected; nothing wakes a closed browser.
- **Stays polite.** `MessageGate` enforces queue-don't-interrupt; a full queue is a sender-visible 429; the client shows a live queue badge, and re-sends a refused typed or stub message automatically when the freeing close lands on the wire (a refused mic clip stays a manual retry — it would need re-transcription).
- **Remembers the wearer.** Per-wearer memory files (atomic JSON, corrupt-file recovery surfaced in health) plus a capped persistent inbox: stored in a 20-item inbox; at the cap the oldest is evicted and counted in health; below the cap, mark-after-play makes redelivery the failure mode.
- **Boots its timing from one source.** Every pattern the phone plays comes from `GET /api/ziv/timing` — the serialized generated module — so the phone and the feel-tool play identical patterns by construction, not by convention.

**A scene from the demo.** A colleague texts "taxi is here" during a meeting. The phone, face-down and silenced, taps the arrival cue, ticks while the relay works, spells the message cell by cell, and closes. The room hears no spoken reply. Ten minutes later, unprompted, a scheduled reminder arrives as its own full turn. Both sides of the demo are shown honestly: the message's words are visible as text in the relay's wire log, because a haptic channel has no speaker — and that is the point.

---

## Key Technologies Used

- **NVIDIA Nemotron-3-Nano-30B-A3B** — text in → the line a wrist reads; the model behind the agent path this demo runs, on Nebius Token Factory
- **Nebius Token Factory** — inference for the Omni model; the hearing layer runs on Nebius when an audio-capable Omni endpoint is configured
- **FastAPI + WebSockets** — the thin relay: WS gateway, optional shared-token auth, per-wearer memory files, capped inbox, scheduler loop
- **The Android Vibration API** — the output channel this demo plays on

**Next revision's hardware, not a technology used here:** the wrist device — ESP32-S3 N16R8 + DRV2605L + 6 LRA motors, ~$40 BOM. The firmware in `firmware/haptic_out/` is written against it and bench-tested on the host; no board is flashed for this prototype.

---

## How we built it

### Architecture

```
[phone: Android Chrome PWA]
  mic ──► MediaRecorder (push-to-talk only) ──► base64 audio
  Vibration API ◄── braille cells + attention vocabulary
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

The phone is the display for this hackathon; the wrist firmware is generated from the same timing source the phone boots from, but it is not on hardware for this submission.

### Design decisions

1. **Vibration is the message output.** No TTS pipeline, no echo cancellation, no wake word: removing sound output removes the entire hard-problem list of voice wearables — and removes the leak. Sound tells the room; vibration tells one person.
2. **Text as rhythm, in two layers.** Layer one is the attention vocabulary — arrival, working, done, and the error long-buzz when a turn fails — the part designed to be legible from the first turn. Layer two is the text itself, spelled as Grade-1 braille cells for anyone who reads braille or learns it. Word-shape corner cues (space, capital, number sign) are planned — the prototype plays plain letters (a–z); pacing is the first-class control.
3. **One timing source, generated, never hand-edited.** `docs/haptic-timing.json` generates seven consumers (phone feel-tool + firmware header + Python consumer + ladder tables), so the phone's patterns and the wrist firmware come from one source by construction. A drift guard fails on any hand edit to a generated block.
4. **Courtesy as relay behavior, not a UI hint.** `MessageGate` is the serialization point: while content plays, an incoming message gets its cue only and queues; the wearer releases the queue by closing the event; drained messages play FIFO, each opening with its cue. The close frame that frees the channel is marked on the wire (`free: true`), so the client's auto-redial fires on the frame the wearer feels — not on a timing guess.
5. **Durable state.** Memory files + a persistent, capped inbox: a message arriving with no phone attached is stored in a capped inbox and replays as a self-naming turn — mark first, content after; at the 20-message cap the oldest is evicted and counted in health. Mark-after-play: below the cap, redelivery is the failure mode.
6. **A felt identity.** The timing spec defines a name mark — Z-I-V spelled in vibro-braille — and the relay plays it today: scheduled reminders open as their own turns with the mark spelled in cells, the kind's triple-pulse tail, and a breath before the content.
7. **Push-to-talk mic (this prototype).** Audio capture only on the mic button — never always-on listening. The wrist hardware's hardware-gated mic (ESP32 pin) is the next revision.
8. **Honest scope.** This submission is a phone-based prototype to the Best Apps and Agents track. The full wearer-controlled system (wrist device with hardware-gated mic + wearer-hosted relay) is the next revision. The haptic output is felt by the holder and is not spoken to the room; the mic is push-to-talk; the relay runs on our infrastructure, not the wearer's, in this prototype.

---

## Challenges we ran into

1. **Rendering language as rhythm.** cell → dot bitmask → vibration waveform timing, with pacing as the first-class control — and with the honest unknown out front: how fast people actually learn to read text by vibration is unproven (see Use cases).
2. **Making waiting legible.** A turn is dead air unless the channel says so — so the turn plays working ticks while the relay handles it, and a descending close when it ends. Latency may be slow; the channel is designed to say it is working.
3. **Courtesy has to be architectural when the channel is serial.** A vibration channel cannot interrupt without confusing the reader, so queue-don't-interrupt became a relay behavior with a bounded queue, a 429 refusal path, and operator-visible rejection telemetry.
4. **Making the demo honest without a speaker.** A channel with no audio output can leave a room assuming the wrong thing — so the demo shows the friend's side as text in the relay's wire log rather than leaving it to the room to guess.

---

## Accomplishments that we're proud of

- **A working channel the wearer can feel on hardware everyone owns.** A message arrives, the phone plays the arrival cue, the working ticks, the braille cells, the end-of-message close — the whole turn journey, with the same timing the wrist firmware would use. This is not a mock of the channel; it is the channel, on a dev band.
- **A single timing source shared by construction.** One JSON generates the phone feel-tool, the firmware header, the Python consumer, and the ladder doc's demo table; a drift guard refuses any hand edit to a generated block.
- **A relay that enforces the right behavior by default.** Queue-don't-interrupt, working-while-waiting, close-before-release, mark-after-play redelivery — made real in the relay seam and the turn timeline, with a threaded concurrency guard so a concurrent arrival is queued rather than lost or duplicated.
- **A refusal path that is loud and sender-visible.** A full queue answers 429 with a reason; the phone shows a plain-language "busy" note and keeps the drafted text; a live queue badge shows how close the queue is to refusing; health surfaces the rejection count and rate.
- **A model inside the channel, not beside it.** You schedule an intent, the relay calls Nemotron on Nebius Token Factory, and the phone spells the line the model wrote — through the same turn pipeline (the exact code path, gate, and timing any message takes). The audio-in seam is the designed hearing layer, held as asset.
- **Honest scope.** The built things are proven; the wrist hardware, chord input, hardware-gated mic, and wearer-hosted relay are scoped and de-risked — and the submission says so in the same sentence that claims what is built.

---

## What We Learned

- **The channel is the product, not the form factor.** A vibration motor that plays language is the same channel on a phone or a wrist — that is what made this buildable without the hardware.
- **Honesty is a credibility strategy, not a modesty strategy.** A reviewer can hold the real claim in one sentence — and the honest claim is already impressive.
- **The hardest problems went away by removal, not by solving.** Removing sound output removed echo cancellation, wake word, and TTS from the critical path.
- **Courtesy has to be architectural when the channel is serial.** The wearer, not the sender, decides when the next message begins.
- **A demo can lie by implication.** With no speaker in the room, the friend's reply is text in the relay log — show it, or the room will assume the wrong thing.

---

## Use cases

*(The one place this submission names who it serves best — because the channel was sharpened by a specific population, and the sharpening shows.)*

**Everyday: the meeting, the kitchen, the night shift.** Anywhere a lit screen is rude and sound is worse, the channel delivers what a buzz cannot: content, framed by cues, felt by the holder — while the phone's screen and the relay log still show the text, and the motor is not silent. The attention vocabulary — arrival, working, done — is the designed first layer; the text layer is there for anyone who reads braille or chooses to learn it. That learnability is the #1 open risk: how fast people actually pick up long-form text-by-vibration is unproven, and the fallback (a fixed attention vocabulary + a 30-phrase set, then a 3-button read/stop/repeat mode) is specified in the plan so the channel stays useful even if long-form reading never lands.

**The sharpest case: deaf-blind users.** ~2.4 million Americans live with combined hearing and vision loss (~45–70k at the deaf-blind core), and the market we surveyed is thin: refreshable braille displays ($1,500–$12,000) have no microphone and no agent; braille keyboards ($239–$349) are input-only; haptic wristbands (Neosensory, Dot) give awareness or notification mirroring, not language with a brain. What the demo shows is delivery and timing on one Android phone: the arrival cue, working ticks, Grade-1 cells, and the close. The operator reads the text on the phone's reply screen and in the relay log to verify what was played; that is a delivery check, not a comprehension test. It does not show a deaf-blind person reading the cells, and it is not a reading study. Braille cells carry meaning for someone who reads braille or learns it; the attention cues are a designed vocabulary, not a validated language. We have not held a validation session with deaf-blind readers. The claim is a working prototype of a new channel — not evidence that it is readable from minute one, and not evidence that it turns a doorbell into a conversation. Nor do we claim that nothing else is built for this population: braille displays and keyboards exist, and the survey above says what each covers.

**Why the sharpest case made the product better for everyone.** The interaction rules were adopted from published early-years deafblind practice (Sense UK, via Insight): every event is cued before it happens, cues mark the start *and* the end, waiting is legible, and nothing barges in. Those four invariants are enforced in the relay's code — and they are exactly why the channel stays legible for a sighted user in a meeting, too. The population that needed the channel most wrote its manners; everyone else inherits them.

---

## What's next for Ziv

What is held as asset, only if someone asks: the wrist device — ESP32-S3 + DRV2605L + 6 LRA motors, ~$40 BOM — with a hardware-gated mic and 6-key braille chord input, running the same relay protocol and the same generated timing source the phone uses now. The phone prototype already generates the firmware header from the same timing JSON the phone feels, so the wrist step is a bring-up, not a rebuild. Also held as asset: an audio-in hearing layer (`POST /inject/audio`) — wired, opt-in, contract-tested; it needs an endpoint that accepts audio input, so it is not part of this entry's demonstrated beat.

Open now (decision points, not promises):

- **Learnability** — the #1 risk: the honest claim is "a working prototype of a new channel," not a proven reading method. The fallback ladder is specified in advance.
- **Naming** — "Ziv" is a working title; a validation session with the deaf-blind community is planned, not yet held.

---

## Devpost-Specific Answers

### What hackathon track are you in?

Best Apps and Agents Track

### What does your project do?

Ziv (working title) is a message channel for your phone: an NVIDIA open model on Nebius Token Factory does the thinking, and the phone plays what it says as braille-rhythm vibrations framed by an attention vocabulary — arrival cue, working ticks, end-of-message close. The channel queues instead of interrupting, stores messages in a capped inbox when no phone is attached, and schedules reminders on the relay. "Always-on" describes the relay, not the phone: it schedules, composes, and stores while the phone is away; the phone renders each event only while its page is open and connected, with no background push or lock-screen delivery. This submission is a phone-based demo; the wrist device is not part of this entry.

### What makes your project unique?

In the five products we surveyed, we did not find one that turns vibration into a channel carrying language with an agent behind it: phone buzzes are context-free doorbells; haptic wristbands translate sound into abstract awareness; smartwatches mirror notifications but still demand the eyes for anything that matters. Ziv's contribution is the combination: a serial haptic channel with enforced courtesy (queue-don't-interrupt as relay behavior), a two-layer vocabulary (attention patterns for anyone, braille text for readers), a relay that schedules and stores while the phone is away, and one generated timing source shared by the phone today and the wrist firmware of the next revision (the phone boots its patterns from `GET /api/ziv/timing`, the serialized generated module).

### What challenges did you face?

1. **Rendering language as rhythm:** cell → dot bitmask → vibration waveform timing, with pacing as the first-class control — and learnability named as the #1 open risk.
2. **Making waiting legible:** working ticks during the round-trip, a felt close at the end — latency may be slow; the channel is designed to say it is working.
3. **Courtesy as architecture:** the serial channel cannot interrupt, so the queue, the 429 refusal, and the release semantics live in the relay, not the UI.
4. **Keeping the infrastructure honest:** the relay runs on our infrastructure; wearer self-hosting is the next revision.
5. **Verifying the Token Factory Omni audio payload format:** the real call is wired, its request contract covered by a mocked-provider test; a keyless stub keeps the demo runnable without a key.

### What technologies did you use?

NVIDIA Nemotron-3-Nano-30B-A3B on Nebius Token Factory, FastAPI, WebSockets, the Android Vibration API — plus the ESP-IDF firmware module that plays the same generated timing (274 host checks against a mock driver). No wrist board is flashed for this demo.

---

## Demo Video Outline (≤3 min)

1. **0:00–0:20** — cold open: a phone face down and silenced in a meeting buzzes; the wearer feels the cells; the room hears no spoken reply, and the words appear on the phone's reply screen and in the relay log. "A message you feel. No spoken reply."
2. **0:20–1:10** — the channel: arrival cue → working ticks → braille cells → close; the attention vocabulary; a queued message released by the close; the 429 and the auto-redial.
3. **1:10–1:50** — the timing source: the spec is generated from one JSON; the drift guard proves the phone and the feel-tool share the same patterns. The demo beat plays cue, working ticks, braille cells, close, queue release.
4. **1:50–2:30** — the agent: a scheduled reminder fires unprompted, proven by the relay's ready/health telemetry; the inbox stores a message that arrived with no phone attached; held as asset: the wrist device, and the audio-in hearing layer. The ask: "a new channel for messages the room does not need to hear."

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
