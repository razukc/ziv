# Devpost Upload Checklist — Ziv

Team-facing upload guide. Everything maps to files already in this repo —
paste, don't rewrite. Pick **one narrative voice** for the description
fields (recommended: the product-first `DEVPOST_HAPTIC_GENERIC.md`, which
keeps the deaf-blind case in its own section) and stay in that voice for
every field. Before you record or upload, run the gate:

```bash
cd agent && python -m pytest -m "not e2e"   # → 126 passed, 2 skipped
python -m pytest -m e2e                     # → 3 passed (needs Playwright)
```

---

## 1. Field-by-field mapping

| Devpost field | Paste from | Notes |
|---|---|---|
| **Project name** | GENERIC "Project Name" | `Ziv` — keep "*(working title)*" out of the field; the working-title honesty lives in the description |
| **Tagline** | GENERIC "Tagline" | "Messages you can feel. Nobody else can see." |
| **Short description** | GENERIC "Short Description (one-liner)" | ~280 chars, fits the field |
| **Description** | GENERIC **Our Solution → What it does → Why It Matters → A scene from the demo → Use cases** | Keep section order; the Use cases section is the one place the deaf-blind case appears — keep it that way |
| **"What does your project do?"** | GENERIC → Devpost-Specific Answers | Direct paste |
| **"What makes your project unique?"** | GENERIC → Devpost-Specific Answers | Includes the timing-mechanism sentence; keep it |
| **"What challenges did you face?"** | GENERIC → Devpost-Specific Answers (numbered 1–5) | Direct paste |
| **"What technologies did you use?"** | GENERIC → Devpost-Specific Answers | Keep the parenthetical "wrist hardware is the next revision" — it keeps the stack list honest |
| **"What hackathon track are you in?"** | GENERIC → Devpost-Specific Answers | Best Apps and Agents |
| **GitHub repo link** | `https://github.com/razukc/ziv` | Judges land on the README's "For judges" block; the `submission-v1` tag freezes the verified tree |
| **"Built with" chips** | NVIDIA Nemotron-3-Nano-Omni, Nebius Token Factory, FastAPI, WebSockets, Android Vibration API, ESP32-S3, DRV2605L, Python | Add chips exactly as listed (ESP32/DRV2605 belong to the next revision — the tech answer already scopes that) |
| **Demo video** | See shot list below | ≤3 min; the outline is in GENERIC "Demo Video Outline" |
| **Screenshot gallery** | See shot list below | 4–6 images |

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
4. **1:10–1:50 the stack** — push-to-talk press → mic clip log line →
   `transcribing via Token Factory…` → `Omni heard — turn turn_complete`;
   flash `tools/haptic_timing.py` verify output (spec v3, 7 consumers in
   sync) and `docs/haptic-timing.json`.
5. **1:50–2:30 the agent** — schedule a reminder via curl (command from
   JUDGE_REPRO Step 1); reminder arrives unprompted: `reminder: pills`
   narration, Z-I-V cells, `triple-pulse`, close. Then the durability
   beat: kill the relay, restart, `GET /api/ziv/schedule` returns the same
   reminder. Close the tab, send while away → `inbox:stored`; reattach →
   replay arrives as a self-naming turn.
6. **2:30–3:00 who it serves** — the GENERIC Use-cases paragraph (everyday
   contexts, then the deaf-blind case), the ask line, and the repo URL.

Recording notes: capture the dev-band page at desktop width (the wire log
is the star); record phone vibration close-ups with a second angle; keep
each wire-log scroll readable (bump browser zoom to 125%).

## 3. Screenshot gallery (4–6)

1. The dev-band page mid-turn: cells box lighting up + wire log showing
   cue → processing → cells → close (the whole vocabulary in one frame).
2. The badge in its two states: `queue 3/8 · reminders 0/64` and
   `refusing — queue full (8/8)` with the busy note.
3. The redial lifecycle: armed note with chances left → (after close) the
   `POST ok` line; plus the red dead-end note after three tries.
4. A reminder turn arriving unprompted: `reminder: …` narration with the
   Z-I-V cells and `triple-pulse` in the log.
5. Health JSON (the operator view): `gate_queue/cap`, `schedule_pending/
   cap`, `queue_rejections` — the numbers the badge renders.
6. Optional: the terminal proof — `pytest` tail (`126 passed, 2 skipped`,
   `3 passed`) beside the firmware suite (`49 checks, 0 failures`).

## 4. Source links to paste (Description → "Sources" section)

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

## 5. Pre-flight (final)

- [ ] `pytest -m "not e2e"` → 126 passed, 2 skipped; `-m e2e` → 3 passed
- [ ] Video ≤ 3:00, every outline beat present, wire log readable
- [ ] Every number in the description matches the repo (129 tests, 49/0
      bench, 27 HAP events — JUDGE_REPRO.md is the source of truth)
- [ ] Both deferral sentences intact (AI-composed replies = next build
      step; wrist hardware = next revision)
- [ ] Repo link opens on the "For judges" README; `submission-v1` tag
      visible under Releases/Tags
- [ ] Sources block pasted and links clickable
- [ ] No claim in the submission lacks a row in JUDGE_REPRO's index
