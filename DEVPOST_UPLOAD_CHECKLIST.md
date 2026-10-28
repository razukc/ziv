# Devpost Upload Checklist — Ziv

Team-facing upload guide. Everything maps to files already in this repo —
paste, don't rewrite. Pick **one narrative voice** for the description
fields (recommended: the product-first `DEVPOST_HAPTIC_GENERIC.md`, which
keeps the deaf-blind case in its own section) and stay in that voice for
every field. Before you re-record or re-upload, run the gate:

```bash
cd agent && python -m pytest -m "not e2e"   # → 232 passed (5 e2e deselected)
python -m pytest -m e2e                     # → 5 passed (needs Playwright)
```

**Deadline: submissions close Friday, October 30, 10:00 AM PT.** The draft
page's own counter is the source of truth — don't plan a last-day upload.

**State (2026-10-28):** submitted — public page
<https://devpost.com/software/ziv>; video <https://youtu.be/t9ovgEjm8i8>
(unlisted, 76.2 s, Kore cut); judges-only PDF attached. The fields below
remain editable until the deadline.

---

## 1. Field-by-field mapping

| Devpost field | Paste from | Notes |
|---|---|---|
| **Project name** | GENERIC "Project Name" | `Ziv` — keep "*(working title)*" out of the field; the working-title honesty lives in the description |
| **Elevator pitch** (overview step) | Paste: "Messages you can feel. No spoken reply. A haptic channel with an agent behind it." | 81 chars — fits the field's 200-char cap |
| **Thumbnail** (overview step) | Upload `docs/devpost_thumbnail.png` | 1500×1000 (3:2), 463 KB; regenerate with `python tools/devpost_thumbnail.py`. Same brand card as the social preview, plus the NVIDIA/Nebius stack line |
| **Short description** | GENERIC "Short Description (one-liner)" | 342 chars as written; a 183-char fallback lives in DEVPOST_FIELDS.md if the field complains |
| **Description** | GENERIC **Our Solution → What it does → Why It Matters → A scene from the demo → Use cases** | Keep section order; the Use cases section is the one place the deaf-blind case appears — keep it that way |
| **"What does your project do?"** | GENERIC → Devpost-Specific Answers | Direct paste |
| **"What makes your project unique?"** | GENERIC → Devpost-Specific Answers | Includes the timing-mechanism sentence; keep it |
| **"What challenges did you face?"** | GENERIC → Devpost-Specific Answers (numbered 1–5) | Direct paste |
| **"What technologies did you use?"** | GENERIC → Devpost-Specific Answers | Keep the closing scope clause ("No wrist board is flashed") — it names the firmware without listing silicon this demo didn't use |
| **"What hackathon track are you in?"** | GENERIC → Devpost-Specific Answers | Best Apps and Agents |
| **GitHub repo link** | `https://github.com/razukc/ziv` | Judges land on the README's "For judges" block; the current submission tree is the verified tree. Public-repo requirements are a graded form item — see §6 |
| **"Built with" chips** | NVIDIA Nemotron-3-Nano-30B-A3B, Nebius Token Factory, FastAPI, WebSockets, Android Vibration API, ESP32, Python | Add chips exactly as listed. Part-number chips (`ESP32-S3`, `DRV2605L`) are deliberately left out — they name silicon that is not on a board, and in a chip row that reads as delivered hardware. NVIDIA + Nebius named here is an explicit organizer ask — don't trim |
| **Demo video** | See shot list below | Uploaded to YouTube (unlisted): `https://youtu.be/t9ovgEjm8i8` — `media/tts_audition/demo_kore/demo_kore.mp4` (**76.2 s**, Kore voice, burned-in captions): gallery-slide intro → live channel turn → `flow` slide → live model beat for the scheduled intent **`meds at nine`** (the model wrote **`meds nine`**) → `haptics` and `honesty` briefs → closing card. The voiceover names Nebius Token Factory and the NVIDIA model. This replaces the older 107 s and 54 s cuts, which predate the 12-cell cap fix and the 2026-10-28 claim sweep. The MP4 is gitignored: upload it from the workspace, not from the repo. |
| **Screenshot gallery** | See shot list below | 4–6 images, each with its caption — §3 |

