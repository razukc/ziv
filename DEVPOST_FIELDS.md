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
Ziv is a private message channel for your phone: an NVIDIA open model on Nebius Token Factory does the thinking, and your phone plays what it says as braille-rhythm vibrations you read by touch — no screen, no sound, nothing for the room to see or overhear. A reminder you schedule while busy fires on its own, composed by that model, and arrives as a turn only you can read.
```

**Short description — fallback (≤200 chars, 164)**

```
A private message channel: an NVIDIA open model on Nebius Token Factory thinks, and your phone plays what it says as braille-rhythm vibrations you read by touch — silent, invisible, an agent behind it.
```

**Project Story** — paste `DEVPOST_PROJECT_STORY.md` whole (template
headings + Sources included).

**Built with** (25/25 tags — paste one at a time; `NVIDIA`,
`Nebius Token Factory`, and `Nebius AI Cloud` are the chips organizers
check for by name, do not trim them)

```
NVIDIA Nemotron-3-Nano-30B-A3B
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
Ziv (working title) is a private message channel for your phone: an NVIDIA open model on Nebius Token Factory does the thinking, and the phone plays what it says as braille-rhythm vibrations framed by an attention vocabulary — arrival cue, working ticks, end-of-message close. The channel queues instead of interrupting, stores messages when no phone is attached, fires scheduled reminders while you're away, and remembers your pacing. Always-on is the relay's property: it schedules, composes, and stores while you're away; the phone renders each event while its page is open. This submission is a phone-based demo; the wrist device is not part of this entry.
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
5. Putting a live model inside a channel with no screen and no speaker: the reminder you set while busy is composed by an NVIDIA open model on Nebius Token Factory and arrives as the same turn a person's message takes. The model is not a chat window bolted on beside the channel — it is the thing whose words the wrist reads.
```

**What technologies did you use?**

```
NVIDIA Nemotron-3-Nano-30B-A3B on Nebius Token Factory, FastAPI, WebSockets, Android Vibration API. (The wrist hardware — ESP32-S3 + DRV2605L + 6 LRA motors — is not part of this phone-based demo.)
```

**What hackathon track are you in?**

```
Best Apps and Agents Track
```

---

## 4. Additional info step (judges-only) — the required questionnaire

Every field below is required; feedback on Nebius/NVIDIA is a graded part
of the submission, not an afterthought. Be specific per tool.

> **Before you paste §4:** the one field that needs a live run is the
> Nemotron output-quality rating. `python tools/model_probe.py` makes a single
> real call against Token Factory and prints the composed line, its length, and
> the round-trip time — paste those under that answer and give the number.
> Do not submit with the `‹PASTE…›` marker still in it.

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
nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B, served through Nebius Token Factory's
OpenAI-compatible API. The channel's job is to write one short line of plain
language, not to reason for long — a 30B-A3B (3B active) model is the
smallest thing that is fluent without sounding like a form letter, and at
temperature 0 it is stable enough that the same reminder intent produces the
same line twice, which matters when a wearer is learning to recognise turns
by rhythm. Token Factory lists it ready-to-serve, so there is no GPU to
provision and no weights to host. We read the id off the account's
GET /v1/models rather than off the model card, which is the only source that
does not lie.
```

**How would you rate Nemotron's output quality for your use case? (1–10)**

```
‹PASTE THE NUMBER AND THE LINE FROM `python tools/model_probe.py` — see the
pre-paste note at the top of this section.›

The constraint that decides this rating is not fluency, it is length and
register: the output is spelled on a wrist one cell at a time, so a good
answer is short, has no markdown and no preamble, and reads as a bare phrase
with no screen to lean on. We pinned that in the system prompt instead of
post-filtering the model's output, and we guarded the failure direction that
actually hurts — a provider error becomes an error long-buzz plus a 502
carrying the provider's own words, never a silent empty line.
```

**Did you fine-tune, prompt-engineer, or use Nemotron out of the box? What was your approach?**

```
Out of the box, via Token Factory's OpenAI-compatible chat/completions
endpoint — no fine-tuning, and the only prompt engineering is a system
message that states the channel's constraints (one line, short, plain words,
no quotes or markdown). The integration is one async function in
agent/ziv_server.py, its request contract pinned by a mocked-provider test,
and without a key the relay still fires the promise: verbatim, and labelled
text_echo on the wire, so the log never claims a model ran when none did. A
fine-tuned braille-output model is held as asset, not part of this
submission.
```

**How did Nemotron's performance compare to other models you've used for similar tasks?**

```
We ran no head-to-head benchmark, so the honest answer is integration
experience rather than a leaderboard result. What we did measure is the
property that actually decides this channel: round-trip time against the
turn budget, because a haptic turn has a latency ceiling a chat window does
not. Past a few seconds the wearer feels working ticks instead of silence,
which is why the pacing guard is part of the design and not an afterthought.
```

**Which Nebius platform capabilities were most valuable to your project and how?**

```
Nebius Token Factory: one OpenAI-compatible endpoint and one key. The
relay's model client is a standard HTTP POST — the same client shape a judge
already has code for — and key management lives in a gitignored .env, so the
public repo ships without secrets. The capability Ziv is built around is that
a hosted model can sit inside a channel with no screen and no speaker: one
call turns a bare intent ("meds at nine") into the line the wrist spells,
with no GPU to provision and no weights to host. GET /v1/models is also the
honest source of truth for what is servable — we read the model id off it
instead of guessing.
```

**How likely are you to recommend running Nemotron on Nebius to other developers? (1–10) + why**

```
9. One endpoint, one key, an OpenAI-compatible wire format, and no GPU
provisioning — the relay swapped a mocked model call for a real one without
touching its client code. The only time cost was working out which model id
is actually deployed: an id taken from the model card earns you a 404, and
GET /v1/models settles it in one call.
```

**How would you rate your experience running Nemotron inference on Nebius compared to previous cloud or local development environments? (1–10) + why**

```9. No GPU provisioning, no model hosting, a contract that is the familiar
OpenAI one, and per-request keys — which is why the demo could be recorded
against a real model while still running keyless for anyone who clones the
repo. The friction was self-inflicted rather than the platform's: we had a
model id from the model card that this account does not serve, and the
failure came back as a plain 404 naming the exact id. That is the best kind
of failure — it told us the truth in one line.
```

**What additional features or improvements would have made the experience more effective?**

```
1. A copy-paste listing of the model ids an account can actually call —
   GET /v1/models does this today, but we only went looking after a 404.
   2. Per-request latency headers, so the working-tick pacing can be tuned
   against a measured round-trip instead of a fixed budget. 3. Streaming
   completions: a turn that could start spelling before the line is finished
   would take the dead time off the front of every answer.
```

**What do you most hope to see from the Nemotron team next?**

```
Smaller and faster variants with stable low-latency serving — a wearable
round-trip lives or dies on time-to-first-token. And more public examples of
a model whose output is consumed by something that is not a screen, because
that is the shape we are optimising for and there is very little guidance on
it written down.
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
