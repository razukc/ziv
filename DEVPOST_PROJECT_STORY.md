Ziv is a private message channel for an Android phone: an NVIDIA open model on Nebius Token Factory does the thinking, and the phone plays what it says as braille-rhythm vibrations you read by touch — no audio output, no spoken reply. A reminder you schedule while busy fires on its own, composed by that model, and arrives as a turn you feel.

## Inspiration

Every notification channel you own spends either your eyes or your ears:

- **The screen demands your eyes** — and leaks to everyone near it. Reading a message in a meeting, on a shop floor, or across a dinner table is either rude or impossible.
- **Sound demands your ears — and the room's.** A ring or a spoken reply is a public broadcast in any shared space.
- **The third channel — touch — is wasted.** Phones carry a vibration motor, and most apps use it as a doorbell: one buzz means "something happened," never *what*. Many haptic wearables translate ambient sound into abstract vibration — awareness, not language.

So the contexts where eyes and ears fail — meetings, kitchens, workshops, libraries, night shifts, shared bedrooms — are exactly the contexts where the message doesn't get through.

The gap: **we could not find a shipping product that turns vibration into a channel carrying language, with an agent behind it.**

The channel's manners were not invented for this hackathon — they were adopted. Published early-years deafblind practice (created by Sense UK, published by Insight) says: every event is cued before it happens, cues mark the start *and* the end, waiting is legible, and nothing barges in. Those four invariants are enforced in the relay's code — and they are why the channel is designed to be polite in a meeting, too. The rules come from early-years deaf-blind practice; this build adopts them rather than inventing them.

**The sharpest case.** ~2.4 million Americans live with combined hearing and vision loss (~45–70k at the deaf-blind core), and the market we surveyed is thin: the refreshable braille displays we found ($1,500–$12,000) are output devices, with no microphone and no agent; the braille keyboards we found ($239–$349) are input-only; the consumer haptic wristbands we looked at give awareness or notification mirroring, not language with a brain. For this population the channel is not a convenience — it is the difference between a doorbell and a conversation. Not everyone in this population reads braille, which is why the channel has two layers: the attention vocabulary works from minute one for anyone, and braille text is the layer for readers. For this population, vibration on the skin is a display that can travel anywhere; the model behind the channel gives it a brain those devices lack: **we could not find a shipping product that pairs a haptic braille output channel with a model behind it.** (Hearing what was said — the audio layer — is designed and held as asset, not claimed here. Sources for every number are at the end of this story.)

## What it does

Ziv is a thin relay plus an Android phone with Chrome, used as a display for a channel with no audio output, read by touch:

1. **Thinks for you.** A reminder you set while busy is not a line you typed — it is an intent ("meds at nine"), and when it fires an NVIDIA open model on Nebius Token Factory writes the line the band spells. The model's words enter the relay's single turn pipeline: `run_message_turn`, the same code path, gate, and timing any message takes. The compose call happens before the turn; once the line is ready, the wearer gets the same `processing` ticks every turn uses — a fixed demo wait, not the model's round-trip. *(Push-to-talk audio in is the designed hearing layer — held as asset, not part of this entry.)*
2. **Speaks in rhythm.** Text is rendered as Grade-1 braille cells and played one cell at a time as vibration patterns — at the wearer's own pacing preference, clamped into the spec's envelope. Every event is framed by an attention vocabulary: an arrival cue before content, working ticks while the turn runs, a descending close that says *this message is over*.
3. **Stays polite.** The haptic channel is serial — it cannot interrupt without confusing the reader. If a message lands mid-playback, it announces itself (cue only) and queues; when the current event closes, the queue drains oldest-first, each message opening with its cue. A full queue answers the sender with HTTP 429 and a plain-language note — a loud no, never a silent drop.
4. **Acts while you're away.** Scheduled reminders fire unprompted as their own full turns — arrival cue, working ticks, cells, close. A message that arrives with no phone attached is stored in a capped inbox and replays on the next attach as the same self-naming turn reminders take — mark first, content after. At the 20-message cap the oldest pending message is evicted, counted in health; below the cap, redelivery is the failure mode.
5. **Private by touch, not by broadcast.** Nothing is spoken: a message vibrates against the holder's skin and is not read aloud to the room. In this demo the operator view and relay log show the text, and the phone's motor is not silent; we have not measured its acoustic noise. This build has no microphone; the designed hearing layer is push-to-talk, never always-on.

