# Conformance — one oracle, every renderer

The reference renderer, [`ziv/haptics/reference.py`](../ziv/haptics/reference.py),
is the definition of correct playback (architecture §10): it turns an
utterance into the timeline of buzzes a faithful device produces. Every real
renderer — the band's C sequencer, the phone client, anything that comes
later — is measured against it here, with the tolerance the spec allows.

Nothing in this directory carries a number of its own. The profiles, the
default pace and the tolerance come from `docs/haptic-timing.json` through
the generated `ziv/haptics/tables.py`.

## Layout

| Path | What it is |
|---|---|
| `golden/*.json` | The golden utterances, each valid against `ziv.wire.Utterance` (the `utterance` schema in `schema/`). Every kind; with and without a prefix; `body_pending`; one, two and three words; a 32-letter word; and `budget_<profile>`, the longest utterance that fits a 15 000 ms budget on that profile at the default pace — machine-constructed (whole words while they fit, then the lightest letter until nothing more fits), which is why its last word is padded; `tests/test_conformance.py` proves one more cell would not fit. |
| `expected/<name>.<profile>.jsonl` | The reference timeline for each golden utterance on each profile at the spec's default pace. **Generated** by `run.py --write`; never hand-edited. |
| `run.py` | The harness: `--write`, `--check`, `--player`. |
| `players/reference.py` | The reference as a player — the known-good player the harness is tested with, and the smallest complete example of the interface. |

## Commands

```bash
PY=.venv/bin/python

$PY conformance/run.py --check          # expected/ agrees with the reference (the oracle's drift guard)
$PY conformance/run.py --write          # regenerate expected/ after a spec or renderer change

# hold a player to the reference on one profile
$PY conformance/run.py --player ".venv/bin/python conformance/players/reference.py" --profile single_actuator
$PY conformance/run.py --player "firmware/app/ziv_qemu/host_player" --profile six_actuator
$PY conformance/run.py --player "node client/dist/conformance.js" --profile single_actuator

# options
#   --pace N        cell gap to ask the player for (default: the spec's; expected/ is at the default)
#   --tolerance N   per-beat |Δt| allowed (default: the spec's conformance_tolerance_ms)
#   --only NAME     one golden utterance
#   --max-diffs K   differences printed per failing utterance
#   --jobs N        player processes at once (default: up to 8; use 1 for a player that must run alone)
```

`--check` and `--player` exit 0 only when everything conforms, 1 on any
drift or failure, 2 when the harness itself cannot run (no goldens, an
invalid golden, an unknown profile). `tests/test_conformance.py` runs
`--check` and a reference-vs-reference player run in the suite.

## The player interface

The harness runs, from the repository root, for each golden utterance:

```
<command> --profile <profile> --pace <pace_ms>
```

- **stdin:** the utterance as JSON — the golden file's text, byte for byte.
- **stdout:** the player's timeline as JSON Lines, one beat per line:

  ```
  {"t_ms":int,"dot_mask":int,"buzz_ms":int,"label":str}
  ```

  `t_ms` is the beat's start, in milliseconds from the first beat's start (so
  the first line has `t_ms` 0); `dot_mask` is the raised dots during the
  buzz, bit *n* = dot *n*+1 (`0x01` dot 1 … `0x20` dot 6), and `0` for a
  whole-device pattern beat; `buzz_ms` is the buzz length; `label` is free
  text for humans (`cue`, `cell:t`, …) and is not compared. Blank lines are
  ignored. Anything else is a failure, not a pass.
- **exit code:** 0. A non-zero exit, a timeout (`--timeout`, default 30 s)
  or unparsable output fails that utterance; stderr is shown with the
  failure.
- `<command>` is split with POSIX shell rules (`shlex.split`); the two flags
  are appended after it. A player that takes its arguments differently can be
  wrapped in a one-line script.

A player is conformant for an utterance when, against the reference timeline
for the same utterance, profile and pace:

1. it has the **same number of beats**;
2. every beat's **`dot_mask` and `buzz_ms` match exactly**;
3. every beat's **`t_ms` is within ± `conformance_tolerance_ms`** of the
   reference (10 ms at spec v4 — under the shortest silence in the spec, so
   the tolerance can never hide a merged or missing beat).

The tolerance is absolute per beat, not cumulative: a renderer that slips 3 ms
on every cell is out after four cells. That is deliberate; a device keeps time
with its own clock from the utterance's first beat.

## What a timeline contains

In order, for one utterance (details in `docs/HAPTIC_TIMING_SPEC.md`, "The
reference renderer"):

1. the prefix when present — the mark's cells with the pace between them,
   `prefix_breath_ms` after the last, then the kind's tail pattern;
2. the kind's cue pattern;
3. one `processing` play when `body_pending` and no words have arrived (a
   device repeats it every `working_every_ms` on its own clock; that is
   device time and is not in the timeline);
4. the words — the pace between cells inside a word, `word_gap_ms` between
   words;
5. `tail_gap_ms` of silence after the last cell, then `end-of-message`.

On `six_actuator` a cell is one beat (`dot_mask` = the letter's mask,
`buzz_ms` = `cell_ms`). On `single_actuator` a cell is one beat per raised
dot (`dot_mask` = that dot's bit, `buzz_ms` = `slot_ms`) at the slot offsets
the spec table gives; the cell's duration is fixed whatever the letter. The
pace is clamped into the spec envelope before anything is rendered, so a
player asked for `--pace 10` must play at `cell_gap_min_ms`.

## How the real renderers plug in

- **The band (C sequencer).** The firmware workstream provides
  `firmware/app/ziv_qemu/host_player`: the host build of the sequencer
  driven on a virtual clock — the same pull-model code path as the bench and
  the FreeRTOS task — reading the utterance from stdin and printing one line
  per `HAPTIC_OUT_EV_BUZZ` with the virtual clock's `now_ms`, the step's
  `dot_mask` and `buzz_ms`. It uses the generated `HAPTIC_KIND_CUE_TABLE` /
  `HAPTIC_KIND_TAIL_TABLE`, `WORD_GAP_MS` and, for the single-actuator case,
  `SLOT_MS` / `SLOT_GAP_MS` / `COLUMN_GAP_MS` / `HAPTIC_SLOT_ORDER` from
  `haptic_timing.h`. The HAP log the firmware already emits carries the same
  three numbers per buzz; `tools/qemu_timeline.py` remains the differ for
  HAP-vs-HAP, this harness the differ for renderer-vs-reference.
- **The phone (web client, then the native app).** The client workstream
  provides `node client/dist/conformance.js`: the client's renderer under
  fake timers, so the timeline is what `setTimeout`/`vibrate` would have
  been asked for, printed without waiting. The native app does the same with
  an instrumented actuator.
- **Anything else** follows the same contract. The reference player in
  `players/reference.py` is the template; a new renderer is conformant when
  `run.py --player` passes on the profile it declares at enrollment.

## Changing the oracle

A spec change (`docs/haptic-timing.json`, then `tools/haptic_timing.py
--write`) or a renderer change moves the expected timelines. Run `run.py
--write`, read the diff of `expected/` — it is the felt change, beat by beat
— and commit it with the change. `--check` refuses a stale set, in the suite
and in CI, so the oracle cannot drift from itself.