Do **not** paste: `HONESTY_CHANGELOG.md` and `JUDGE_REPRO.md` are repo
artifacts (linked from the README the judges will open), not Devpost body
text — but reference them in one line at the end of the description:
*"Every claim is reproducible: see JUDGE_REPRO.md; the claims-vs-code audit
trail is HONESTY_CHANGELOG.md."*

## 2. Demo video shot list (≤3 min, follows GENERIC's outline)

1. **0:00–0:06 hero slide** — the gallery hero: "A haptic message channel
   for deaf-blind users." The voice names Ziv and the channel.
2. **0:06–0:23 the live channel turn** — the actual dev-band page: typed
   message, arrival cue, working ticks, cells, close. The voice explains the
   one pipeline and the shared timing spec.
3. **0:23–0:33 `flow` slide** — sender → relay → phone; a typed message or a
   scheduled intent takes the same path, one turn at a time.
4. **0:33–0:47 the live model beat** — scheduled intent **`meds at nine`**;
   the relay calls Nemotron-3-Nano-30B-A3B on Nebius Token Factory; the band
   spells **`meds nine`**. The voice says the relay's own record says the model
   call succeeded; the wire log names `text_live`.
5. **0:47–0:57 `haptics` slide** — cue, spell, close; cues need no braille
   literacy, and braille is the layer for readers.
6. **0:57–1:05 `honesty` slide** — built now vs next revision: phone today,
   wrist next; 232 hermetic tests green in the current suite.
7. **1:05–1:16 closing card** — repo URL, scope, and the tagline. The phone
   stays silent; the channel's audio output is none.

Recording notes: capture the dev-band page at desktop width (the wire log
is the star); record phone vibration close-ups with a second angle; keep
each wire-log scroll readable (bump browser zoom to 125%).

**Say the required names out loud.** The organizers' own tip: name Nebius
Token Factory / AI Cloud and the NVIDIA model "clearly — in your demo
video, not just a passing mention." Two scripted paths do this themselves
(TTS voiceover + ffmpeg mux, per-phase marks kept for re-mixing):

-  `agent/record_full_demo.py` — the live take recorder used for the current
   cut (cold-open card → channel → the model-path beat → closing card) →
   `agent/demo_live.webm` plus marks. The 2026-10-28 take was recorded against
   the public origin with the funded key: the intent **`meds at nine`** was
   composed live into **`meds nine`**, and the relay's `last_compose` says
   `{ok: true, status: 200, model: NVIDIA…}`. A keyless take would narrate the
   verbatim `text_echo` path instead. No Omni model is shown or named in this
   take — it is held as asset, not demonstrated.
-  `media/tts_audition/build_demo_kore.py` — builds the **76.2 s** captioned
   cut from that take, with the hero/flow/haptics/honesty slides and Kore’s
   narration → `media/tts_audition/demo_kore/demo_kore.mp4`. The MP4 is
   gitignored; upload it from the workspace.
- `agent/record_beat_narrated.py` — just the 0:20–1:10 beat against a
  self-started relay on :8787 (`ZIV_FAKE_MODEL_SECONDS=8`) →
  `demo_beat_narrated.mp4`.

