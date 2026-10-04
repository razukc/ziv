# Devpost Upload Checklist — Ziv

Team-facing upload guide. Everything maps to files already in this repo —
paste, don't rewrite. Pick **one narrative voice** for the description
fields (recommended: the product-first `DEVPOST_HAPTIC_GENERIC.md`, which
keeps the deaf-blind case in its own section) and stay in that voice for
every field. Before you record or upload, run the gate:

```bash
cd agent && python -m pytest -m "not e2e"   # → 126 passed (3 e2e deselected)
python -m pytest -m e2e                     # → 3 passed (needs Playwright)
```

**Deadline: submissions close Friday, October 30, 10:00 AM PT.** The draft
page's own counter is the source of truth — don't plan a last-day upload.

---

## 1. Field-by-field mapping

| Devpost field | Paste from | Notes |
|---|---|---|
| **Project name** | GENERIC "Project Name" | `Ziv` — keep "*(working title)*" out of the field; the working-title honesty lives in the description |
| **Elevator pitch** (overview step, ~100 chars) | Paste: "Messages you can feel. Nobody else can see. A private haptic channel with an agent behind it." | 93 chars — fits the 100-char cap; it's the GENERIC tagline plus the agent clause |
| **Thumbnail** (overview step) | Upload `docs/devpost_thumbnail.png` | 1500×1000 (3:2), 476 KB; regenerate with `python tools/devpost_thumbnail.py`. Same brand card as the social preview, plus the NVIDIA/Nebius stack line |
| **Short description** | GENERIC "Short Description (one-liner)" | 331 chars as written; a ≤200-char fallback lives in DEVPOST_FIELDS.md if the field complains |
| **Description** | GENERIC **Our Solution → What it does → Why It Matters → A scene from the demo → Use cases** | Keep section order; the Use cases section is the one place the deaf-blind case appears — keep it that way |
| **"What does your project do?"** | GENERIC → Devpost-Specific Answers | Direct paste |
| **"What makes your project unique?"** | GENERIC → Devpost-Specific Answers | Includes the timing-mechanism sentence; keep it |
| **"What challenges did you face?"** | GENERIC → Devpost-Specific Answers (numbered 1–5) | Direct paste |
| **"What technologies did you use?"** | GENERIC → Devpost-Specific Answers | Keep the parenthetical "wrist hardware is the next revision" — it keeps the stack list honest |
| **"What hackathon track are you in?"** | GENERIC → Devpost-Specific Answers | Best Apps and Agents |
| **GitHub repo link** | `https://github.com/razukc/ziv` | Judges land on the README's "For judges" block; the `submission-v1` tag freezes the verified tree. Public-repo requirements are a graded form item — see §6 |
| **"Built with" chips** | NVIDIA Nemotron-3-Nano-30B-A3B, Nebius Token Factory, FastAPI, WebSockets, Android Vibration API, ESP32-S3, DRV2605L, Python | Add chips exactly as listed (ESP32/DRV2605 belong to the next revision — the tech answer already scopes that). NVIDIA + Nebius named here is an explicit organizer ask — don't trim |
| **Demo video** | See shot list below | ≤3 min; the outline is in GENERIC "Demo Video Outline". Name Nebius Token Factory + the NVIDIA model **with audio** on the soundtrack — see §2's recording notes |
| **Screenshot gallery** | See shot list below | 4–6 images, each with its caption — §3 |

Do **not** paste: `HONESTY_CHANGELOG.md` and `JUDGE_REPRO.md` are repo
artifacts (linked from the README the judges will open), not Devpost body
text — but reference them in one line at the end of the description:
*"Every claim is reproducible: see JUDGE_REPRO.md; the claims-vs-code audit
trail is HONESTY_CHANGELOG.md."*

## 2. Demo video shot list (≤3 min, follows GENERIC's outline)

1. **0:00–0:20 cold open** — phone face-down and silenced in a meeting;
   it buzzes; fingers read; nothing visible or audible. Title card:
   "A message only one person receives."
2. **0:20–1:10 the channel** — typed message sends; capture the dev-band
   page wire log top-down: `▶ double-tap (kind cue)` → `▶ processing
   (working)` → `message: <text>` text frame → per-letter `cell` frames →
   `▶ end-of-message (close)`. Then a second send mid-turn: cue only,
   badge count ticks up, auto-replay after the close.
3. **0:20–1:10 (b) the refusal** — keep sending until the badge shows
   `refusing — queue full (8/8)`; show the HTTP 429 and the busy note; then
   the redial: `↻ redial armed — … 3 chances left`, the auto resend on the
   freeing close, `POST ok`.