Concretely, the prototype does this now:

- **Thinks for you.** Schedule an *intent*, not a sentence: `POST /api/ziv/schedule` with `{"intent": "meds at nine"}`. When it fires, the relay asks Nemotron-3-Nano-30B-A3B on Nebius Token Factory for one line within the band's 12 cells, then measures the reply with the same spelling the band plays: a line that fits is played whole — the wire log says `source: text_live` — and a line that does not fit gets two corrective retries, then is refused as `too_long` — never sliced. If the compose fails, the promise still fires as the intent verbatim, labelled `text_echo`, and the log names the path it took; a failed compose does not buzz. Without a key the same `text_echo` path runs, so the log never claims a model ran when none did.
- **Speaks in rhythm.** Grade-1 braille cells, one at a time, at the wearer's persisted pacing preference (an API-set control, clamped into the spec envelope). The attention vocabulary — arrival cue, working ticks, end-of-message close — frames every turn; the error long-buzz is wired to the Omni transcription path (held as asset), and a scheduled reminder opens with its triple-pulse tail.
- **Acts while you're away.** A scheduler loop fires reminders as full turns, proven live by `/api/ziv/ready` + health telemetry — and the schedule is durable like the inbox (atomic JSON, corrupt-tolerant, capped). A restart does not drop a pending reminder; the 64-reminder cap can evict the oldest.
- **Stays polite.** `MessageGate` enforces queue-don't-interrupt; a full queue is a sender-visible 429; the client shows a live queue badge, and re-sends a refused typed or stub message automatically when the freeing close lands on the wire.
- **Remembers the wearer.** Per-wearer memory files (atomic JSON, corrupt-file recovery surfaced in health) plus a capped persistent inbox: stored while no band is attached; mark-after-play, so below the cap redelivery is the failure mode.
- **Boots its timing from one source.** Every pattern the phone plays comes from `GET /api/ziv/timing` — the serialized generated module — so the phone's patterns and the wrist firmware come from one source by construction, not by convention.

**A scene from the demo.** You set an intent — "meds at nine" — and get back to work. Ten minutes later, unprompted, the phone taps the arrival cue, spells the Z-I-V mark, ticks while the relay finishes, and plays the line — **with a funded Nebius Token Factory key, the line a model wrote for you (or, if the model cannot give a line that fits, the intent verbatim, labelled `text_echo`); without a key, that same fallback**. Either way the room hears no spoken reply, and both sides are shown honestly: the words are visible as text in the operator view and relay log, because the demo has to show what the band is playing — a haptic channel has no speaker, and that is the point.

## How we built it

**Key technologies:**

- **NVIDIA Nemotron-3-Nano-30B-A3B on Nebius Token Factory** — text in → the line the band plays; the model behind the agent path this demo runs
- **Nebius Token Factory** — the hosted endpoint the model call goes through; the Omni audio seam is held as asset, not claimed
- **FastAPI + WebSockets** — the thin relay: WS gateway, optional shared-token auth, per-wearer memory files, capped inbox, scheduler loop
- **The Android Vibration API** — the output channel this demo plays on

**Next revision's hardware, not a technology used here:** the wrist device — ESP32-S3 N16R8 + DRV2605L + 6 LRA motors, ~$40 BOM. The firmware in `firmware/haptic_out/` is written against it and bench-tested on the host; no board is flashed for this prototype.

**Architecture:**

```
[phone: Android Chrome PWA]
  (not in this build; held as asset: mic → /inject/audio → Omni transcription)
  Vibration API ◄── braille cells + attention vocabulary
        │  text JSON frames over WebSocket
        ▼
[relay — thin FastAPI service]
  WS gateway (optional shared-token auth; open on the LAN by default)
  intent → Nemotron-3-Nano-30B-A3B on Nebius (writes the line the band spells)  [wire source: text_live, or text_echo on fallback]
  typed text → the relay's one turn pipeline (no model call)
  memory: per-wearer memory files + capped inbox
  scheduler: a poll loop fires reminders while nobody is "chatting" (schedule durable like the inbox)
        ▼
[Nebius Token Factory — NVIDIA open models]
  Nemotron-3-Nano-30B-A3B  (text in → the line the band plays)
```

