# Devpost Submission — Ziv, working title (DRAFT)

> **Status: draft for the Personal AI track submission.** Copy-paste the sections into the Devpost project page when the submission goes live. The project ships under the working title **Ziv** — final naming authority rests with the deaf-blind community (week-6 sessions). Lines marked *(planned)* describe the 8-week build scoped in [docs/HAPTIC_COMPANION_PLAN.md](docs/HAPTIC_COMPANION_PLAN.md); they graduate to plain text only as they are built. House rule from the plan: **no clinical or efficacy claims** — the claim is "a working prototype of a new channel," not therapy.

---

## Project Name

Ziv *(working title — the final name is validated with, or given by, the deaf-blind community in the week-6 sessions)*

## Tagline

Hears for people who can't hear, speaks braille on their skin.

## Short Description (one-liner)

Ziv is a ~$40 wrist-worn AI companion for deaf-blind users: NVIDIA Nemotron-3-Nano-Omni on Nebius Token Factory hears the world, and six vibration motors play the answer as braille on the skin.

---

## Description (paste into "Description" field)

### The Problem

~2.4 million Americans live with combined hearing and vision loss (~45–70k at the deaf-blind core), and almost nothing is built for them:

- **Refreshable braille displays cost $1,500–$12,000** — and have no microphone, no agent, no always-on awareness.
- **Braille keyboards (Hable One, $239–$349) are input-only** — no output channel, no brain.
- **Research prototypes** have played braille through phone vibration for 15 years (V-Braille, HoliBraille, BrailleBand) — none shipped, because the missing piece was a brain that could *hear*.
- **"AI pins" serve eyes and ears** — useless to someone who cannot see or hear the reply.

The gap: **no existing product pairs a haptic braille output channel with an always-on agent.**

### Our Solution

Ziv (working title) is a wrist-worn pin with six vibration motors in a braille-dot layout, six braille chord keys, and one microphone. One NVIDIA model hears for the wearer; their skin is the display.

1. **Hears the world.** A sighted friend speaks; push-to-talk sends the audio to Nemotron-3-Nano-Omni (audio in, text out — one model transcribes *and* understands) on Nebius Token Factory.
2. **Speaks braille.** The reply is rendered as Grade-1 braille and played as *temporal braille* — one letter at a time as dot-patterns on the wrist, with pause/replay/skip/speed controls. *(planned)*
3. **Listens back by touch.** The wearer answers with braille chords on six keys — no phone, no screen, no speech required. *(planned)*
4. **Acts while they're away.** Scheduled jobs on the relay buzz reminders and briefs unprompted — the always-on assistant beat, proven by an overnight cron log. *(planned)*
5. **Private by physics.** Nothing to overhear, nothing to glance at: a message vibrates on the wrist and is invisible to the room. Memory lives on device flash; the relay is self-hosted; the mic is hardware-gated — no always-on listening, ever.

### Why It Matters

- **A $37–46 device against a $1,500–$12,000 device class**, for a population no mass-market product is built for.
- **Dignity, not just access:** for people who already depend on others for information, the device that tells you things *without telling the room* is a different kind of assistant.
- **Always-on:** the relay heartbeat + scheduled jobs act while the wearer is away — the track's full sentence, not a chatbot.
- **NVIDIA open models doing real work:** Omni hears; Nemotron Nano-30B-A3B takes the cheap text turns; routing is cost-aware with a per-device daily token budget.
- **The channel doubles as the identity:** at boot and before every unsolicited message, the pin plays its name — Z-I-V spelled in vibro-braille (heavy-light-heavy) — a haptic "name mark," the same way DeafBlind communities identify people by tactile signs rather than descriptions.

### Grounded in Deafblind Practice, Not Just Built for Deafblind People

The interaction rules are borrowed from the field's own guidance. Sense UK's early-years resource for parents of children with deafblindness (published via Insight, Jan 2025) opens with the problem this device exists to solve: a child with deafblindness receives little information from the world, and what arrives "may be inconsistent and distorted" — so events must be cued before they happen, routines must be consistent, waiting must be patient, and the child must stay in control. What serves that child serves Ziv's wearer: an adult with the same sensory reality deserves a device that holds itself to the same rules. They are written into the plan as six **interaction invariants**:

| Invariant | What it forbids |
|---|---|
| 1. No content without a kind cue first | a buzz that says "something" but not "what kind" |
| 2. Cues mark the start *and* the end of an event | a message that just stops |
| 3. Waiting is legible | dead air during a model round-trip |
| 4. Queue, don't interrupt | an announcement barging into playback |
| 5. Structure is universal, parameters are personal | tuning that silently changes what a cue means |
| 6. Every state transition is feelable | a silent reconnect |

