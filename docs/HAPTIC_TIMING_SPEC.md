# Haptic timing spec — one clock for the wrist and the phone

**Purpose:** every buzz and silence the Ziv haptic channel plays lives in exactly one place — [docs/haptic-timing.json](./haptic-timing.json). The phone feel-tool ([haptic-name-marks.html](./haptic-name-marks.html)) and the band firmware (`haptic_out`, plan §5) are *generated* consumers of that file, so the pattern you feel on the phone is the pattern the motors play — by construction, not by convention.

**Status:** spec v3. Implements plan §4 (attention vocabulary — five attention patterns + two lifecycle patterns) and the vibro-braille cell rule (protocol §0: duration = 50 + 60 × dots ms). Research/screening tool: no clinical claims (§9).

## How the single source works

- `docs/haptic-timing.json` — canonical constants, the 26-letter Grade-1 dot table (counts *and* dot positions — the Unicode glyphs and the firmware's per-letter motor bitmask are derived from the positions), the five candidate marks, pre-validated rename examples (protocol §5 option B), the seven attention/lifecycle patterns (each beat annotated with the constant it references), and the prefix composition. Edit here, and only here.
- `python tools/haptic_timing.py --write` — regenerates: the feel-tool's timing block + gap slider, [firmware/haptic_out/haptic_timing.h](../firmware/haptic_out/haptic_timing.h), and the tables below.
- `python tools/haptic_timing.py` — verifies every consumer against the JSON (generated block text, slider envelope, the HTML's LETTERS/MARKS tables, the M1 distractor pool ids) and exits non-zero on any drift. Run it after touching either side; the JSON itself self-validates (beat ranges, constant references, the tail rule, mark letters).
- **Drift cannot be committed** — the same verify runs in the pre-commit hook ([hooks/pre-commit](../hooks/pre-commit), installed with `git config core.hooksPath hooks`) and in the agent's Ziv hermetic suite ([tests/test_haptic_timing.py](../agent/tests/test_haptic_timing.py), which also proves the checker detects drift).

<!-- haptic-timing:begin (generated — do not edit; regenerate with tools/haptic_timing.py --write) -->

### Constants — spec v3

| Constant | ms | Feeds |
|---|---:|---|
| `cell_base_ms` | 50 | braille cell buzz floor |
| `cell_per_dot_ms` | 60 | added per raised dot: `cell_ms = cell_base + cell_per_dot × dots` |
| `cell_gap_default_ms` | 420 | silence between cells — the playback-speed control (tunable 250–700 ms, step 10 ms) |
| `tick_ms` | 70 | the attention tick |
| `tick_gap_ms` | 160 | silence between ticks inside a pattern |
| `long_buzz_ms` | 600 | the error buzz |
| `tail_gap_ms` | 420 | silence after a pattern's last beat |
| `prefix_breath_ms` | 550 | silence between the name mark and its attention tail |

### UI vs. runtime limits — do not unify

- `spell_max_letters` = 12: the feel-tool page's spell-box affordance — it caps how long a word the page headlines for the wearer. - The band firmware's runtime ceiling is `HAPTIC_OUT_MAX_WORD_LEN` = 16: the longest word the motors will actually play. These are intentionally different settings for different layers (page vs. device), not two views of one number — do not unify them.

### Attention patterns (plan §4)

| Pattern | Meaning | Beats — buzz/gap in ms |
|---|---|---|
| `double-tap` | acknowledge / you go | 70/160 · 70/420 |
| `triple-pulse` | reminder / look again | 70/160 · 70/160 · 70/420 |
| `long-buzz` | error / stop | 600/420 |
| `ramp-up` | attention building | 50/90 · 90/120 · 140/160 · 200/420 |
| `heartbeat` | keep alive / I'm here | 70/120 · 70/420 |
| `processing` | thinking / working | 70/350 · 70/420 |
| `end-of-message` | done / return | 200/120 · 140/120 · 90/120 · 50/420 |

### Cell durations — the full Grade-1 alphabet

```
a=110 b=170 c=170 d=230 e=170 f=230 g=290 h=230
i=170 j=230 k=170 l=230 m=230 n=290 o=230 p=290
q=350 r=290 s=230 t=290 u=230 v=290 w=290 x=290
y=350 z=290
```

| Letter | Dots | Pattern | Glyph |
|---|---|---|---|
| a | 1 | 1 | ⠁ |
| b | 2 | 1-2 | ⠃ |
| c | 2 | 1-4 | ⠉ |
| d | 3 | 1-4-5 | ⠙ |
| e | 2 | 1-5 | ⠑ |
| f | 3 | 1-2-4 | ⠋ |
| g | 4 | 1-2-4-5 | ⠛ |
| h | 3 | 1-2-5 | ⠓ |
| i | 2 | 2-4 | ⠊ |
| j | 3 | 2-4-5 | ⠚ |
| k | 2 | 1-3 | ⠅ |
| l | 3 | 1-2-3 | ⠇ |
| m | 3 | 1-3-4 | ⠍ |
| n | 4 | 1-3-4-5 | ⠝ |
| o | 3 | 1-3-5 | ⠕ |
| p | 4 | 1-2-3-4 | ⠏ |
| q | 5 | 1-2-3-4-5 | ⠟ |
| r | 4 | 1-2-3-5 | ⠗ |
| s | 3 | 2-3-4 | ⠎ |
| t | 4 | 2-3-4-5 | ⠞ |
| u | 3 | 1-3-6 | ⠥ |
| v | 4 | 1-2-3-6 | ⠧ |
| w | 4 | 2-4-5-6 | ⠺ |
| x | 4 | 1-3-4-6 | ⠭ |
| y | 5 | 1-3-4-5-6 | ⠽ |
| z | 4 | 1-3-5-6 | ⠵ |

### Rename examples (protocol §5 option B)

Same dot-count arc as **raz** (4-1-4): **zar** — arc-validated only; legal screening per plan §1 required before adoption.

### The five candidate marks

| Mark | Letters | Arc — buzz/gap in ms (last cell bare) |
|---|---|---|
| ziv | z·i·v | 290/420 · 170/420 · 290 |
| raz | r·a·z | 290/420 · 110/420 · 290 |
| boaz | b·o·a·z | 170/420 · 230/420 · 110/420 · 290 |
| razu | r·a·z·u | 290/420 · 110/420 · 290/420 · 230 |
| buz | b·u·z | 170/420 · 230/420 · 290 |

### Prefix composition (plan §4)

The ziv mark (290/420 · 170/420 · 290) → silence 550 ms → attention tail: message = `double-tap` · reminder = `triple-pulse` · error = `long-buzz`.

<!-- haptic-timing:end -->

## Why the numbers are what they are

- **Cells** carry duration by dot weight: `cell_ms = 50 + 60 × dots`. The lightest cell (1 dot) is 110 ms, the heaviest (4-dot Z/V arc) 290 ms — the heavy-light-heavy Ziv arc falls out of the alphabet itself (plan §4).
- **Ticks (70 ms) sit below the lightest cell (110 ms)** and the **long buzz (600 ms) above the heaviest cell (290 ms)**, so attention patterns are never confusable with letter cells by duration alone.
- **Lifecycle patterns speak through gaps and shape, not tick length** — `processing` is two ticks like double-tap, but its middle gap is 350 ms (double-tap: 160, heartbeat: 120): the pause is the ellipsis. `end-of-message` descends 200→140→90→50, the exact mirror of ramp-up's ascent — an event closing, not opening — and its even 120 ms gaps never match a cell sequence's cadence. Both join the week-6 M3 confusion screen (protocol §3).
- **Ramp up** ascends in duration (50 → 90 → 140 → 200) because the Android Vibration API has no amplitude control — duration is the only ramp the phone can play, so it is the ramp the band must match.
- **Cell gap is the speed control** (250–700 ms, default 420): the same envelope on the page's slider and in the band's config, so M1 reaction times measured on the phone transfer to the wrist (protocol §3).
- **Prefix breath (550 ms)** separates the name mark from its attention tail so the wearer hears two events — *who*, then *why* — not one merged blob.

## Change discipline

1. Edit `docs/haptic-timing.json` (bump `version`).
2. `python tools/haptic_timing.py --write`.
3. Re-feel every pattern on the phone; re-run an M1 session.
4. Commit the JSON and both consumers together — they are one artifact.

Enforced: the pre-commit hook and the hermetic suite refuse a commit that
violates steps 1–2.