**Design decisions** — the five that shaped everything else:

1. **Vibration is the message output.** No TTS pipeline, no echo cancellation, no wake word: removing audio output removes the entire hard-problem list of voice wearables — and removes the audio leak. Sound broadcasts; vibration is directed at the holder.
2. **Text as rhythm, in two layers.** Layer one is the attention vocabulary — arrival, working, done, and the error long-buzz wired to the Omni transcription path — the part a wearer feels from minute one. Layer two is the text itself, spelled as Grade-1 braille cells for anyone who reads braille or learns it. Word-shape corner cues (space, capital, number sign) are planned — the prototype plays plain letters (a–z); pacing is the first-class control.
3. **One timing source, generated, never hand-edited.** `docs/haptic-timing.json` generates seven consumers (phone feel-tool + firmware header + Python consumer + ladder tables), so the phone's patterns and the wrist firmware come from one source by construction. A drift guard fails on any hand edit to a generated block.
4. **Courtesy as relay behavior, not a UI hint.** `MessageGate` is the serialization point: while content plays, an incoming message gets its cue only and queues; the wearer releases the queue by closing the event; drained messages play FIFO, each opening with its cue. The close frame that frees the channel is marked on the wire (`free: true`), so the client's auto-redial fires on the frame the wearer feels — not on a timing guess.
5. **Durable state.** Memory files + a persistent, capped inbox: a message arriving with no phone attached is stored and replays as a self-naming turn — mark first, content after. Mark-after-play makes redelivery the failure mode below the cap; at the cap the oldest is evicted, counted in health.

**Push-to-talk and honest scope.** This build has no microphone — the band is compose-and-receive only, and the client says so on its own surface. The designed hearing layer (push-to-talk mic → base64 → `POST /inject/audio` → Omni transcription) is held as asset, with its request contract covered by a mocked-provider test; when it ships, capture happens only while the button is held, never always-on listening. This submission is a phone-based prototype to the Best Apps and Agents track; the full private, wearer-controlled system (wrist device with hardware-gated mic + wearer-hosted relay) is the next revision. The haptic output is touch-only; the demo's operator view shows the text, and the relay runs on our infrastructure, not the wearer's, in this prototype.

## Challenges we ran into

