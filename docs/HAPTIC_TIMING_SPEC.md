# Haptic timing spec — one clock for the wrist and the phone

**Purpose:** every buzz and silence the Ziv haptic channel plays lives in exactly one place — [docs/haptic-timing.json](./haptic-timing.json). The phone feel-tool ([haptic-name-marks.html](./haptic-name-marks.html)) and the band firmware (`haptic_out`, plan §5) are *generated* consumers of that file, so the pattern you feel on the phone is the pattern the motors play — by construction, not by convention.

**Status:** spec v4. Implements plan §4 (attention vocabulary — five attention patterns + two lifecycle patterns), the vibro-braille cell rule (protocol §0: duration = 50 + 60 × dots ms) and, since v4, the utterance layer of [ARCHITECTURE.md](./ARCHITECTURE.md) §2/§5/§10: the word gap, the working cadence, the kind → cue/tail table, the two renderer profiles (chords on the band, time slots on a phone) and the conformance tolerance. Research/screening tool: no clinical claims (§9).

## How the single source works

- `docs/haptic-timing.json` — canonical constants, the 26-letter Grade-1 dot table (counts *and* dot positions — the Unicode glyphs and the firmware's per-letter motor bitmask are derived from the positions), the five candidate marks, pre-validated rename examples (protocol §5 option B), the seven attention/lifecycle patterns (each beat annotated with the constant it references), the prefix composition, and (v4) the `kinds` table, the renderer `profiles` and the word-gap / working-cadence / tolerance constants, each with its reasoning under `rationale`. Edit here, and only here.
- `python tools/haptic_timing.py --write` — regenerates: the feel-tool's timing block + gap slider, [firmware/haptic_out/haptic_timing.h](../firmware/haptic_out/haptic_timing.h) (constants, pattern tables, `haptic_kind` cue/tail tables, the slot order), the Python timing module ([ziv/haptics/tables.py](../ziv/haptics/tables.py) and its home in the package, [ziv/haptics/tables.py](../ziv/haptics/tables.py), which the reference renderer and the conformance harness read at call time), the scripted boot demo pair, the QEMU ladder's demo-chain block, and the tables below.
- `python tools/haptic_timing.py` — verifies every consumer against the JSON (generated block text, slider envelope, the HTML's LETTERS/MARKS tables, the M1 distractor pool ids) and exits non-zero on any drift. Run it after touching either side; the JSON itself self-validates (beat ranges, constant references, the tail rule, mark letters).
- **Drift cannot be committed** — the same verify runs in the pre-commit hook ([hooks/pre-commit](../hooks/pre-commit), installed with `git config core.hooksPath hooks`) and in the suite ([tests/test_timing_guard.py](../tests/test_timing_guard.py), which also proves the checker detects drift).

<!-- haptic-timing:begin (generated — do not edit; regenerate with tools/haptic_timing.py --write) -->

### Constants — spec v4

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
| `word_gap_ms` | 520 | silence between two words of one utterance (inside a word: the pace) — longer than the default cell gap, shorter than the prefix breath |
| `working_every_ms` | 2000 | period at which a device repeats `processing` on its own clock while an utterance's body is pending |
| `conformance_tolerance_ms` | 10 | per-beat start-time drift (±) a real renderer may show against the reference timeline; dot mask and buzz length must match exactly |

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

### Kinds — arrival cue and prefix tail (architecture §2)

| Kind | Cue | Tail after the mark |
|---|---|---|
| `message` | `double-tap` | `double-tap` |
| `reminder` | `triple-pulse` | `triple-pulse` |
| `error` | `long-buzz` | `long-buzz` |
| `system` | `heartbeat` | `heartbeat` |

### Renderer profiles (architecture §5.2)

- `six_actuator` (`chord`): a cell is its raised dots driven together for `cell_ms` (110–350 ms, mean 244 ms over the alphabet).
- `single_actuator` (`slots`): a cell is 6 time slots in dot order 1-2-3-4-5-6; a raised dot is a `slot_ms` = 50 ms pulse in its slot, an absent dot 50 ms of silence; `slot_gap_ms` = 30 ms follows every slot but the last and `column_gap_ms` = 80 ms more follows the third. Every cell lasts 6 × 50 + 5 × 30 + 80 = **530 ms** whatever the letter (2.2 × the mean chord cell).

| Slot | Dot | Pulse starts at (ms into the cell) |
|---:|---:|---:|
| 1 | 1 | 0 |
| 2 | 2 | 80 |
| 3 | 3 | 160 |
| 4 | 4 | 320 |
| 5 | 5 | 400 |
| 6 | 6 | 480 |

<!-- haptic-timing:end -->

## Why the numbers are what they are

- **Cells** carry duration by dot weight: `cell_ms = 50 + 60 × dots`. The lightest cell (1 dot) is 110 ms, the heaviest (4-dot Z/V arc) 290 ms — the heavy-light-heavy Ziv arc falls out of the alphabet itself (plan §4).
- **Ticks (70 ms) sit below the lightest cell (110 ms)** and the **long buzz (600 ms) above the heaviest cell (290 ms)**, so attention patterns are never confusable with letter cells by duration alone.
- **Lifecycle patterns speak through gaps and shape, not tick length** — `processing` is two ticks like double-tap, but its middle gap is 350 ms (double-tap: 160, heartbeat: 120): the pause is the ellipsis. `end-of-message` descends 200→140→90→50, the exact mirror of ramp-up's ascent — an event closing, not opening — and its even 120 ms gaps never match a cell sequence's cadence. Both join the week-6 M3 confusion screen (protocol §3).
- **Ramp up** ascends in duration (50 → 90 → 140 → 200) because the Android Vibration API has no amplitude control — duration is the only ramp the phone can play, so it is the ramp the band must match.
- **Cell gap is the speed control** (250–700 ms, default 420): the same envelope on the page's slider and in the band's config, so M1 reaction times measured on the phone transfer to the wrist (protocol §3).
- **Prefix breath (550 ms)** separates the name mark from its attention tail so the wearer hears two events — *who*, then *why* — not one merged blob.
- **Word gap (520 ms, v4)** is the silence between two words of one utterance; inside a word the gap is the wearer's pace. It is about a quarter longer than the 420 ms default cell gap — above the ~20 % Weber fraction for empty tactile intervals, so a word boundary is *felt* as a boundary — and 30 ms under the breath, the one silence that already means "a boundary between events", so a word boundary never outranks *who / why*. It cannot read as an ending: since v3 nothing ends on silence, only `end-of-message` does (plan §4 invariant 2). Note that the literal envelope "between the cell gap and the tail gap" is empty at v4 (`tail_gap_ms` = `cell_gap_default_ms` = 420); the breath is the upper bound that matters, and `validate()` enforces `cell_gap_default_ms < word_gap_ms < prefix_breath_ms`. **Known limit, to validate on the feel-tool:** the gap is a constant while the pace is tunable 250–700 ms, so at paces of 520 ms and slower a word boundary is no longer longer than a cell gap. If slow readers need it, v5 defines the word gap relative to the pace; the renderer contract does not change.
- **Working cadence (2000 ms, v4)** is how often a device repeats `processing` on its own clock while an utterance's body is pending (architecture §5.1) — the relay's old `PROCESSING_EVERY_S = 2.0` and the plan's "~2 s" (§4 invariant 3). One play of the pattern lasts 910 ms, so each repeat is followed by about a second of silence: a pulse, not a drone. `validate()` refuses a cadence shorter than one play. The reference renderer models the header only (one `processing` play); the repeats are device time, not utterance time, and do not count against the budget.
- **Single-actuator slots (50 / 30 / 80 ms → 530 ms per cell, v4)** carry *letters* on a phone's one motor, not dot counts: a cell is six time slots in dot order 1-2-3 · 4-5-6; a raised dot is a 50 ms pulse in its slot, an absent dot 50 ms of silence; 30 ms separates slots and 80 ms more separates the two columns, so the column break (110 ms) is almost four times the in-column gap and every cell lasts 6 × 50 + 5 × 30 + 80 = **530 ms** whatever the letter — the letter lives in *where* the pulses fall. That is 2.2 × the mean chord cell (244 ms over the alphabet) and 1.5 × the heaviest (350 ms): the "roughly twice" architecture §5.2 budgets for, and the time budget is computed per profile so a phone is never asked to play what it cannot fit. The 50 ms pulse is the shortest buzz already in the vocabulary (ramp-up's first beat, `cell_base_ms`). **All three numbers are provisional until validated on the feel-tool with braille readers**: the trade is legibility of pulse *position* against the budget; a slower slot (e.g. 70 / 40 / 100) is the first thing to try if positions blur, and the table above (pulse start per slot) is what a reader is asked to recognise.
- **Conformance tolerance (10 ms, v4)** is the per-beat start-time drift a real renderer may show against the reference timeline; dot masks and buzz lengths must match exactly. It equals the HAP differ's tolerance in `tools/qemu_timeline.py` and sits well under the shortest silence in the spec (the 30 ms slot gap), so a tolerance can never hide a merged or missing beat — `validate()` checks that too.

## The reference renderer and the conformance harness

`ziv/haptics/reference.py` turns an utterance (`ziv.wire.Utterance`) into the timeline every real renderer is measured against: `timeline(utterance, profile, pace_ms)` → a list of `Beat(t_ms, dot_mask, buzz_ms, label)`, `duration_ms(...)` → the time budget admission charges. It adds structure only; every number comes from `ziv/haptics/tables.py`. The shape of a turn, in order:

1. the prefix, when present: the mark's cells with the pace between them, `prefix_breath_ms` after the last, then the kind's tail pattern;
2. the kind's cue pattern;
3. one `processing` play when `body_pending` and no words have arrived;
4. the words: the pace between cells inside a word, `word_gap_ms` between words;
5. `tail_gap_ms` of silence after the last cell, then `end-of-message`.

On `six_actuator` a cell is one beat (`dot_mask` = the letter's mask, `buzz_ms` = `cell_ms`); on `single_actuator` it is one beat per raised dot (`dot_mask` = that dot's bit, `buzz_ms` = `slot_ms`) at the slot offsets above. Pace is clamped into the spec envelope. [conformance/](../conformance/README.md) holds the golden utterances, the expected timelines the reference produces for them (`conformance/run.py --write`, guarded by `--check`), and the player interface the C sequencer and the phone client plug into (`--player "<command>" --profile P`).

## Change discipline

1. Edit `docs/haptic-timing.json` (bump `version`).
2. `python tools/haptic_timing.py --write`.
3. `.venv/bin/python conformance/run.py --write` when any timeline changes, and read the diff of `conformance/expected/` — it is the felt change, beat by beat.
4. Re-feel every pattern on the phone; re-run an M1 session.
5. Commit the JSON and every consumer together — they are one artifact.

Enforced: the pre-commit hook and the hermetic suite refuse a commit that
violates steps 1–2.
