## Inspiration

Every notification channel you own spends either your eyes or your ears:

- **The screen demands your eyes** — and leaks to everyone near it. Reading a message in a meeting, on a shop floor, or across a dinner table is either rude or impossible.
- **Sound demands your ears — and the room's.** A ring or a spoken reply is a public broadcast in any shared space.
- **The third channel — touch — is wasted.** Every phone carries a vibration motor, and every app uses it as a doorbell: one buzz means "something happened," never *what*. Haptic wearables translate ambient sound into abstract vibration — awareness, not language.

So the contexts where eyes and ears fail — meetings, kitchens, workshops, libraries, night shifts, shared bedrooms — are exactly the contexts where the message doesn't get through.

The gap: **no shipping product turns vibration into a channel that carries language, with an agent behind it.**

The channel's manners were not invented for this hackathon — they were adopted. Published early-years deafblind practice (created by Sense UK, published by Insight) says: every event is cued before it happens, cues mark the start *and* the end, waiting is legible, and nothing barges in. Those four invariants are enforced in the relay's code — and they are exactly why the channel stays legible for a sighted user in a meeting, too. The population that needed the channel most wrote its rules; everyone else inherits them.

**The sharpest case.** ~2.4 million Americans live with combined hearing and vision loss (~45–70k at the deaf-blind core), and almost nothing is built for them: refreshable braille displays ($1,500–$12,000) have no microphone and no agent; braille keyboards ($239–$349) are input-only; haptic wristbands give awareness or notification mirroring, not language with a brain. For this population the channel is not a convenience — it is the difference between a doorbell and a conversation. Braille is a literacy many in this population already hold; vibration on the skin is the one display they can read anywhere; and the hearing layer gives the channel the brain every prior device lacked: **no shipping product pairs a haptic braille output channel with a device that can hear.** (Sources for every number are at the end of this story.)

## What it does

Ziv is a thin relay plus the phone you already own, used as a display for a channel that is silent and invisible by physics:

1. **Thinks for you.** A reminder you set while busy is not a line you typed — it is an intent ("meds at nine"), and when it fires an NVIDIA open model on Nebius Token Factory writes the line the wrist spells. The model's words enter the relay's single turn pipeline: `run_message_turn`, the exact code path, gate, and timing any message takes; the round-trip is the only added wait, and the wrist feels it as `processing` ticks rather than silence. *(Push-to-talk audio in is the designed hearing layer — held as asset, not part of this entry.)*
2. **Speaks in rhythm.** Text is rendered as Grade-1 braille cells and played one cell at a time as vibration patterns — at the wearer's own pacing preference, clamped into the spec's envelope. Every event is framed by an attention vocabulary: an arrival cue before content, working ticks while the relay handles the turn, a descending close that says *this message is over*.
3. **Stays polite.** The haptic channel is serial — it cannot interrupt without confusing the reader. If a message lands mid-playback, it announces itself (cue only) and queues; when the current event closes, the queue drains oldest-first, each message opening with its cue. A full queue answers the sender with HTTP 429 and a plain-language note — a loud no, never a silent drop.
4. **Acts while you're away.** Scheduled reminders fire unprompted as their own full turns — arrival cue, working ticks, cells, close. A message that arrives with no phone attached is stored in a capped inbox, not dropped, and replays on the next attach as the same self-naming turn reminders take — mark first, content after.
5. **Private by physics.** Nothing to overhear, nothing to glance at: a message vibrates against the holder's skin and is invisible to the room. The mic is push-to-talk, never always-on.

Concretely, the prototype does this now:

- **Thinks for you.** Schedule an *intent*, not a sentence: `POST /api/ziv/schedule` with `{"intent": "meds at nine"}`. When it fires, the relay calls Nemotron-3-Nano-30B-A3B on Nebius Token Factory and plays the line the model wrote — the wire log says `source: text_live`. Without a key the promise still fires verbatim, labelled `text_echo`, so the log never claims a model ran when none did.
- **Speaks in rhythm.** Grade-1 braille cells, one at a time, at the wearer's persisted pacing preference (an API-set control, clamped into the spec envelope). The attention vocabulary — arrival cue, working ticks, end-of-message close — frames every turn; an error long-buzz answers a failed transcription, and a scheduled reminder opens with its triple-pulse tail.
- **Acts while you're away.** A scheduler loop fires reminders as full turns, proven live by `/api/ziv/ready` + health telemetry — and the schedule is durable like the inbox (atomic JSON, corrupt-tolerant, capped), so a restart never drops a pending reminder.
- **Stays polite.** `MessageGate` enforces queue-don't-interrupt; a full queue is a sender-visible 429; the client shows a live queue badge, and re-sends a refused typed or stub message automatically when the freeing close lands on the wire (a refused mic clip stays a manual retry — it would need re-transcription).
- **Remembers the wearer.** Per-wearer memory files (atomic JSON, corrupt-file recovery surfaced in health) plus a capped persistent inbox: stored, not dropped; mark-after-play, so redelivery is the failure mode, never loss.
- **Boots its timing from one source.** Every pattern the phone plays comes from `GET /api/ziv/timing` — the serialized generated module — so the phone and the wrist firmware play identical patterns by construction, not by convention.

