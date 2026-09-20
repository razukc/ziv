# Devpost Submission — Ziv (DRAFT)

> **Track: Best Apps and Agents.** Copy-paste the sections into the Devpost project page when the submission goes live. The project ships under the working title **Ziv** — final naming authority rests with the deaf-blind community (week-6 sessions). Lines marked *(planned)* describe the next revision (wrist hardware + fuller agent); they are not claimed for this submission. House rule from the plan: **no clinical or efficacy claims** — the claim is "a working prototype of a new channel," not therapy.

---

## Project Name

Ziv *(working title — the final name is validated with, or given by, the deaf-blind community)*

## Tagline

Hears for people who can't hear, speaks braille on their skin.

## Short Description (one-liner)

Ziv is a phone-based AI companion for deaf-blind users: NVIDIA Nemotron-3-Nano-Omni on Nebius Token Factory hears the world, and the phone's vibration motor plays the reply as braille patterns a deafblind wearer can feel — no screen, no sound.

---

## Description (paste into "Description" field)

### The Problem

~2.4 million Americans live with combined hearing and vision loss (~45–70k at the deaf-blind core), and almost nothing is built for them:

- **Refreshable braille displays cost $1,500–$12,000** — and have no microphone, no agent, no always-on awareness.
- **Braille keyboards (Hable One, $239–$349) are input-only** — no output channel, no brain.
- **Research prototypes** have played braille through phone vibration for 15 years (V-Braille, HoliBraille, BrailleBand) — none shipped, because the missing piece was a brain that could *hear*.
- **"AI pins" serve eyes and ears** — useless to someone who cannot see or hear the reply.

The gap: **no existing product pairs a haptic braille output channel with an AI that can hear.**

### Our Solution

Ziv (working title) is a phone-based AI companion for deaf-blind users: NVIDIA Nemotron-3-Nano-Omni on Nebius Token Factory hears the world, and the phone's vibration motor plays the reply as braille patterns on the wearer's skin — no screen, no sound, nothing for the room to see or overhear.

1. **Hears the world.** A sighted friend speaks; the phone's mic sends the audio to Nemotron-3-Nano-Omni on Nebius Token Factory — audio in, text out, one model transcribes *and* understands.
2. **Speaks braille.** The reply is rendered as Grade-1 braille and played as *temporal braille* — one letter at a time as vibration dot-patterns, with pause/replay/skip/speed controls.
3. **Acts while they're away.** Scheduled relay jobs buzz reminders unprompted — the always-on assistant beat, proven by a cron log. *(prototype has a scheduled-job skeleton; the full beat is the next build step)*
4. **Private by physics.** Nothing to overhear, nothing to glance at: a message vibrates on the wrist/phone and is invisible to the room. The mic is push-to-talk (not always-on listening).
5. **A cheaper device class against a more expensive one.** The wrist hardware (for the next revision) is ~$40 BOM — against $1,500–$12,000 refreshable braille displays.

### Why It Matters

- **A ~$40 device against a $1,500–$12,000 device class**, for a population no mass-market product is built for.
- **Dignity, not just access:** for people who already depend on others for information, the device that tells you things *without telling the room* is a different kind of assistant.
- **NVIDIA open models doing real work:** Omni hears — one model, audio-native, on Nebius Token Factory.
- **The channel doubles as the identity:** at boot and before every unsolicited message, the phone plays its name — Z-I-V spelled in vibro-braille (heavy-light-heavy) — a haptic "name mark," the same way DeafBlind communities identify people by tactile signs rather than descriptions.

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
- **End of message** — four ticks descending (200→140→90→50 ms), the exact mirror of the booting pattern's ascent. Until it plays, the silence after a message's last letter was indistinguishable from the pause before the next one.

Invariant 4 became the relay's first real behavior, proven in code: **queue, don't interrupt.** If a message arrives while the wearer is mid-playback, it may announce itself (the "new message" cue) but its content waits; when the event closes — the end-of-message close has played — the queue releases oldest-first, and every queued message still opens with its who→why prefix (invariant 1 holds for queued content too). The wearer, not the sender, decides when the next message begins.

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

- **Hears** — a friend's speech understood by Nemotron-Omni on Nebius Token Factory; no competitor has a speech-in path at all.
- **Speaks their literacy** — temporal braille on the skin; no pins, no screen, no audio.
- **Acts while they're away** — scheduled agent jobs; no competitor ships an agent at all.
- **At a ~$40 BOM (wrist hardware, next revision)** — against $239–$4,500+ across the table.