4. **1:10–1:50 the stack** — the live model. Schedule an *intent* by curl
   (`{"intent": "meds at nine", "fire_at": …}`); the relay calls
   Nemotron-3-Nano-30B-A3B on Nebius Token Factory and plays the line the
   model wrote (`source: text_live` on the wire). Flash
   `python tools/prove.py` — one block with every suite's counts and the
   drift-guard result — and `docs/haptic-timing.json`.
5. **1:50–2:30 the agent acts while you're away** — a finished `text`
   reminder, scheduled by curl, fires unprompted: `reminder: pills`
   narration, Z-I-V cells, `triple-pulse`, close. Then the durability beat:
   kill the relay, restart, `GET /api/ziv/schedule` returns the same
   reminder. Close the tab, send while away → `inbox:stored`; reattach →
   replay arrives as a self-naming turn.
6. **2:30–3:00 who it serves** — the GENERIC Use-cases paragraph (everyday
   contexts, then the deaf-blind case), the ask line, and the repo URL.

Recording notes: capture the dev-band page at desktop width (the wire log
is the star); record phone vibration close-ups with a second angle; keep
each wire-log scroll readable (bump browser zoom to 125%).

**Say the required names out loud.** The organizers' own tip: name Nebius
Token Factory / AI Cloud and the NVIDIA model "clearly — in your demo
video, not just a passing mention." Two scripted paths do this themselves
(SAPI voiceover + ffmpeg mux, per-phase marks kept for re-mixing):

-  `agent/record_full_demo.py` — the **whole §2 outline in one take**
  (cold-open card → channel → the live model beat → refusal → the durability
  beat with a real relay kill/restart → closing card) →
  `demo_full_narrated.mp4` (~110 s). It owns the relay lifecycle on :8787,
  sweeps stray relays, and refuses a poisoned gate. The stack beat schedules
  an intent and shows the relay's own call to Nemotron on Token Factory
  producing the line the wrist spells — `source: text_live`, and the
  narration says that is a live model call. If the key is absent the relay
  still fires the promise, labelled `text_echo`, and the log says so rather
  than claiming a model ran.
- `agent/record_beat_narrated.py` — just the 0:20–1:10 beat against a
  self-started relay on :8787 (`ZIV_FAKE_MODEL_SECONDS=8`) →
  `demo_beat_narrated.mp4`.

`record_beat.py` alone still emits a **silent webm**; use a narrated
pipeline for the upload track. Also treat the video as a pitch per the
same email: lead with the problem, show it working, say who it's for.

## 3. Screenshot gallery (4–6 images, each with a caption)

**Scripted capture:** `cd agent && venv/Scripts/python.exe record_gallery.py`
(POSIX: `venv/bin/python`) records the shots below from the real relay —
same trick as `record_beat.py` — into `agent/gallery_shots/` as 2520×1680
(3:2, 2× DPR) PNGs, one file per numbered item (item 2 in two states, item 3
as a dead-end + recovery pair), plus `gallery_shots/CAPTIONS.md` with the
paste-ready per-image captions. Pick 4–6 of the outputs; every PNG lands
≤5 MB and Devpost-ready. Devpost gives **each uploaded image its own
caption field** — fill every one; captions come from `CAPTIONS.md`.

| # | File (`agent/gallery_shots/`) | Caption (from `CAPTIONS.md`) |
|---|---|---|
| 1 | `01-turn-vocabulary.png` | One turn, the whole vocabulary: arrival cue → working ticks → message → braille cells → end-of-message close, live in the dev-band wire log — while two later messages announce themselves mid-turn and queue instead of interrupting. |
| 2a | `02-badge-queue3.png` | The queue badge in its healthy state — queue 3/8 · reminders 0/64 — polled live from the relay's health endpoint while the current turn plays. |
| 2b | `02-badge-refusing.png` | Queue full: the badge reads refusing — queue full (8/8), the sender gets HTTP 429 with a plain-language busy note, and the refused message arms its redial. A loud no, never a silent drop. |
| 3a | `03-redial-dead-end.png` | The redial's loud dead end: three tries, three refusals — the red note stays on screen until the wearer acts, and the log records the give-up. |
| 3b | `03-redial-lifecycle.png` | Recovery on the same screen: manual send → the note clears → POST ok. The redial fires on the close frame the wearer feels, not on a timing guess. |
| 4 | `04-reminder-turn.png` | An agent turn, unprompted: a scheduled reminder fires as its own full turn — reminder: pills, the Z-I-V name mark spelled in cells, the triple-pulse tail. |
| 5 | `05-health-json.png` | The operator view: GET /api/ziv/health — gate queue and cap, schedule depth and cap, queue-rejection telemetry — the same numbers the badge renders. |
| 6 | `06-test-proof.png` | Every claim reproducible: the hermetic pytest suite's summary line beside the firmware bench suite's — both counts on screen, both green. |
| 7 | `07-fire-while-away.png` | Fire-while-away: with no band attached the relay stores the message (inbox:stored); on reattach the hello reports the pending count and each replay arrives as a self-naming turn — mark first, content after. |