Invariants 2–3 demanded two haptic patterns that did not exist, so we built them into the timing spec (v3) — the single JSON the phone feel-tool and the wrist firmware are both generated from, so they play identical patterns by construction — and exercised them in the hermetic test suite:

- **Processing** — two ticks whose *middle gap is the signal*: 350 ms of silence where the "new message" pattern has 160 ms. An ellipsis: your request is being handled, content follows. Latency may be slow, never silent.
- **End of message** — four ticks descending (200→140→90→50 ms), the exact mirror of the booting pattern's ascent. Until it plays, the silence after a message's last letter was indistinguishable from the pause before the next one.

Invariant 4 became the relay's first real behavior, proven in code: **queue, don't interrupt.** If a message arrives while the wearer is mid-playback, it may announce itself (the "new message" cue) but its content waits; when the event closes — the end-of-message close has played — the queue releases oldest-first, and every queued message still opens with its who→why prefix (invariant 1 holds for queued content too). The wearer, not the sender, decides when the next message begins.

New vocabulary faces a screening protocol, not vibes: the week-6 sessions with braille readers measure whether every pattern is distinguishable from the name mark and from each other (recognition + confusion screens), and a pattern that confuses gets retired rather than tuned. Two more ideas parked for v2 come from the same guidance: per-contact **people-marks** (a known contact's own tactile cue before their message — caller ID generalized to touch) and an on-device **practice mode** (the device plays a letter, the wearer answers on the chord keys — sensory play, no instructions).

*Design rules adopted from published practice, not clinical claims: the guidance informs interaction design; nothing here asserts therapeutic or developmental outcomes — the plan's no-clinical-claims rule applies to every line of this submission.*

### Competition

The nearest assistive wearables each substitute one missing sense — and pay the user back in the other one. Five products closest to Ziv:

| Company | What they ship | The gap for a deaf-blind wearer |
|---|---|---|
| [Neosensory](https://neosensory.com/) (Buzz / Duo) | 4-motor haptic wristband translating ambient sound into vibration — sound awareness for deaf/HoH users and tinnitus therapy; shipping since 2019 | Awareness, not language: abstract vibration patterns — no braille, no speech understanding, no input, no agent. Validates that haptic wrist wearables sell (and it is the incumbent whose name retired our candidate 'Buz'). |
| [RAZ Mobility](https://www.razmobility.com/) | Smartphones for blind/low-vision and senior users — RAZ Memory Cell Phone (sold by Verizon since Jul 2025), SmartVision 3 | Every output path is spoken audio or a screen — a deaf-blind wearer is the one customer they cannot serve. Validates the channels (carriers, Amazon, state AT programs) this device will need too. |
| [OrCam MyEye](https://www.orcam.com/) | AI camera clipped to glasses; reads text and recognizes faces, spoken aloud via bone conduction ($2,450–$4,500) | Best-in-class vision substitution with a *spoken* output — unusable for a deaf wearer; no haptic channel, no conversation, no input keys. |
| [Dot Inc.](https://www.dotincorp.com/) | The closest hardware cousin: Dot Watch put a 4-cell braille display on a wrist (first generation discontinued Jun 2018); today's line is multi-line braille and tactile-graphics pads | A *display*, not an agent: it mirrors phone notifications — no microphone, no hearing, no AI — and static 4-cell pins are slow to read. The watch line's fate is itself evidence that wrist braille needs a brain. |
| [Hable One](https://www.iamhable.com/) | $239–$349 six-key braille keyboard for smartphones | Input in the wearer's own literacy — but the reply comes back as the phone's *spoken* screen reader: no output channel of its own, no haptics, no brain. |

The pattern: **spoken output (OrCam, RAZ Mobility, Hable's screen reader) excludes deaf users; notification mirroring (Dot) excludes agency; abstract vibration (Neosensory) excludes language.** None of the five pairs haptic braille with a device that can hear and act. What only Ziv combines:

- **Hears** — a friend's speech understood by Nemotron-Omni; no competitor has a speech-in path at all.
- **Speaks their literacy** — temporal braille on the skin; no pins, no screen, no audio.
- **Listens by touch** — braille chord input: the only two-way haptic loop in the table.
- **Acts while they're away** — scheduled agent jobs; no competitor ships an agent at all.
- **At ~$40 BOM** — against $239–$4,500+ across the table.

None of the five is the enemy — each validates one pillar (haptic wristbands sell; wrist braille is wanted; braille input is intuitive; the distribution channels exist). The combination is the submission.

*Sourcing: Dot Watch discontinuation and 4-cell detail — [AFB review via Dot Inc. news](https://www.dotincorp.com/en/news/27); OrCam pricing — [dealer listings](https://lowvisionsource.com/product-category/lowvisionwearabledevices-com/orcam/) and [AFB Accessworld (MyEye 2.0 at $4,500)](https://afb.org/aw/19/8/15066).*

---

## Key Technologies Used

- **NVIDIA Nemotron-3-Nano-Omni** — audio in → text out; the hearing layer
- **NVIDIA Nemotron-3-Nano-30B-A3B** — text agent turns (cheap, always-on)
- **Nebius Token Factory** — inference for both models; Serverless Jobs for scheduled briefs
- **ESP32-S3 N16R8** (16 MB flash / 8 MB PSRAM) — the wearable: dual-core FreeRTOS, WiFi
- **DRV2605L I²C haptic driver + 6 LRA motors** — one motor per braille dot
- **6-key braille chord keyboard** — input in the wearer's own literacy
- **FastAPI** — thin self-hosted relay: WSS gateway, per-device auth + allow-list, memory files, cron, egress allow-list
- **ESP-IDF (C)** — firmware: audio capture, haptic sequencer, chord decode, WS client, flash memory

---

## How We Built It

### Architecture

```
[wearable: ESP32-S3 N16R8]
  I2S mic ──► WAV/Opus capture (push-to-talk only)
  6 keys ──► braille chord input
  DRV2605L (I²C) ◄── vibro-braille + attention patterns
        │  text JSON + binary audio frames over WSS
        ▼
[relay on Nebius — thin FastAPI service, self-hosted]
  WS gateway (per-device key + device allow-list; egress allow-list)
  audio → Token Factory Omni (hearing)
  text  → Token Factory Nano-30B-A3B (cheap text turns)
  memory: SOUL.md / MEMORY.md / sessions (device flash + relay history)
  cron/heartbeat: scheduled jobs fire while nobody is "chatting"
        ▼
[Nebius Token Factory — NVIDIA open models]
  Nemotron-3-Nano-Omni · Nemotron-3-Nano-30B-A3B
  (Nemotron-3-Super-120B-A12B optional for hard turns)
```

### Design Decisions

1. **No speaker, by design.** The wearer can't hear one — and removing it deletes echo cancellation, wake word, and the TTS pipeline: the entire hard-problem list of voice wearables. The output channel is a $5 haptic driver.
2. **Temporal braille, Grade 1.** The same alphabet braille readers already know, played as rhythm instead of shown as pins. Word-shape corner cues (space, capital, number sign) from day one; pacing is a first-class control; Grade 2 contractions parked behind a config flag.
3. **A haptic name mark.** The pin identifies itself by spelling its name in vibro-braille (Z = four motors, heavy; I = two motors, light; V = four motors, heavy — the mark ends decisive, the same heavy-light-heavy arc "Raz" would have played). Grounded in how DeafBlind communities use tactile name signs: the name is a felt pattern, not a label.
4. **Hardware-gated mic.** Capture only on push-to-talk or the physical switch; ambient awareness starts from digital events (messages, timers, integrations), never continuous listening.
5. **Cost-aware autonomy.** Voice turns route to Omni only when audio arrived; text turns to Nano; a per-device daily token budget degrades gracefully to the cheaper model.
6. **Security as code, not prompts.** Per-device keys, a device allow-list (the "agent only answers me" beat), and a relay egress allow-list that only ever speaks to Token Factory hosts.
7. **Honest about the research risk.** Reading *temporal* braille on 6 motors is unproven at product level — treated as a research question with a bench protocol (blindfolded sighted proxies, then braille-reader sessions) and a pre-decided fallback ladder down to an attention vocabulary + 30-phrase fixed set.
8. **Interaction invariants from early-years practice.** Six rules (plan §4) adopted from Sense UK's early-years deafblind guidance: cue before content, mark the end, legible waiting, queue-don't-interrupt, universal structure with personal parameters, every transition feelable. First artifacts already built: the two lifecycle patterns in timing spec v3 (generated into feel-tool and firmware header from one JSON) and the relay's message gate, both proven in the hermetic test suite.

---

## What We Learned

*(to be written as the build progresses — see docs/HAPTIC_COMPANION_PLAN.md milestones and CHANGELOG.md)*

## What's Next

1. **Spoken replies (v2)** — TTS on the relay, so the friend hears the wearer's answer.
2. **Grade 2 contractions** — 20–40% fewer cells per message, tuned with braille readers.
3. **BLE caregiver bridge** — setup and a caregiver app without the phone in the critical path.
4. **Braille-style reply distillation** — a LoRA-tuned Qwen3-0.6B/1.7B that compresses replies into short, dot-friendly phrasing (the one thing Token Factory's fine-tuning catalog adds; the weights are ours, which doubles as a data-control argument).
5. **Scene description** — Omni takes image input; an optional capture lens could add "what is in front of me?" in a later revision.
6. **Per-contact people-marks (v2)** — a known contact's own tactile cue before their message; caller ID generalized to touch, from the objects-of-reference practice in the early-years guidance.
7. **On-device practice mode (v2)** — the device plays a letter, the wearer answers on the chords; sensory play with no instructions, the gentlest way to learn the vocabulary.

---

## Devpost-Specific Answers

### What hackathon track are you in?

Personal AI Track

### What does your project do?

Ziv (working title) is an always-on AI companion for deaf-blind users. A sighted person speaks; Nemotron-3-Nano-Omni on Nebius Token Factory transcribes and understands in one model; the reply plays as braille on the wearer's wrist via six vibration motors. The wearer replies with braille chord keys, and scheduled relay jobs deliver reminders as vibration while they're away — with no screen, no speaker, and nothing for the room to see or overhear.

### What makes your project unique?

No existing product pairs a haptic braille output channel with an always-on agent. Braille displays ($1,500–$12,000) don't hear; braille keyboards ($239–$349) don't speak; research vibro-braille prototypes never shipped because nothing could hear. Ziv is built from the combination only this stack enables: an omni-modal NVIDIA model that takes audio natively (Nemotron-3-Nano-Omni on Token Factory) and a $5 haptic driver that speaks braille — at a ~$40 BOM. And the interaction design is grounded in the field's own guidance rather than intuition: six invariants adopted from early-years deafblind practice, with the lifecycle patterns and the queue-don't-interrupt rule already enforced in code and tests.

### What challenges did you face?

1. Naming for the audience: "Tact" was too literal (withdrawn); "Raz" was a perfect haptic mark but its word collided with RAZ Mobility, an established assistive-tech company for blind users. Ten names screened in total — every sensory-feeling word collided with an assistive-tech incumbent (Viz → Viz.ai, Buz → Neosensory Buzz; A2Z was generic). The trail produced the rule: the mark is the name, the word is a handle chosen by cost, not meaning. The submission ships as "Ziv (working title)" — final naming authority rests with the deaf-blind community.
2. Rendering braille as rhythm: cell → dot bitmask → LRA waveform timing, with pacing/skip/replay as first-class controls.
3. Keeping the always-on economics honest: cost-aware model routing with a per-device daily budget.
4. Avoiding voice-wearable hard problems entirely by removing the speaker (no AEC, no wake word, no TTS in the critical path).
5. Verifying the Token Factory Omni audio payload format (week-1 spike, with a relay-side STT fallback pre-decided).
6. Grounding the interaction design in practice rather than intuition: adopting Sense UK's early-years deafblind guidance (via Insight) as design law exposed two missing patterns — a "working" cue and an end-of-message close — and produced the queue-don't-interrupt rule. The haptic channel is serial, so courtesy has to be architectural.

### What technologies did you use?

NVIDIA Nemotron-3-Nano-Omni, NVIDIA Nemotron-3-Nano-30B-A3B, Nebius Token Factory, Nebius Serverless Jobs, ESP32-S3 (ESP-IDF, C), DRV2605L, LRA vibration motors, I2S MEMS microphone, FastAPI, WebSockets, FreeRTOS.

---

## Demo Video Outline (≤3 min) *(planned — full script: plan doc §8)*

1. **0:00–0:20** — the gap: price cards ($4,000 display / $349 keyboard / ~$40 Ziv).
2. **0:20–1:10** — the conversation: a friend speaks, the wrist plays braille, the wearer chords a reply; relay log + Omni telemetry on screen.
3. **1:10–1:50** — always-on: overnight cron log; an unprompted reminder buzzes live; MEMORY.md on flash; a second arrival during playback shows the queue rule — cue now, content after the close.
4. **1:50–2:20** — secure: device allow-list rejecting a stranger; mic hardware switch off; the haptic channel shown leaking nothing.
5. **2:20–2:50** — the stack: Omni hears, Nano reasons, Nebius runs; cost per turn.
6. **2:50–3:00** — the ask: "Private by physics."

---

## License

Apache License 2.0 — mirrors the repo.