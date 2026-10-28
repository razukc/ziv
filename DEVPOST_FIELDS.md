# Devpost Fields — the paste cheat sheet

Every remaining Devpost form field as a copy-ready block, in form order.
Companion to `DEVPOST_UPLOAD_CHECKLIST.md` (the map) and
`DEVPOST_PROJECT_STORY.md` (the Project Story block — not repeated here).
All numbers verified against the repo: 199 passed / 4 e2e, 274-check
firmware bench, 49-check ziv_qemu host suite, 27 HAP events.

---

## 1. Project overview step

**Project name**

```
Ziv
```

**Elevator pitch** (100 chars; field allows 200)

```
Messages you can feel. Private by touch, not by broadcast. A haptic channel with an agent behind it.
```

**Thumbnail** — upload `docs/devpost_thumbnail.png` (1500×1000, 3:2,
463 KB; regenerate: `python tools/devpost_thumbnail.py`).

---

## 2. Project details step

**Short description** (326 chars as written — trim to the fallback below
only if the field enforces a cap)

```
Ziv is a private message channel for your phone: an NVIDIA open model on Nebius Token Factory writes the line, and your phone plays it as braille-rhythm vibrations you read by touch — no audio output, no spoken reply. A reminder you schedule while busy fires on its own, composed by that model, and arrives as a turn you feel.
```

**Short description — fallback (≤200 chars, 183)**

```
A private message channel: an NVIDIA open model on Nebius Token Factory writes a line, and your phone plays it as braille-rhythm vibrations you feel. No audio output, no spoken reply.
```

**Project Story** — paste `DEVPOST_PROJECT_STORY.md` whole (template
headings + Sources included).

**Built with** (23/25 tags — paste one at a time; `NVIDIA`,
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

The two part-number chips (`ESP32-S3`, `DRV2605L`) are deliberately
absent. They name specific silicon for the next revision, and in a chip
row that reads as delivered hardware — the honest chips are the platform
(`ESP32`, `ESP-IDF`, `Embedded C`), whose firmware is in this repo.

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
2. Making waiting legible: working ticks during the round-trip, a felt close at the end — latency may be slow; the channel is designed to say it is working.
3. Courtesy as architecture: the serial channel cannot interrupt, so the queue, the 429 refusal, and the release semantics live in the relay, not the UI.
4. Keeping the infrastructure honest: the relay runs on our infrastructure; wearer self-hosting is the next revision.
5. Putting a live model inside a channel whose wearer-facing output is vibration: the reminder you set while busy is composed by an NVIDIA open model on Nebius Token Factory and arrives as the same turn a person's message takes. The model is not a chat window bolted on beside the channel — it is the thing whose words the phone plays.
```

**What technologies did you use?**

```
NVIDIA Nemotron-3-Nano-30B-A3B on Nebius Token Factory, FastAPI, WebSockets, the Android Vibration API — plus the ESP-IDF firmware module that plays the same generated timing (274 host checks against a mock driver). No wrist board is flashed for this demo.
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
Zip of the current submission tree (minus gitignored
wearer state), or a PDF of JUDGE_REPRO.md if a single-document proof is
preferred.
```

**Which model(s) did you use, and why did you choose that size/variant?**

```
nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B, served through Nebius Token Factory's
OpenAI-compatible API. The channel's job is to write one short line of plain
language, not to reason for long — a 30B-A3B (3B active) model is small enough
to answer without a long reasoning pass and fluent enough not to sound like a
form letter, and a short line is what a wearer learning to recognise turns by
rhythm can hold. Token Factory serves it on demand, so there is no GPU to
provision and no weights to host. We read the id off the account's
GET /v1/models rather than off the model card, which is the only source that
does not lie.
```

**How would you rate Nemotron's output quality for your use case? (1–10)**

```
9. The constraint that decides this rating is not fluency, it is length and register: the output is spelled to a wearer one cell at a time, so a good answer is short, has no markdown and no preamble, and reads as a bare phrase with no visual formatting to lean on. We put that in the system prompt, then measure the composed line with the same spelling the band plays: a line that does not fit 12 cells is re-asked or refused as `too_long`, never sliced, and digits are respelled as words because the band has no cell for one. A compose failure never plays an empty line — the judge-key path answers 502 with the provider's own words, and the scheduled path falls back to the intent as `text_echo`; the error long-buzz belongs to a failed turn on the band, not a failed compose.
```


> This is the saved answer in the Devpost form. The 0.63 s probe and the
> 10.8 s scheduled turn are from the 2026-10-27 live run recorded in
> `agent/VM_ONLINE.md`; there are no placeholder slots to fill before paste.

**Did you fine-tune, prompt-engineer, or use Nemotron out of the box? What was your approach?**

```
Out of the box, via Token Factory's OpenAI-compatible chat/completions
endpoint — no fine-tuning. The prompt engineering is a system message that
states the channel's constraints (one line, short, plain words, no quotes or
markdown), plus two short corrective retries when a line does not fit the
band's 12 cells. The integration is one async provider call in
agent/ziv_server.py, its request contract pinned by a mocked-provider test;
without a key the relay still fires the promise, verbatim, labelled
`text_echo` on the wire, so the log never claims a model ran when none did. A
fine-tuned braille-output model is held as asset, not part of this
submission.
```

**How did Nemotron's performance compare to other models you've used for similar tasks?**

```
We ran no head-to-head benchmark, so the honest answer is integration
experience rather than a leaderboard result. What we did measure is the
property that decides this channel: a live provider probe answered in
0.63 s, and scheduled turns played in about 10.8 s end to end, playback
included. Past a few seconds the wearer feels working ticks instead of
silence, which is why the pacing guard is part of the design and not an
afterthought.
```

**Which Nebius platform capabilities were most valuable to your project and how?**

```
Nebius Token Factory: one OpenAI-compatible endpoint and one key. The
relay's model client is a standard HTTP POST — the same client shape a judge
already has code for — and key management lives in a gitignored .env, so the
public repo ships without secrets. The capability Ziv is built around is that
a hosted model can sit inside a channel whose output is vibration, not audio: one
call turns a bare intent ("meds at nine") into the line the band plays,
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