None of the five is the enemy — each validates one pillar. The combination is the submission.

*Sourcing: Dot Watch discontinuation and 4-cell detail — [AFB review via Dot Inc. news](https://www.dotincorp.com/en/news/27); OrCam pricing — [dealer listings](https://lowvisionsource.com/product-category/lowvisionwearabledevices-com/orcam/) and [AFB Accessworld (MyEye 2.0 at $4,500)](https://afb.org/aw/19/8/15066).*

---

## Key Technologies Used

- **NVIDIA Nemotron-3-Nano-Omni** — audio in → text out; the hearing layer, on Nebius Token Factory
- **Nebius Token Factory** — inference for the Omni model; the hearing layer runs on Nebius
- **FastAPI + WebSockets** — the thin relay: WSS gateway, per-device auth + allow-list, memory files, inbox, cron/heartbeat skeleton
- **The phone Vibration API** — the wearer feels the reply (Android Chrome); the wrist hardware (ESP32-S3 + DRV2605L + 6 LRA motors) is the next revision
- **ESP32-S3 N16R8 + DRV2605L + 6 LRA motors** — the next revision's hardware (~$40 BOM), built for but not shipped in this prototype

---

## How We Built It

### Architecture

```
[phone: Android Chrome PWA]
  mic ──► MediaRecorder (push-to-talk only) ──► base64 audio
  Vibration API ◄── vibro-braille + attention patterns
        │  text JSON + binary audio frames over WSS
        ▼
[relay — thin FastAPI service]
  WS gateway (per-device key + device allow-list; egress allow-list)
  audio → Token Factory Omni (hearing, Nemotron-3-Nano-Omni)
  memory: head.md + wearer memory files + capped inbox
  cron/heartbeat skeleton: scheduled jobs fire while nobody is "chatting"
        ▼
[Nebius Token Factory — NVIDIA open models]
  Nemotron-3-Nano-Omni  (audio in → text out)
```

### Design Decisions

1. **No speaker, by design.** The wearer can't hear one — and removing it deletes echo cancellation, wake word, and the TTS pipeline: the entire hard-problem list of voice wearables. The output channel is a vibration motor.
2. **Temporal braille, Grade 1.** The same alphabet braille readers already know, played as rhythm instead of shown as pins. Word-shape corner cues (space, capital, number sign) from day one; pacing is a first-class control.
3. **A haptic name mark.** The phone identifies itself by spelling its name in vibro-braille (Z = four motors, heavy; I = two motors, light; V = four motors, heavy — the mark ends decisive, the same heavy-light-heavy arc "Raz" would have played). Grounded in how DeafBlind communities use tactile name signs: the name is a felt pattern, not a label.
4. **Push-to-talk mic (this prototype).** Audio capture only on the mic button — not always-on listening. The wrist hardware's hardware-gated mic (ESP32 pin) is the next revision.
5. **The timing spec is generated, never hand-edited.** `docs/haptic-timing.json` is the single source of truth; seven consumers are generated from it (phone feel-tool + firmware header), so the phone and the wrist play identical patterns by construction. The drift guard fails on any hand edit.
6. **Durable wearer state.** Memory files + a persistent, capped inbox: a message arriving with no band attached is stored, not dropped, and delivered as a full event on the next attach. Mark-after-play: redelivery, never loss.
7. **Honest scope for the hackathon.** This submission is a phone-based prototype to the Best Apps and Agents track. The full private, wearer-controlled personal AI system (wrist device with hardware-gated mic + wearer-hosted relay) is the next revision. The haptic output is private by physics; the mic is push-to-talk; the relay runs on Nebius infrastructure in this prototype.

---

## What We Learned

*(to be written as the build progresses — see docs/HAPTIC_COMPANION_PLAN.md milestones and CHANGELOG.md)*

## What's Next

1. **Wrist hardware (next revision)** — ESP32-S3 + DRV2605L + 6 LRA motors, ~$40 BOM; the phone prototype already generates the firmware header from the same timing JSON the phone uses.
2. **Hardware-gated mic** — the ESP32 pin; push-to-talk becomes a physical property, not a software choice.
3. **Wearer-hosted relay** — the wearer runs their own relay so their data is under their control (the next revision's honest answer to "private / data under your control").
4. **Scheduled-job beat (this sprint, week 3)** — the relay fires an unprompted reminder while nobody is "chatting"; the always-on demo beat, proven by a cron log.
5. **Spoken replies (v2)** — TTS on the relay, so the friend hears the wearer's answer.
6. **Grade 2 contractions** — 20–40% fewer cells per message, tuned with braille readers.
7. **Per-contact people-marks (v2)** — a known contact's own tactile cue before their message.
8. **On-device practice mode (v2)** — the device plays a letter, the wearer answers on the chords; sensory play with no instructions.

---

## Devpost-Specific Answers

### What hackathon track are you in?

Best Apps and Agents Track

### What does your project do?

Ziv (working title) is an AI companion app for deaf-blind users. A sighted person speaks; Nemotron-3-Nano-Omni on Nebius Token Factory transcribes and understands in one model; the reply plays as braille vibration patterns on the wearer's phone — no screen, no sound, nothing for the room to see or overhear. The wearer can reply, and scheduled relay jobs deliver reminders unprompted. The full private, wearer-controlled system (wrist device with hardware-gated mic + wearer-hosted relay) is the next revision; this submission is a phone-based working prototype demonstrating the always-on companion interaction loop, powered by NVIDIA open models on Nebius.

### What makes your project unique?

No existing product pairs a haptic braille output channel with an AI that can hear. Braille displays ($1,500–$12,000) don't hear; braille keyboards ($239–$349) don't speak; existing haptic wristbands (Neosensory, Dot) give awareness or pins, not language with a brain. Ziv is built from the combination only this stack enables: an omni-modal NVIDIA model that takes audio natively (Nemotron-3-Nano-Omni on Token Factory) and a phone's vibration motor that speaks braille. And the interaction design is grounded in the field's own guidance rather than intuition: four invariants adopted from early-years deafblind practice (Sense UK, via Insight), with the lifecycle patterns and the queue-don't-interrupt rule already enforced in code and tests.

### What challenges did you face?

1. **Naming for the audience:** "Tact" was too literal (withdrawn); "Raz" was a perfect haptic mark but its word collided with RAZ Mobility, an established assistive-tech company for blind users. Ten names screened in total — every sensory-feeling word collided with an assistive-tech incumbent. The trail produced the rule: the mark is the name, the word is a handle chosen by cost, not meaning. The submission ships as "Ziv (working title)" — final naming authority rests with the deaf-blind community.
2. **Rendering braille as rhythm:** cell → dot bitmask → vibration waveform timing, with pacing/skip/replay as first-class controls.
3. **Keeping the always-on economics honest:** the prototype runs on our Nebius account; the wearer does not yet self-host or control their data — that is the next revision, scoped honestly rather than claimed.
4. **Avoiding voice-wearable hard problems entirely by removing the speaker** (no AEC, no wake word, no TTS in the critical path).
5. **Verifying the Token Factory Omni audio payload format** (the week-1 spike, with a relay-side STT fallback pre-decided) — the real TF call is wired and tested; a keyless stub keeps the demo runnable without a key.
6. **Grounding the interaction design in practice rather than intuition:** adopting Sense UK's early-years deafblind guidance (via Insight) as design law exposed two missing patterns — a "working" cue and an end-of-message close — and produced the queue-don't-interrupt rule. The haptic channel is serial, so courtesy has to be architectural.

### What technologies did you use?

NVIDIA Nemotron-3-Nano-Omni, Nebius Token Factory, FastAPI, WebSockets, Android Vibration API, ESP32-S3 (ESP-IDF, C), DRV2605L, LRA vibration motors, I2S MEMS microphone. *(The wrist hardware — ESP32-S3 + DRV2605L + 6 LRA motors — is the next revision, not shipped in this phone-based prototype.)*

---

## Demo Video Outline (≤3 min)

1. **0:00–0:20** — the gap: price cards ($4,000 display / $349 keyboard / ~$40 Ziv).
2. **0:20–1:10** — the conversation: a friend speaks, the phone plays braille, the wearer replies; relay log + Omni telemetry on screen.
3. **1:10–1:50** — the stack: Omni hears on Token Factory, the relay routes through turn/gate/queue, the phone feels it. The timing spec generated from one JSON; the drift guard.
4. **1:50–2:30** — private by physics: a message vibrates on the phone, invisible to the room; push-to-talk mic; the relay runs on Nebius in this prototype, with the wearer-hosted relay + hardware-gated wrist as the next revision (honest scope).
5. **2:30–3:00** — the ask: "a new channel for people mass-market product ignores."

---

## License

Apache License 2.0 — mirrors the repo's [LICENSE](LICENSE).