1. **Rendering language as rhythm.** Cell → dot bitmask → vibration waveform timing, with pacing as the first-class control — and with the honest unknown out front: how fast people actually learn to read text by vibration is unproven (the #1 open risk, named under What's next).
2. **Making waiting legible.** A model round-trip is dead air unless the channel says so — so the turn plays working ticks while it waits, and a descending close when it ends. Those ticks are the demo's fixed pacing; the compose call completes before the turn begins.
3. **Courtesy has to be architectural when the channel is serial.** A vibration channel cannot interrupt without confusing the reader, so queue-don't-interrupt became a relay behavior with a bounded queue, a 429 refusal path, and operator-visible rejection telemetry.
4. **Keeping the infrastructure honest.** The relay runs on our infrastructure, not the wearer's (model inference on Nebius Token Factory); wearer self-hosting is the next revision, scoped rather than claimed.
5. **Verifying the Token Factory Omni audio payload format** (the week-1 spike) — the real call is wired, with its request contract covered by a mocked-provider test; a keyless stub keeps the relay runnable without a key. The live relay runs the text path — the intent is composed on Token Factory and the wire log says `text_live` — while the audio seam stays held as asset.
6. **Making the demo honest without a speaker.** A channel with no audio output can leave a room assuming the wrong thing — so the demo shows the friend's side as text in the relay's wire log rather than leaving it to the room to guess.

## Accomplishments that we're proud of

- **A working channel the wearer can feel on an Android phone.** A message arrives, the phone plays the arrival cue, the working ticks, the braille cells, the end-of-message close — the whole turn journey, with the same timing the wrist firmware would use. This is not a mock of the channel; it is the channel, with the demo's fixed processing wait.
- **A single timing source shared by construction.** One JSON generates the phone feel-tool, the firmware header, the Python consumer, and the ladder doc's demo table; a drift guard refuses any hand edit to a generated block.
- **A relay that enforces the right behavior by default.** Queue-don't-interrupt, working-while-waiting, close-before-release, mark-after-play redelivery — made real in the relay seam and the turn timeline, with a threaded concurrency guard so concurrent arrivals are neither lost nor duplicated inside the gate.
- **A refusal path that is loud and sender-visible.** A full queue answers 429 with a reason; the phone shows a plain-language "busy" note and keeps the drafted text; a live queue badge shows how close the queue is to refusing; health surfaces the rejection count and rate.
- **A model feeding the channel, not decorating it.** MediaRecorder → base64 → `POST /inject/audio` is the designed hearing layer, held as asset. What the demo proves is the other direction: a live NVIDIA open model on Nebius Token Factory composing the line the band plays, then handing it to the relay's one turn pipeline — the same code path, gate, and timing any message takes. The compose call itself runs before the turn.
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

*Every code claim is reproducible: see [JUDGE_REPRO.md](https://github.com/razukc/ziv/blob/main/JUDGE_REPRO.md); the claims-vs-code audit trail is [HONESTY_CHANGELOG.md](https://github.com/razukc/ziv/blob/main/HONESTY_CHANGELOG.md).*

## Sources

- **"~2.4 million Americans live with combined hearing and vision loss"** — Helen Keller National Center, DeafBlind Awareness Week 2026 ([helenkeller.org/dbaw2026](https://www.helenkeller.org/dbaw2026/)).
- **"~45–70k at the deaf-blind core"** — HKNC's data summaries: the classic ~45–50k estimate, ~70k per the HKNC summary on Wikipedia, and the HKNC's own ACS 2022 analysis ([helenkeller.org/hknc](https://www.helenkeller.org/hknc/)), ([ACS 2022 analysis](https://www.helenkeller.org/american-community-survey-acs-2022-data-on-people-who-are-deafblind-2024/)), ([Wikipedia summary](https://en.wikipedia.org/wiki/Helen_Keller_National_Center_for_Deaf-Blind_Youths_and_Adults)).
- **"Refreshable braille displays we found ($1,500–$12,000)"** — the low end from Helen Keller Services' five-display comparison, $1,499–$3,695 for 40-cell units ([helenkeller.org](https://www.helenkeller.org/40-cells-to-empowerment-a-comparison-of-five-braille-displays-to-fortify-your-success-in-2023/)); the high end from Hackaday's 80-cell build analysis ([hackaday.io](https://hackaday.io/project/191181-electromechanical-refreshable-braille-module)) and the ≈$35/cell economics in a ScienceDirect review ([sciencedirect.com](https://www.sciencedirect.com/science/article/pii/S0141938225001702)).
- **"Braille keyboards we found ($239–$349) are input-only"** — Hable One's product page ([iamhable.com](https://www.iamhable.com/en-am/products/hable-one-keyboard)) and the NFB's review at $350 ([nfb.org](https://nfb.org/blog/hable-one-quality-braille-keyboard-your-smartphone)).
- **Early-years practice (cues mark start and end, waiting stays legible, the wearer releases)** — "How to support a child with deafblindness in their early years," created by **Sense UK**, published by **Insight** (Jan 2025) ([insightdeafblind.org](https://insightdeafblind.org/resource/how-to-support-a-child-with-deafblindness-in-their-early-years)).
- **The practice's reach ("Sense UK in Nepal")** — the same organisation's global sister charity, **Sense International**, runs deafblindness programmes in Nepal (and seven other countries), including educator training and day centres ([senseinternational.org.uk](https://www.senseinternational.org.uk/our-work/where-we-work/our-work-in-nepal/)).
- **Tactile name signs (the name-mark's grounding)** — the protactile literature: "Protactile Language, Modality, and Community," Annual Review of Linguistics ([annualreviews.org](https://www.annualreviews.org/content/journals/10.1146/annurev-linguistics-011724-121536)).
