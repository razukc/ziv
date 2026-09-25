# Devpost Submission — Ziv (DRAFT, generic-angle variation)

> **Track: Best Apps and Agents.** This is the product-first variation of [DEVPOST_HAPTIC.md](DEVPOST_HAPTIC.md): the same built artifact, presented as what it is — a private, glance-free, sound-free message channel with an agent behind it — without leading with any accessibility story. The deaf-blind use case appears **only** in [Use cases](#use-cases), where it belongs. Same working title (**Ziv**), same house rules: **no clinical or efficacy claims**; nothing deferred is claimed for this submission — deferrals are named the *next revision* in the same sentence that claims what is built.

---

## Project Name

Ziv *(working title)*

## Tagline

Messages you can feel. Nobody else can see.

## Short Description (one-liner)

Ziv is a private message channel for your phone: a relay hears speech (NVIDIA Nemotron-3-Nano-Omni on Nebius Token Factory) and takes typed messages, then plays them as braille-rhythm vibrations you read by touch — no screen, no sound, nothing for the room to see or overhear — with scheduled reminders that fire while you're away.

---

## Description (paste into "Description" field)

### The Problem

Every notification channel you own spends either your eyes or your ears:

- **The screen demands your eyes** — and leaks to everyone near it. Reading a message in a meeting, on a shop floor, or across a dinner table is either rude or impossible.
- **Sound demands your ears — and the room's.** A ring or a spoken reply is a public broadcast in any shared space.
- **The third channel — touch — is wasted.** Every phone carries a vibration motor, and every app uses it as a doorbell: one buzz means "something happened," never *what*. Haptic wearables translate ambient sound into abstract vibration — awareness, not language.

So the contexts where eyes and ears fail — meetings, kitchens, workshops, libraries, night shifts, shared bedrooms — are exactly the contexts where the message doesn't get through.

The gap: **no shipping product turns vibration into a channel that carries language, with an agent behind it.**

### Our Solution

Ziv is a thin relay plus the phone you already own, used as a display for a channel that is silent and invisible by physics:

1. **Hears speech.** Push-to-talk: a clip goes to Nemotron-3-Nano-Omni on Nebius Token Factory — audio in, text out, one model transcribes natively — and the transcript enters the relay's single turn pipeline: `run_message_turn`, the exact code path, gate, and timing a typed message takes; the only added wait is the Token Factory round-trip, which the wrist feels as `processing` ticks. *(Composing AI replies from what is heard is the next build step; today the channel carries words — spoken in, tapped out.)*
2. **Speaks in rhythm.** Text is rendered as Grade-1 braille cells and played one cell at a time as vibration patterns — at the wearer's own pacing preference, clamped into the spec's envelope. Every event is framed by an attention vocabulary: an arrival cue before content, working ticks while the relay handles the turn, a descending close that says *this message is over*.
3. **Stays polite.** The haptic channel is serial — it cannot interrupt without confusing the reader. If a message lands mid-playback, it announces itself (cue only) and queues; when the current event closes, the queue drains oldest-first, each message opening with its cue. A full queue answers the sender with HTTP 429 and a plain-language note — a loud no, never a silent drop.
4. **Acts while you're away.** Scheduled reminders fire unprompted as their own full turns — arrival cue, working ticks, cells, close. A message that arrives with no phone attached is stored in a capped inbox, not dropped, and replays on the next attach as the same self-naming turn reminders take — mark first, content after.
5. **Private by physics.** Nothing to overhear, nothing to glance at: a message vibrates against the holder's skin and is invisible to the room. The mic is push-to-talk, never always-on.

### Why It Matters

- **Silent and invisible by physics** — of the channels a phone already carries (screen, speaker, buzz), only vibration delivers a message to one person without telling the room; no new device required.
- **Dignity, not just convenience:** the device that tells you things *without telling the room* changes what you can read, and where. Under a table. Mid-shift. Anywhere a screen is rude and sound is worse.
- **Courtesy is architecture, not a setting.** Queue-don't-interrupt, legible waiting, a felt end-of-message: the rules are enforced in the relay, so the channel behaves the same no matter who sends.
- **An NVIDIA open model doing real work:** Omni hears — one model, audio-native, on Nebius Token Factory.

### What it does (this submission)

Concretely, the prototype does this now:

- **Hears speech.** Push-to-talk mic → `/inject/audio` → Nemotron-3-Nano-Omni on Nebius Token Factory → the transcript runs the relay's one turn pipeline (same code path as a typed message). A keyless stub keeps the demo runnable without a key; the real call is wired, its request contract covered by a mocked-provider test.
- **Speaks in rhythm.** Grade-1 braille cells, one at a time, at the wearer's persisted pacing preference (an API-set control, clamped into the spec envelope). The attention vocabulary — arrival cue, working ticks, end-of-message close — frames every turn; an error long-buzz answers a failed transcription, and a scheduled reminder opens with its triple-pulse tail.
- **Acts while you're away.** A scheduler loop fires reminders as full turns, proven live by `/api/ziv/ready` + health telemetry — and the schedule is durable like the inbox (atomic JSON, corrupt-tolerant, capped), so a restart never drops a pending reminder.
- **Stays polite.** `MessageGate` enforces queue-don't-interrupt; a full queue is a sender-visible 429; the client shows a live queue badge, and re-sends a refused typed or stub message automatically when the freeing close lands on the wire (a refused mic clip stays a manual retry — it would need re-transcription).
- **Remembers the wearer.** Per-wearer memory files (atomic JSON, corrupt-file recovery surfaced in health) plus a capped persistent inbox: stored, not dropped; mark-after-play, so redelivery is the failure mode, never loss.
- **Boots its timing from one source.** Every pattern the phone plays comes from `GET /api/ziv/timing` — the serialized generated module — so the phone and the wrist firmware play identical patterns by construction, not by convention.

**A scene from the demo.** A colleague texts "taxi is here" during a meeting. The phone, face-down and silenced, taps the arrival cue, ticks while the relay works, spells the message cell by cell, and closes. The room sees and hears nothing. Ten minutes later, unprompted, a scheduled reminder arrives as its own full turn. Both sides of the demo are shown honestly: the message's words are visible as text in the relay's wire log, because a haptic channel has no speaker — and that is the point.

---

## Key Technologies Used

- **NVIDIA Nemotron-3-Nano-Omni** — audio in → text out; the hearing layer, on Nebius Token Factory
- **Nebius Token Factory** — inference for the Omni model
- **FastAPI + WebSockets** — the thin relay: WS gateway, optional shared-token auth, per-wearer memory files, capped inbox, scheduler loop
- **The Android Vibration API** — the output channel; the wrist hardware (ESP32-S3 + DRV2605L + 6 LRA motors) is the next revision
- **ESP32-S3 N16R8 + DRV2605L + 6 LRA motors** — the next revision's hardware (~$40 BOM); the firmware is written against it (`firmware/haptic_out/`), boards are not shipped in this prototype

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
  audio → Token Factory Omni (hearing, Nemotron-3-Nano-Omni)
  text  → the transcript runs the relay's one turn pipeline (same code path as a typed message)
  memory: per-wearer memory files + capped inbox
  scheduler: a poll loop fires reminders while nobody is "chatting" (schedule durable like the inbox)
        ▼
[Nebius Token Factory — NVIDIA open models]
  Nemotron-3-Nano-Omni  (audio in → text out; the hearing layer)
```

The phone is the display for this hackathon; the wrist firmware is generated from the same timing source the phone boots from, but it is not on hardware for this submission.

### Design decisions

1. **Vibration is the only output.** No TTS pipeline, no echo cancellation, no wake word: removing sound output removes the entire hard-problem list of voice wearables — and removes the leak. Sound tells the room; vibration tells one person.
2. **Text as rhythm, in two layers.** Layer one is the attention vocabulary — arrival, working, done, and the error long-buzz when a turn fails — the part every wearer feels from minute one. Layer two is the text itself, spelled as Grade-1 braille cells for anyone who reads braille or learns it. Word-shape corner cues (space, capital, number sign) are planned — the prototype plays plain letters (a–z); pacing is the first-class control.
3. **One timing source, generated, never hand-edited.** `docs/haptic-timing.json` generates seven consumers (phone feel-tool + firmware header + Python consumer + ladder tables), so the phone and the wrist firmware play identical patterns by construction. A drift guard fails on any hand edit to a generated block.
4. **Courtesy as relay behavior, not a UI hint.** `MessageGate` is the serialization point: while content plays, an incoming message gets its cue only and queues; the wearer releases the queue by closing the event; drained messages play FIFO, each opening with its cue. The close frame that frees the channel is marked on the wire (`free: true`), so the client's auto-redial fires on the frame the wearer feels — not on a timing guess.
5. **Durable state.** Memory files + a persistent, capped inbox: a message arriving with no phone attached is stored, not dropped, and replays as a self-naming turn — mark first, content after. Mark-after-play: redelivery, never loss.
6. **A felt identity.** The timing spec defines a name mark — Z-I-V spelled in vibro-braille — and the relay plays it today: scheduled reminders open as their own turns with the mark spelled in cells, the kind's triple-pulse tail, and a breath before the content.
7. **Push-to-talk mic (this prototype).** Audio capture only on the mic button — never always-on listening. The wrist hardware's hardware-gated mic (ESP32 pin) is the next revision.
8. **Honest scope.** This submission is a phone-based prototype to the Best Apps and Agents track. The full private, wearer-controlled system (wrist device with hardware-gated mic + wearer-hosted relay) is the next revision. The haptic output is private by physics; the mic is push-to-talk; the relay runs on our infrastructure, not the wearer's, in this prototype.

---

## Challenges we ran into

1. **Rendering language as rhythm.** cell → dot bitmask → vibration waveform timing, with pacing as the first-class control — and with the honest unknown out front: how fast people actually learn to read text by vibration is unproven (see Use cases).
2. **Making waiting legible.** A model round-trip is dead air unless the channel says so — so the turn plays working ticks while the relay handles it, and a descending close when it ends. Latency may be slow, never silent.
3. **Courtesy has to be architectural when the channel is serial.** A vibration channel cannot interrupt without confusing the reader, so queue-don't-interrupt became a relay behavior with a bounded queue, a 429 refusal path, and operator-visible rejection telemetry.
4. **Keeping the infrastructure honest.** The relay runs on our infrastructure, not the wearer's (model inference on Nebius Token Factory); wearer self-hosting is the next revision, scoped rather than claimed.
5. **Verifying the Token Factory Omni audio payload format** (the week-1 spike) — the real call is wired, with its request contract covered by a mocked-provider test; a keyless stub keeps the demo runnable without a key.
6. **Making the demo honest without a speaker.** A channel with no audio output can leave a room assuming the wrong thing — so the demo shows the friend's side as text in the relay's wire log rather than leaving it to the room to guess.

---

## Accomplishments that we're proud of

- **A working channel the wearer can feel on hardware everyone owns.** A message arrives, the phone plays the arrival cue, the working ticks, the braille cells, the end-of-message close — the whole turn journey, with the same timing the wrist firmware would use. This is not a mock of the channel; it is the channel, on a dev band.
- **A single timing source shared by construction.** One JSON generates the phone feel-tool, the firmware header, the Python consumer, and the ladder doc's demo table; a drift guard refuses any hand edit to a generated block.
- **A relay that enforces the right behavior by default.** Queue-don't-interrupt, working-while-waiting, close-before-release, mark-after-play redelivery — made real in the relay seam and the turn timeline, with a threaded concurrency guard so concurrent arrivals never lose or duplicate a message.
- **A refusal path that is loud and sender-visible.** A full queue answers 429 with a reason; the phone shows a plain-language "busy" note and keeps the drafted text; a live queue badge shows how close the queue is to refusing; health surfaces the rejection count and rate.
- **An audio-in path that is wired, not just a diagram.** MediaRecorder → base64 → `/inject/audio` → Nemotron-3-Nano-Omni → the relay's single turn pipeline (the exact code path, gate, and timing a typed message takes).
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

**Everyday: the meeting, the kitchen, the night shift.** Anywhere a screen is rude and sound is worse, the channel delivers what a buzz cannot: content, framed by cues, felt by exactly one person. The attention vocabulary — arrival, working, done — is what every wearer feels from the first minute; the text layer is there for anyone who reads braille or chooses to learn it. That learnability is the #1 open risk: how fast people actually pick up long-form text-by-vibration is unproven, and the fallback (a fixed attention vocabulary + a 30-phrase set, then a 3-button read/stop/repeat mode) is specified in the plan so the channel stays useful even if long-form reading never lands.

**The sharpest case: deaf-blind users.** ~2.4 million Americans live with combined hearing and vision loss (~45–70k at the deaf-blind core), and almost nothing is built for them: refreshable braille displays ($1,500–$12,000) have no microphone and no agent; braille keyboards ($239–$349) are input-only; haptic wristbands (Neosensory, Dot) give awareness or notification mirroring, not language with a brain. For this population the channel is not a convenience — it is the difference between a doorbell and a conversation. Braille is a literacy many in this population already hold; vibration on the skin is the one display they can read anywhere, and the hearing layer gives the channel the brain every prior device lacked: **no shipping product pairs a haptic braille output channel with a device that can hear.**

**Why the sharpest case made the product better for everyone.** The interaction rules were adopted from published early-years deafblind practice (Sense UK, via Insight): every event is cued before it happens, cues mark the start *and* the end, waiting is legible, and nothing barges in. Those four invariants are enforced in the relay's code — and they are exactly why the channel stays legible for a sighted user in a meeting, too. The population that needed the channel most wrote its manners; everyone else inherits them.

---

## What's next for Ziv

**Next revision (after the hackathon):** the wrist device — ESP32-S3 + DRV2605L + 6 LRA motors, ~$40 BOM — with a hardware-gated mic and 6-key braille chord input, running the same relay protocol and the same generated timing source the phone uses now. The phone prototype already generates the firmware header from the same timing JSON the phone feels, so the wrist step is a bring-up, not a rebuild.

After the wrist lands:

1. **Hardware-gated mic** — push-to-talk becomes a physical property, not a software choice.
2. **Wearer-hosted relay** — the wearer runs their own relay, so their data is under their control.
3. **AI-composed replies** — a text model on the relay turns what was heard into an answer, closing the conversation loop.
4. **Spoken replies for the sender (v2)** — TTS, so the sighted-hearing side hears the answer.
5. **Grade 2 braille contractions** — 20–40% fewer cells per message, tuned with braille readers.

Open now (decision points, not promises):

- **Learnability** — the #1 risk: the honest claim is "a working prototype of a new channel," not a proven reading method. The fallback ladder is specified in advance.
- **Naming** — "Ziv" is a working title; a validation session with the deaf-blind community is planned, not yet held.

---

## Devpost-Specific Answers

### What hackathon track are you in?

Best Apps and Agents Track

### What does your project do?

Ziv (working title) is a private message channel for your phone: a relay hears speech (Nemotron-3-Nano-Omni on Nebius Token Factory, push-to-talk) and takes typed messages, then plays them as braille-rhythm vibrations framed by an attention vocabulary — arrival cue, working ticks, end-of-message close. The channel queues instead of interrupting, stores messages when no phone is attached, fires scheduled reminders while you're away, and remembers your pacing. Always-on is the relay's property: it schedules, fires, and stores while you're away; the phone renders each event while its page is open. This submission is a phone-based prototype; the wrist device is the next revision. *(Composing AI replies from what is heard is the next build step; today the channel carries words — spoken in, tapped out.)*

### What makes your project unique?

No shipping product turns vibration into a channel that carries language, with an agent behind it: phone buzzes are context-free doorbells; haptic wristbands translate sound into abstract awareness; smartwatches mirror notifications but still demand the eyes for anything that matters. Ziv's combination is new: a serial haptic channel with enforced courtesy (queue-don't-interrupt as relay behavior), a two-layer vocabulary (attention patterns for anyone, braille text for readers), an agent that acts while you're away, and one generated timing source shared by the phone today and the wrist firmware of the next revision (the phone boots its patterns from `GET /api/ziv/timing`, the serialized generated module).

### What challenges did you face?

1. **Rendering language as rhythm:** cell → dot bitmask → vibration waveform timing, with pacing as the first-class control — and learnability named as the #1 open risk.
2. **Making waiting legible:** working ticks during the round-trip, a felt close at the end — latency may be slow, never silent.
3. **Courtesy as architecture:** the serial channel cannot interrupt, so the queue, the 429 refusal, and the release semantics live in the relay, not the UI.
4. **Keeping the infrastructure honest:** the relay runs on our infrastructure; wearer self-hosting is the next revision.
5. **Verifying the Token Factory Omni audio payload format:** the real call is wired, its request contract covered by a mocked-provider test; a keyless stub keeps the demo runnable without a key.

### What technologies did you use?

NVIDIA Nemotron-3-Nano-Omni, Nebius Token Factory, FastAPI, WebSockets, Android Vibration API, ESP32-S3 (ESP-IDF, C), DRV2605L, LRA vibration motors, I2S MEMS microphone. *(The wrist hardware — ESP32-S3 + DRV2605L + 6 LRA motors + I2S MEMS mic — is the next revision, not shipped in this phone-based prototype.)*

---

## Demo Video Outline (≤3 min)

1. **0:00–0:20** — cold open: a phone face-down and silenced in a meeting buzzes; fingers read it; the room sees and hears nothing. "A message only one person receives."
2. **0:20–1:10** — the channel: arrival cue → working ticks → braille cells → close; the attention vocabulary; a queued message released by the close; the 429 and the auto-redial.
3. **1:10–1:50** — the stack: push-to-talk speech → Nemotron-3-Nano-Omni on Token Factory → the relay's one turn pipeline (same code path as a typed message); the timing spec generated from one JSON, the drift guard proving phone and wrist share the same patterns.
4. **1:50–2:30** — the agent: a scheduled reminder fires unprompted, proven by the relay's ready/health telemetry; the inbox stores a message that arrived with no phone attached; honest scope (relay on our infrastructure; wrist hardware + wearer-hosted relay = next revision).
5. **2:30–3:00** — who it serves best: everyday private contexts, and the deaf-blind community — the population nothing else is built for, whose practice wrote the channel's manners. The ask: "a new channel for messages the room was never meant to see."

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