**A scene from the demo.** You set an intent — "meds at nine" — and get back to work. Ten minutes later, unprompted, the phone taps the arrival cue, spells the Z-I-V mark, ticks while the relay finishes, spells the line a model wrote for you, and closes. The room sees and hears nothing. Both sides are shown honestly: the words are visible as text in the relay's wire log, because a haptic channel has no speaker — and that is the point.

## How we built it

**Key technologies:**

- **NVIDIA Nemotron-3-Nano-30B-A3B on Nebius Token Factory** — text in → the line a wrist reads; the model behind the agent path this demo runs
- **Nebius Token Factory** — inference for the Omni model
- **FastAPI + WebSockets** — the thin relay: WS gateway, optional shared-token auth, per-wearer memory files, capped inbox, scheduler loop
- **The Android Vibration API** — the output channel; the wrist hardware (ESP32-S3 + DRV2605L + 6 LRA motors) is the next revision
- **ESP32-S3 N16R8 + DRV2605L + 6 LRA motors** — the next revision's hardware (~$40 BOM); the firmware is written against it (`firmware/haptic_out/`), boards are not shipped in this prototype

**Architecture:**

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

**Design decisions** — the five that shaped everything else:

1. **Vibration is the only output.** No TTS pipeline, no echo cancellation, no wake word: removing sound output removes the entire hard-problem list of voice wearables — and removes the leak. Sound tells the room; vibration tells one person.
2. **Text as rhythm, in two layers.** Layer one is the attention vocabulary — arrival, working, done, and the error long-buzz when a turn fails — the part every wearer feels from minute one. Layer two is the text itself, spelled as Grade-1 braille cells for anyone who reads braille or learns it. Word-shape corner cues (space, capital, number sign) are planned — the prototype plays plain letters (a–z); pacing is the first-class control.
3. **One timing source, generated, never hand-edited.** `docs/haptic-timing.json` generates seven consumers (phone feel-tool + firmware header + Python consumer + ladder tables), so the phone and the wrist firmware play identical patterns by construction. A drift guard fails on any hand edit to a generated block.
4. **Courtesy as relay behavior, not a UI hint.** `MessageGate` is the serialization point: while content plays, an incoming message gets its cue only and queues; the wearer releases the queue by closing the event; drained messages play FIFO, each opening with its cue. The close frame that frees the channel is marked on the wire (`free: true`), so the client's auto-redial fires on the frame the wearer feels — not on a timing guess.
5. **Durable state.** Memory files + a persistent, capped inbox: a message arriving with no phone attached is stored, not dropped, and replays as a self-naming turn — mark first, content after. Mark-after-play: redelivery, never loss.

