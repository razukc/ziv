# Devpost Fields — the paste cheat sheet

Every remaining Devpost form field as a copy-ready block, in form order.
Companion to `DEVPOST_UPLOAD_CHECKLIST.md` (the map) and
`DEVPOST_PROJECT_STORY.md` (the Project Story block — not repeated here).
All numbers verified against the repo: 126 passed / 3 e2e, 274-check
firmware bench, 49-check ziv_qemu host suite, 27 HAP events.

---

## 1. Project overview step

**Project name**

```
Ziv
```

**Elevator pitch** (93 chars, cap ~100)

```
Messages you can feel. Nobody else can see. A private haptic channel with an agent behind it.
```

**Thumbnail** — upload `docs/devpost_thumbnail.png` (1500×1000, 3:2,
476 KB; regenerate: `python tools/devpost_thumbnail.py`).

---

## 2. Project details step

**Short description** (331 chars as written — trim to the fallback below
only if the field enforces a cap)

```
Ziv is a private message channel for your phone: a relay hears speech (NVIDIA Nemotron-3-Nano-Omni on Nebius Token Factory) and takes typed messages, then plays them as braille-rhythm vibrations you read by touch — no screen, no sound, nothing for the room to see or overhear — with scheduled reminders that fire while you're away.
```

**Short description — fallback (≤200 chars, 164)**

```
A private message channel: speech in via NVIDIA Nemotron-3-Nano-Omni on Nebius Token Factory, braille-rhythm vibrations out — silent, invisible, an agent behind it.
```

**Project Story** — paste `DEVPOST_PROJECT_STORY.md` whole (template
headings + Sources included).

**Built with** (25/25 tags — paste one at a time; `NVIDIA`,
`Nebius Token Factory`, and `Nebius AI Cloud` are the chips organizers
check for by name, do not trim them)

```
NVIDIA Nemotron-3-Nano-Omni
NVIDIA
Nebius Token Factory
Nebius AI Cloud
FastAPI
WebSockets
Python
Android
PWA
Vibration API
ESP32
ESP32-S3
DRV2605L
ESP-IDF
Embedded C
braille
haptics
accessibility
deaf-blind
assistive tech
uvicorn
pytest
Playwright
HTTP 429
agents
```

**GitHub repo link / "Try it out"**

```
https://github.com/razukc/ziv
```

Paste it under **Try it out** links too — judges land on the README's
"For judges" block. Optional second link (only if the relay is publicly
reachable for the demo window): leave empty otherwise; the video + repo +
JUDGE_REPRO steps carry the demo.

**Video demo link** — YouTube or Vimeo URL of the narrated demo
(see checklist §2: the narrated-beat pipeline names the required tools
with audio). Devpost embeds it at the top of the public page; upload
unlisted-but-linkable and confirm it plays before submitting.

**Image gallery** — 9 shots from `agent/gallery_shots/` (2520×1680, 3:2,
54–234 KB), captions one-per-image from `agent/gallery_shots/CAPTIONS.md`;
suggested pick of 4–6 and the shot table are in checklist §3.

---

## 3. Devpost-specific questions (project details step)

**What does your project do?**

```
Ziv (working title) is a private message channel for your phone: a relay hears speech (Nemotron-3-Nano-Omni on Nebius Token Factory, push-to-talk) and takes typed messages, then plays them as braille-rhythm vibrations framed by an attention vocabulary — arrival cue, working ticks, end-of-message close. The channel queues instead of interrupting, stores messages when no phone is attached, fires scheduled reminders while you're away, and remembers your pacing. Always-on is the relay's property: it schedules, fires, and stores while you're away; the phone renders each event while its page is open. This submission is a phone-based prototype; the wrist device is the next revision. (Composing AI replies from what is heard is the next build step; today the channel carries words — spoken in, tapped out.)
```

**What makes your project unique?**

```
No shipping product turns vibration into a channel that carries language, with an agent behind it: phone buzzes are context-free doorbells; haptic wristbands translate sound into abstract awareness; smartwatches mirror notifications but still demand the eyes for anything that matters. Ziv's combination is new: a serial haptic channel with enforced courtesy (queue-don't-interrupt as relay behavior), a two-layer vocabulary (attention patterns for anyone, braille text for readers), an agent that acts while you're away, and one generated timing source shared by the phone today and the wrist firmware of the next revision (the phone boots its patterns from GET /api/ziv/timing, the serialized generated module).
```

**What challenges did you face?**

```
1. Rendering language as rhythm: cell → dot bitmask → vibration waveform timing, with pacing as the first-class control — and learnability named as the #1 open risk.
2. Making waiting legible: working ticks during the round-trip, a felt close at the end — latency may be slow, never silent.
3. Courtesy as architecture: the serial channel cannot interrupt, so the queue, the 429 refusal, and the release semantics live in the relay, not the UI.
4. Keeping the infrastructure honest: the relay runs on our infrastructure; wearer self-hosting is the next revision.
5. Verifying the Token Factory Omni audio payload format: the real call is wired, its request contract covered by a mocked-provider test; a keyless stub keeps the demo runnable without a key.
```

**What technologies did you use?**

```
NVIDIA Nemotron-3-Nano-Omni, Nebius Token Factory, FastAPI, WebSockets, Android Vibration API, ESP32-S3 (ESP-IDF, C), DRV2605L, LRA vibration motors, I2S MEMS microphone. (The wrist hardware — ESP32-S3 + DRV2605L + 6 LRA motors + I2S MEMS mic — is the next revision, not shipped in this phone-based prototype.)
```