```
9. No GPU provisioning, no model hosting, a contract that is the familiar
OpenAI one, and one account key — which is why the demo runs against a real
model on the VM while the relay still serves a keyless path for anyone who
clones the repo. The friction was self-inflicted rather than the platform's:
we had a model id from the model card that this account does not serve, and
the failure came back as a plain 404 naming the exact id. That is the best
kind of failure — it told us the truth in one line.
```

**What additional features or improvements would have made the experience more effective?**

```
1. A copy-paste listing of the model ids an account can actually call —
   GET /v1/models does this today, but we only went looking after a 404.
2. Per-request latency headers, so the working-tick pacing can be tuned
   against a measured round-trip instead of a fixed budget.
3. Streaming completions: a turn that could start spelling before the line
   is finished would take the dead time off the front of every answer.
```

**What do you most hope to see from the Nemotron team next?**

```
Smaller and faster variants with stable low-latency serving — a wearable
round-trip lives or dies on time-to-first-token. And more public examples of
a model whose output is consumed outside a chat window, because
that is the shape we are optimizing for and there is very little guidance on
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

**Which AI tools have you leveraged while working on this project?**

```
Two different things, so two answers. In the running product the only AI is
nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B on Nebius Token Factory's
OpenAI-compatible endpoint: one async provider call in agent/ziv_server.py
turns a bare intent into the line the band spells, and the same relay still
works keyless for anyone who clones it. In the build, I used an AI coding
assistant (Codebuff) to write and refactor much of the code and documentation
under my direction — its commits carry a Co-Authored-By trailer; the prompts,
scope decisions and final review are mine, and every behavioural claim about
the relay is pinned by the test suite in agent/tests/. That suite is what kept
AI-written code honest: it caught two silent data-loss bugs, a third surfaced
when I probed the seam directly, and the compose tests now pin the 12-cell cap
that one recorded take exposed by dropping a line's last letter.
```

---

## 5. Description → Sources section

The Sources block is already inside `DEVPOST_PROJECT_STORY.md` (§ Sources)
— if Devpost's form offers a separate sources field instead, copy that
section verbatim. Every external claim in the submission has a row there.

---

## 6. Paste-order summary (fast entry)

1. Overview: name → pitch → thumbnail upload.
2. Details: short description → Project Story → Built With (23 tags) →
   repo link (GitHub + Try it out) → video URL → gallery uploads + captions.
3. Devpost-specific questions: five blocks from §3 above.
4. Additional info: submitter/country/age → upload zip → questionnaire
   §4 (Tavily = No) → Builders & Brews city → eligibility checkboxes.
5. Pre-flight against checklist §9, then Submit — before
   **Fri Oct 30, 10:00 AM PT**.