**Push-to-talk and honest scope.** Audio capture happens only on the mic button — never always-on listening (the wrist hardware's hardware-gated mic is the next revision). This submission is a phone-based prototype to the Best Apps and Agents track; the full private, wearer-controlled system (wrist device with hardware-gated mic + wearer-hosted relay) is the next revision. The haptic output is private by physics; the mic is push-to-talk; the relay runs on our infrastructure, not the wearer's, in this prototype.

## Challenges we ran into

1. **Rendering language as rhythm.** Cell → dot bitmask → vibration waveform timing, with pacing as the first-class control — and with the honest unknown out front: how fast people actually learn to read text by vibration is unproven (the #1 open risk, named under What's next).
2. **Making waiting legible.** A model round-trip is dead air unless the channel says so — so the turn plays working ticks while the relay handles it, and a descending close when it ends. Latency may be slow, never silent.
3. **Courtesy has to be architectural when the channel is serial.** A vibration channel cannot interrupt without confusing the reader, so queue-don't-interrupt became a relay behavior with a bounded queue, a 429 refusal path, and operator-visible rejection telemetry.
4. **Keeping the infrastructure honest.** The relay runs on our infrastructure, not the wearer's (model inference on Nebius Token Factory); wearer self-hosting is the next revision, scoped rather than claimed.
5. **Verifying the Token Factory Omni audio payload format** (the week-1 spike) — the real call is wired, with its request contract covered by a mocked-provider test; a keyless stub keeps the demo runnable without a key. The v1 demo takes the stub path so the turn pipeline is exercised without a live provider call.
6. **Making the demo honest without a speaker.** A channel with no audio output can leave a room assuming the wrong thing — so the demo shows the friend's side as text in the relay's wire log rather than leaving it to the room to guess.

## Accomplishments that we're proud of

- **A working channel the wearer can feel on hardware everyone owns.** A message arrives, the phone plays the arrival cue, the working ticks, the braille cells, the end-of-message close — the whole turn journey, with the same timing the wrist firmware would use. This is not a mock of the channel; it is the channel, on a dev band.
- **A single timing source shared by construction.** One JSON generates the phone feel-tool, the firmware header, the Python consumer, and the ladder doc's demo table; a drift guard refuses any hand edit to a generated block.
- **A relay that enforces the right behavior by default.** Queue-don't-interrupt, working-while-waiting, close-before-release, mark-after-play redelivery — made real in the relay seam and the turn timeline, with a threaded concurrency guard so concurrent arrivals never lose or duplicate a message.
- **A refusal path that is loud and sender-visible.** A full queue answers 429 with a reason; the phone shows a plain-language "busy" note and keeps the drafted text; a live queue badge shows how close the queue is to refusing; health surfaces the rejection count and rate.
- **A model inside the channel, not beside it.** MediaRecorder → base64 → `POST /inject/audio` is the designed hearing layer, held as asset. What the demo proves is the other direction: a live NVIDIA open model on Nebius Token Factory composing the line a wrist reads, through the relay's one turn pipeline — the exact code path, gate, and timing any message takes.
- **Honest scope.** The built things are proven; the wrist hardware, chord input, hardware-gated mic, and wearer-hosted relay are scoped and de-risked — and the submission says so in the same sentence that claims what is built.

## What we learned

- **The channel is the product, not the form factor.** A vibration motor that plays language is the same channel on a phone or a wrist — that is what made this buildable without the hardware.
- **Honesty is a credibility strategy, not a modesty strategy.** A reviewer can hold the real claim in one sentence — and the honest claim is already impressive.
- **The hardest problems went away by removal, not by solving.** Removing sound output removed echo cancellation, wake word, and TTS from the critical path.
- **Courtesy has to be architectural when the channel is serial.** The wearer, not the sender, decides when the next message begins.
- **A demo can lie by implication.** With no speaker in the room, the friend's reply is text in the relay log — show it, or the room will assume the wrong thing.

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

*Every claim is reproducible: see [JUDGE_REPRO.md](https://github.com/razukc/ziv/blob/main/JUDGE_REPRO.md); the claims-vs-code audit trail is [HONESTY_CHANGELOG.md](https://github.com/razukc/ziv/blob/main/HONESTY_CHANGELOG.md).*

## Sources

- **"~2.4 million Americans live with combined hearing and vision loss"** — Helen Keller National Center, DeafBlind Awareness Week 2026 ([helenkeller.org/dbaw2026](https://www.helenkeller.org/dbaw2026/)).
- **"~45–70k at the deaf-blind core"** — HKNC's data summaries: the classic ~45–50k estimate, ~70k per the HKNC summary on Wikipedia, and the HKNC's own ACS 2022 analysis ([helenkeller.org/hknc](https://www.helenkeller.org/hknc/)), ([ACS 2022 analysis](https://www.helenkeller.org/american-community-survey-acs-2022-data-on-people-who-are-deafblind-2024/)), ([Wikipedia summary](https://en.wikipedia.org/wiki/Helen_Keller_National_Center_for_Deaf-Blind_Youths_and_Adults)).
- **"Refreshable braille displays ($1,500–$12,000)"** — the low end from Helen Keller Services' five-display comparison, $1,499–$3,695 for 40-cell units ([helenkeller.org](https://www.helenkeller.org/40-cells-to-empowerment-a-comparison-of-five-braille-displays-to-fortify-your-success-in-2023/)); the high end from Hackaday's 80-cell build analysis ([hackaday.io](https://hackaday.io/project/191181-electromechanical-refreshable-braille-module)) and the ≈$35/cell economics in a ScienceDirect review ([sciencedirect.com](https://www.sciencedirect.com/science/article/pii/S0141938225001702)).
- **"Braille keyboards ($239–$349) are input-only"** — Hable One's product page ([iamhable.com](https://www.iamhable.com/en-am/products/hable-one-keyboard)) and the NFB's review at $350 ([nfb.org](https://nfb.org/blog/hable-one-quality-braille-keyboard-your-smartphone)).
- **Early-years practice (cues mark start and end, waiting stays legible, the wearer releases)** — "How to support a child with deafblindness in their early years," created by **Sense UK**, published by **Insight** (Jan 2025) ([insightdeafblind.org](https://insightdeafblind.org/resource/how-to-support-a-child-with-deafblindness-in-their-early-years)).
- **The practice's reach ("Sense UK in Nepal")** — the same organisation's global sister charity, **Sense International**, runs deafblindness programmes in Nepal (and seven other countries), including educator training and day centres ([senseinternational.org.uk](https://www.senseinternational.org.uk/our-work/where-we-work/our-work-in-nepal/)).
- **Tactile name signs (the name-mark's grounding)** — the protactile literature: "Protactile Language, Modality, and Community," Annual Review of Linguistics ([annualreviews.org](https://www.annualreviews.org/content/journals/10.1146/annurev-linguistics-011724-121536)).