Suggested pick of 4–6: 1, 2b, 4, 5, 7 (the product story) — add 3a/3b if
you want the redial arc, and 6 if you want proof in the gallery.

## 4. Project Story — mapping to GENERIC

The "Project details → About the project" box takes **Markdown** (LaTeX
supported). GENERIC's sections map 1:1 onto the headings Devpost's template
pre-fills — keep Devpost's exact headings, paste GENERIC's bodies under
them, trimming long sub-lists rather than rewriting:

| Devpost heading (template) | Take from GENERIC |
|---|---|
| `## Inspiration` | "The Problem" (notification channels spend eyes/ears; touch is wasted) + one line of the Use-cases grounding (early-years deafblind practice wrote the channel's manners) |
| `## What it does` | "Our Solution" (the 5 numbered capabilities) + "What it does (this submission)" bullet list + "A scene from the demo" |
| `## How we built it` | "Key Technologies Used" + "How we built it" (architecture diagram + the 8 design decisions, trimmed to the 5 strongest) |
| `## Challenges we ran into` | "Challenges we ran into" (the numbered 6) |
| `## Accomplishments that we're proud of` | "Accomplishments that we're proud of" (direct paste) |
| `## What we learned` | "What We Learned" (direct paste) |
| `## What's next for Ziv` | "What's next for Ziv" (wrist revision + the numbered list; keep the open-decision points — learnability, naming) |
| **Built with** (≤25 tags) | NVIDIA Nemotron-3-Nano-30B-A3B, NVIDIA, Nebius Token Factory, Nebius AI Cloud, FastAPI, WebSockets, Python, Android, PWA, Vibration API, ESP32, ESP32-S3, DRV2605L, ESP-IDF, Embedded C, braille, haptics, accessibility, deaf-blind, assistive tech, uvicorn, pytest, Playwright, HTTP 429, agents — add **Nebius Token Factory** and **NVIDIA** as standalone chips; organizers check for them by name |
| **"Try it out" links** | GitHub repo `https://github.com/razukc/ziv` (+ the working-demo URL from §6 if one is hosted) |
| **Image gallery** | 9 shots from §3, each with its caption |
| **Video demo link** | YouTube or Vimeo URL — Devpost embeds it at the top of the public page; upload unlisted-but-public-linkable and confirm it plays |

## 5. Additional info (judges-only) — paste-ready answers

The "Additional info" step is **for judges and organizers** (not public),
and the Nemotron/Nebius feedback questionnaire is a **required** part of
every submission — the organizers' email says so explicitly, not an
afterthought. Be specific per tool ("the docs were confusing" doesn't help
anyone without naming the tool). Paste-ready drafts:

- **Submitter type / country / track / new-or-existing:** Individual ·
  Nepal · **Best apps and agents** · **New** (leave the "existing" essay
  empty).
- **Upload a File (≤35 MB):** a zip of the verified tree (`submission-v1`
  tag content, minus gitignored state) — or a PDF of JUDGE_REPRO.md. One
  file only; zip multiples.
- **The eight required Nemotron/Nebius answers are written once, in
  [DEVPOST_FIELDS.md](DEVPOST_FIELDS.md) §4 — paste them from there.**
  Do not keep a second copy here: two copies of an answer is how a stale
  claim ships. Before you paste, run `python tools/model_probe.py` and fill
  in the output-quality rating marked with the `‹PASTE…›` marker.
- **What do you most hope to see from the Nemotron team next?** → the answer
  is in [DEVPOST_FIELDS.md](DEVPOST_FIELDS.md) §4.
- **Did you use Tavily in your project?** → **No.** (The form notes a
  Tavily-track qualification requires a functional, runtime call to the
  Tavily API — Ziv makes none. Answer honestly; don't select Yes.)
- **Builders & Brews city / age & eligibility checkboxes:** your call at
  submit time; both eligibility boxes must be ticked to save the step.

## 6. Repo URL + working demo (a graded form item)

The Additional-info form asks for a **public repo URL** and states what it
must include — treat it as graded, not a formality. Status of each
requirement in this repo:

- [x] **Approved OSI license** — `LICENSE` is Apache-2.0 (OSI-approved).
- [x] **README with setup instructions** — README "Quick start (dev-band
      relay)" + "For judges" block; keep them current with any code change
      before submitting.
- [x] **Highlight NVIDIA Nemotron usage + where Token Factory accelerated
      the workflow** — README names Nemotron-3-Nano-30B-A3B on Nebius Token
      Factory in the first paragraph, the agent-path row, and Quick start;
      the Additional-info questionnaire (§4 of DEVPOST_FIELDS.md) says it in
      judge-facing words too. The **description and Built With must repeat
      the names** (the email's "impossible to miss" tip) — §1's rows do.
- [ ] **Verify before submit:** repo is public, default branch builds the
      README badges honestly, `submission-v1` tag visible, no secrets
      (`agent/.env` is gitignored — `git status --porcelain` shows no
      `.env`, no `ziv_data/`, no gallery outputs).
- **Working-demo URL (optional, "not required for Physical AI
  submissions"):** only if a relay is publicly reachable for the demo
  window; otherwise leave empty — the video + repo + repro steps carry it.

## 7. Source links to paste (Description → "Sources" section)

Paste the Sources block from the chosen DEVPOST file verbatim — both files
carry the identical list (links re-verified live this submission):

- 2.4M Americans with combined hearing/vision loss — HKNC DeafBlind
  Awareness Week 2026: <https://www.helenkeller.org/dbaw2026/>
- ~45–70k deaf-blind core — HKNC + ACS 2022 analysis + Wikipedia summary
  (three links, as in the block)
- Braille displays $1,500–$12,000 — Helen Keller Services comparison
  ($1,499–$3,695) + Hackaday 80-cell analysis + ScienceDirect ≈$35/cell
- Braille keyboards $239–$349 — Hable One product page + NFB review
- Early-years practice — "How to support a child with deafblindness in
  their early years," created by Sense UK, published by Insight (Jan 2025)
- Sense International's Nepal programme (the practice's reach)
- Protactile name signs — Annual Review of Linguistics (name-mark grounding)

## 8. GitHub social preview (manual step — no API exists)

GitHub offers no REST/GraphQL API for the social preview image (verified:
`POST /repos/{owner}/{repo}/social-preview` → 404; the Settings UI is the
only mechanism). The image is generated and committed so it can never be
lost:

- **File:** `docs/social_preview.png` — 1280×640, rendered from
  `tools/social_preview.py` (real Z-I-V braille dot patterns, tagline,
  judges pointer). Regenerate: `python tools/social_preview.py`.
- **One manual step:** GitHub → repo **Settings → General → Social
  preview → Edit** → upload `docs/social_preview.png` → Save. GitHub
  caches the card; if a shared link still shows the old preview, re-fetch
  with a cache-buster (`?v=2`) or wait a few minutes.

## 9. Pre-flight (final)

- [ ] `pytest -m "not e2e"` → 126 passed (3 e2e deselected); `-m e2e` → 3 passed
- [ ] Video ≤ 3:00, every outline beat present, wire log readable, and
      Token Factory + Nemotron **named aloud** (§2's narrated pipeline),
      uploaded as MP4/WebM with the audio track present in the file
- [ ] Every number in the description matches the repo (126 passed / 3 e2e,
      274-check firmware bench, 49-check ziv_qemu host suite, 27 HAP events
      — JUDGE_REPRO.md is the source of truth)
- [ ] Both deferral sentences intact (AI-composed replies = next build
      step; wrist hardware = next revision)
- [ ] Gallery images uploaded with **every caption field filled** (§3);
      thumbnail 3:2 ≤5 MB; ≤15 images
- [ ] Elevator pitch pasted (93 chars, ≤100); thumbnail shows the card, not Devpost's placeholder
- [ ] Project Story headings match Devpost's template (§4); Built With
      includes standalone **Nebius Token Factory** and **NVIDIA** chips
- [ ] §5 questionnaire answered — every required field non-empty; Tavily
      = **No**
- [ ] §6 repo checks green: public, Apache-2.0 LICENSE, README setup
      current, tag visible, no secrets in the tree
- [ ] Repo link opens on the "For judges" README; `submission-v1` tag
      visible under Releases/Tags
- [ ] Social preview uploaded via Settings (step 8) — a shared repo link
      shows the card, not the auto-generated file grid
- [ ] Sources block pasted and links clickable
- [ ] No claim in the submission lacks a row in JUDGE_REPRO's index
- [ ] Submitted **before Fri Oct 30, 10:00 AM PT** — the draft page's
      "Submit" step is the only one that counts; verify the page flips
      from DRAFT to submitted