`ZIV_TAKE=live` on `record_full_demo.py` records the four-beat live take →
`agent/demo_live.webm` (**48.2 s** silent): cold open, channel, live NVIDIA
compose, closing. It reads the live claim from the relay's health record, not
the local `.env`, and leaves the deployed relay running. The current cut uses
that silent master and rebuilds the narration in Kore, so do not upload the
SAPI `demo_live_narrated.mp4` (66.9 s) instead. Both modes use the installed
Chrome channel for capture (the headless shell crashed its renderer after
~90 s) and count wire events in page state, because the client's log trims at
60 lines.

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
| 2b | `02-badge-refusing.png` | Queue full: the badge reads refusing — queue full (8/8), the sender gets HTTP 429 with a plain-language busy note, and the refused message arms its redial. A loud no, not a silent drop. |
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
| **Built with** (≤25 tags) | NVIDIA Nemotron-3-Nano-30B-A3B, NVIDIA, Nebius Token Factory, Nebius AI Cloud, FastAPI, WebSockets, Python, Android, PWA, Vibration API, ESP32, ESP-IDF, Embedded C, braille, haptics, accessibility, deaf-blind, assistive tech, uvicorn, pytest, Playwright, HTTP 429, agents — add **Nebius Token Factory** and **NVIDIA** as standalone chips; organizers check for them by name |
| **"Try it out" links** | GitHub repo `https://github.com/razukc/ziv` + hosted feel-tool `https://site-5505fea77ec84b4f8e1a5d70c82d5877.freebuff.page` (no install, no key) + live PWA `https://35-224-56-20.sslip.io` |
| **Image gallery** | 9 shots from §3, each with its caption |
| **Video demo link** | `https://youtu.be/t9ovgEjm8i8` — unlisted, 76.2 s Kore cut; verified playable from a signed-out incognito session. Devpost embeds it at the top of the public page. |

## 5. Additional info (judges-only) — paste-ready answers

The "Additional info" step is **for judges and organizers** (not public),
and the Nemotron/Nebius feedback questionnaire is a **required** part of
every submission — the organizers' email says so explicitly, not an
afterthought. Be specific per tool ("the docs were confusing" doesn't help
anyone without naming the tool). Paste-ready drafts:

- **Submitter type / country / track / new-or-existing:** Individual ·
  Nepal · **Best apps and agents** · **New** (leave the "existing" essay
  empty).
- **Upload a File (≤35 MB):** attached: [docs/JUDGE_REPRO.pdf](docs/JUDGE_REPRO.pdf)
  — the 8-page judge repro guide. One file only; zip multiples.
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
      README badges honestly, current submission tag visible, no secrets
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

- [ ] `pytest -m "not e2e"` → 232 passed (5 e2e deselected); `-m e2e` → 5 passed
- [ ] Video ≤ 3:00, every outline beat present, wire log readable, and
      Token Factory + Nemotron **named aloud** (§2's narrated pipeline),
      uploaded as MP4/WebM with the audio track present in the file
- [ ] Every number in the description matches the repo (232 passed / 5 e2e,
      274-check firmware bench, 49-check ziv_qemu host suite, 27 HAP events
      — JUDGE_REPRO.md is the source of truth)
- [ ] Both deferral sentences intact (AI-composed replies = next build
      step; wrist hardware = next revision)
- [ ] Gallery images uploaded with **every caption field filled** (§3);
      thumbnail 3:2 ≤5 MB; ≤15 images
- [ ] Elevator pitch pasted (100 chars, ≤200); thumbnail shows the card, not Devpost's placeholder
- [ ] Project Story headings match Devpost's template (§4); Built With
      includes standalone **Nebius Token Factory** and **NVIDIA** chips
- [ ] §5 questionnaire answered — every required field non-empty; Tavily
      = **No**
- [ ] §6 repo checks green: public, Apache-2.0 LICENSE, README setup
      current, tag visible, no secrets in the tree
- [ ] Repo link opens on the "For judges" README; current submission tag
      visible under Releases/Tags
- [ ] Social preview uploaded via Settings (step 8) — a shared repo link
      shows the card, not the auto-generated file grid
- [ ] Sources block pasted and links clickable
- [ ] No claim in the submission lacks a row in JUDGE_REPRO's index
- [ ] Submitted **before Fri Oct 30, 10:00 AM PT** — the draft page's
      "Submit" step is the only one that counts; verify the page flips
      from DRAFT to submitted