**What hackathon track are you in?**

```
Best Apps and Agents Track
```

---

## 4. Additional info step (judges-only) — the required questionnaire

Every field below is required; feedback on Nebius/NVIDIA is a graded part
of the submission, not an afterthought. Be specific per tool.

**Submitter type / country / project age**

```
Individual  ·  Nepal  ·  New project (first public release; nothing to
describe for the "existing project" essay — leave it empty)
```

**Upload a File (one file, ≤35 MB)**

```
Zip of the verified tree (the submission-v1 tag content, minus gitignored
wearer state), or a PDF of JUDGE_REPRO.md if a single-document proof is
preferred.
```

**Which model(s) did you use, and why did you choose that size/variant?**

```
NVIDIA Nemotron-3-Nano-Omni, served through Nebius Token Factory's
OpenAI-compatible API. Ziv's hearing layer needs one model that takes audio
in natively and returns text — no separate ASR stage, no pipeline to keep in
sync. The nano/omni variant is the smallest audio-native Nemotron, which
keeps the push-to-talk round-trip snappy enough that the wrist feels
working-ticks, not dead air, and its single audio→text step matches the
product's one-relay-turn architecture.
```

**How would you rate Nemotron's output quality for your use case? (1–10)**

```
8. Transcription of short, clear push-to-talk clips was reliable, and
instruction-following through the chat/completions contract was consistent.
It fell short on noisy/clip-edge audio (clipped first syllables on fast
taps), which matters for a push-to-talk flow; we guard it with an error
long-buzz and a manual retry rather than claiming ASR perfection.
```

**Did you fine-tune, prompt-engineer, or use Nemotron out of the box? What was your approach?**

```
Out of the box, via Token Factory's OpenAI-compatible chat/completions
endpoint with an audio payload — no fine-tuning, no prompt engineering
beyond a minimal transcription instruction. The integration is a thin seam
(/inject/audio in agent/ziv_server.py), its request contract covered by a
mocked-provider test, and a keyless stub keeps the demo runnable without a
key. A fine-tuned braille-output model is explicitly scoped as v2, not part
of this submission.
```

**How did Nemotron's performance compare to other models you've used for similar tasks?**

```
Comparable accuracy to the hosted ASR+LLM two-step we'd otherwise bolt
together, in one call and one vendor. Latency on Token Factory was the
pleasant surprise: short clips come back fast enough to sit inside a haptic
turn with felt "working" feedback rather than silence. We did not run a
formal benchmark against other audio models this hackathon — the claim is
integration experience, not a leaderboard result.
```

**Which Nebius platform capabilities were most valuable to your project and how?**

```
Nebius Token Factory: the OpenAI-compatible API meant the relay's model
client is a standard HTTP call with an audio payload — the same client
shape a judge already has code for — and key management lives in a
gitignored .env, so the public repo ships without secrets. The audio-native
serving of Nemotron-3-Nano-Omni is the capability the product stands on:
one hosted model turns push-to-talk speech into the text that drives the
whole haptic turn pipeline.
```

**How likely are you to recommend running Nemotron on Nebius to other developers? (1–10) + why**

```
9. One endpoint, one key, OpenAI-compatible wire format, and an
audio-native Nemotron variant you can't get everywhere; the missing point
is onboarding polish — the audio payload format took a spike to verify
(documented in the repo's honesty changelog).
```

**How would you rate your experience running Nemotron inference on Nebius compared to previous cloud or local development environments? (1–10) + why**

```
8 — no GPU provisioning, no model hosting, the API contract is the familiar
one, and per-request keys made the demo/story split trivial. Docked points
only because docs for the audio request shape required experimentation;
once pinned, it never bit again.
```

**What additional features or improvements would have made the experience more effective?**

```
A documented, copy-paste audio-input example for Omni-style models (base64
WAV in chat/completions) — we reverse-engineered the payload shape;
streaming partial transcripts, so a long clip could feel responsive; and
per-request latency headers to make the working-tick pacing honest against
real round-trip times.
```

**What do you most hope to see from the Nemotron team next?**

```
Smaller/faster audio-native variants with stable low-latency serving
(wearable round-trips live or die on time-to-first-byte); a documented
speech→model-reply loop (audio in, text out, one call) for
on-device-feeling agents; and multilingual audio robustness — Ziv's
sharpest use case is global, and accents are the norm, not the exception.
```

**Did you use Tavily in your project?**

```
No
```

(The Tavily track requires a functional, runtime call to the Tavily API —
Ziv makes none. Answer honestly; do not select Yes.)

**Builders & Brews city / age & eligibility checkboxes** — your call at
submit time; both eligibility boxes must be ticked to save the step.

---

## 5. Description → Sources section

The Sources block is already inside `DEVPOST_PROJECT_STORY.md` (§ Sources)
— if Devpost's form offers a separate sources field instead, copy that
section verbatim. Every external claim in the submission has a row there.

---

## 6. Paste-order summary (fast entry)

1. Overview: name → pitch → thumbnail upload.
2. Details: short description → Project Story → Built With (25 tags) →
   repo link (GitHub + Try it out) → video URL → gallery uploads + captions.
3. Devpost-specific questions: five blocks from §3 above.
4. Additional info: submitter/country/age → upload zip → questionnaire
   §4 (Tavily = No) → Builders & Brews city → eligibility checkboxes.
5. Pre-flight against checklist §9, then Submit — before
   **Fri Oct 30, 10:00 AM PT**.
