#!/usr/bin/env python3
"""haptic_timing.py — the haptic timing spec's generator and verifier.

docs/haptic-timing.json is the single source of truth for every buzz and
silence the Ziv haptic channel plays (plan §4 vocabulary + vibro-braille
cells). This script derives the consumers from it, so the phone mock and the
band play identical patterns by construction:

  - docs/haptic-name-marks.html        generated JS timing block + gap slider
  - firmware/haptic_out/haptic_timing.h  generated C constants + pattern tables
  - ziv/haptics/tables.py              generated Python timing module (relay, tests, tools)
  - ziv/haptics/tables.py              the same module at its home in the ziv package
                                       (the reference renderer and the conformance
                                       harness read KINDS / PROFILES / constants from it)
  - docs/HAPTIC_TIMING_SPEC.md         generated readable tables section
  - firmware/app/ziv_qemu/main/ziv_demo_sequence.{h,c}
                                       generated scripted boot demo (the stage
                                       table single source + its derived HAP fixture)
  - docs/QEMU_SIMULATION_LADDER.md     generated demo-chain block (the ladder
                                       doc's rung-1/rung-2 story reads the same
                                       DEMO_STAGES single source)

Usage:
  python tools/haptic_timing.py            # verify all consumers match the spec
  python tools/haptic_timing.py --write    # regenerate the consumers from the spec

Verify mode exits 1 on any drift, so it can stand in as a hermetic check.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs" / "haptic-timing.json"
HTML_PATH = ROOT / "docs" / "haptic-name-marks.html"
HEADER_PATH = ROOT / "firmware" / "haptic_out" / "haptic_timing.h"
DOC_PATH = ROOT / "docs" / "HAPTIC_TIMING_SPEC.md"
# The generated Python module: the relay, the reference renderer and the
# suite import it as ziv.haptics.tables.
PY_PKG_PATH = ROOT / "ziv" / "haptics" / "tables.py"
DEMO_DIR = ROOT / "firmware" / "app" / "ziv_qemu" / "main"
DEMO_H_PATH = DEMO_DIR / "ziv_demo_sequence.h"
DEMO_C_PATH = DEMO_DIR / "ziv_demo_sequence.c"
LADDER_DOC_PATH = ROOT / "docs" / "QEMU_SIMULATION_LADDER.md"
FIRMWARE_MAX_WORD_LEN_H = ROOT / "firmware" / "haptic_out" / "haptic_out.h"
RE_MAX_WORD_LEN = re.compile(r"^\s*#define\s+HAPTIC_OUT_MAX_WORD_LEN\s+(\d+)\s*$", re.MULTILINE)

JS_BEGIN = "/* haptic-timing:begin (generated — edit docs/haptic-timing.json, then run: python tools/haptic_timing.py --write) */"
JS_END = "/* haptic-timing:end */"
DOC_BEGIN = "<!-- haptic-timing:begin (generated — do not edit; regenerate with tools/haptic_timing.py --write) -->"
DOC_END = "<!-- haptic-timing:end -->"

REF_KEY = {
    "tick": "tick_ms",
    "tick_gap": "tick_gap_ms",
    "long": "long_buzz_ms",
    "tail": "tail_gap_ms",
}
JS_SYMBOL = {"tick": "TICK", "tick_gap": "TICK_GAP", "long": "LONG", "tail": "TAIL_GAP"}
C_SYMBOL = {"tick": "TICK_MS", "tick_gap": "TICK_GAP_MS", "long": "LONG_BUZZ_MS", "tail": "TAIL_GAP_MS"}

REQUIRED_CONSTANTS = [
    "cell_base_ms", "cell_per_dot_ms", "cell_gap_default_ms", "cell_gap_min_ms",
    "cell_gap_max_ms", "tick_ms", "tick_gap_ms", "long_buzz_ms", "tail_gap_ms",
    "prefix_breath_ms",
    # spec v4: the word boundary, the working cadence, the conformance tolerance
    "word_gap_ms", "working_every_ms", "conformance_tolerance_ms",
]
# Renderer profiles the reference renderer knows (ziv.wire.Profile names them
# too; the spec is the source and the wire enum is checked against it in the
# ziv suite).  A slots profile is the single-actuator encoding: six time slots
# per cell, one per dot, in `order`.
REQUIRED_PROFILES = {"six_actuator": "chord", "single_actuator": "slots"}
SLOT_COUNT = 6
SLOT_FIELDS = ("slot_ms", "slot_gap_ms", "column_gap_ms")
REQUIRED_UI = ["play_lead_ms", "loop_restart_ms", "cell_gap_step_ms", "spell_max_letters"]


def js_str(s):
    """A JSON string literal is a valid JS string literal."""
    return json.dumps(s, ensure_ascii=False)


def cell_ms(spec, letter):
    c = spec["constants"]
    return c["cell_base_ms"] + c["cell_per_dot_ms"] * spec["letters"][letter]


def braille_char(dots):
    """Unicode braille pattern for a list of dot positions (1..6)."""
    bits = 0
    for d in dots:
        bits |= 1 << (d - 1)
    return chr(0x2800 + bits)


def bitmask(dots):
    """Integer bitmask for a list of dot positions (1..6); bit n = dot n."""
    bits = 0
    for d in dots:
        bits |= 1 << (d - 1)
    return bits


def arc_name(arc):
    """Spoken shape of a dot-count arc: heavy = 4+ dots, light = fewer."""
    return "-".join("heavy" if d >= 4 else "light" for d in arc)


# --- validation -----------------------------------------------------------

def rename_word_problems(spec, word):
    """Protocol §5 option-B validation for one candidate word.

    Returns a list of problem strings (empty = the word spells the same
    dot-count arc as rename_examples.same_arc_as).  Shared by the spec's
    own validate() and by tools/rename_check.py.
    """
    problems = []
    letters = spec.get("letters", {})
    rex = spec.get("rename_examples") or {}
    mark = rex.get("same_arc_as")
    if mark not in spec.get("marks", {}):
        return [f"spec: rename_examples.same_arc_as {mark!r} is not a known mark"]
    if not isinstance(word, str) or not re.fullmatch(r"[a-z]+", word):
        return [f"{word!r}: must be lowercase a-z"]
    if word == "".join(spec["marks"][mark]):
        return [f"{word!r}: is the mark's current word — option B changes the word"]
    if len(word) > spec.get("ui", {}).get("spell_max_letters", 12):
        return [f"{word!r}: {len(word)} letters exceeds spell_max_letters "
                f"({spec['ui']['spell_max_letters']})"]
    arc = [letters.get(ch) for ch in spec["marks"][mark]]
    word_arc = [letters.get(ch) for ch in word]
    if word_arc != arc:
        problems.append(
            f"{word!r} spells {'-'.join(str(d) for d in word_arc)} ({arc_name(word_arc)}) — "
            f"the {mark!r} mark is {'-'.join(str(d) for d in arc)} ({arc_name(arc)})")
    return problems


def validate(spec, problems):
    c = spec.get("constants", {})
    for key in REQUIRED_CONSTANTS:
        if key not in c or not isinstance(c[key], int) or c[key] <= 0:
            problems.append(f"constants.{key}: missing or not a positive integer")
    for key in REQUIRED_UI:
        if key not in spec.get("ui", {}):
            problems.append(f"ui.{key}: missing")

    letters = spec.get("letters", {})
    if len(letters) != 26 or set(letters) != set("abcdefghijklmnopqrstuvwxyz"):
        problems.append("letters: expected the full 26-letter Grade-1 alphabet")
    for letter, dots in letters.items():
        if not (1 <= dots <= 6):
            problems.append(f"letters.{letter}: dot count {dots} outside 1..6")

    letter_patterns = spec.get("letter_patterns", {})
    if set(letter_patterns) != set("abcdefghijklmnopqrstuvwxyz"):
        problems.append("letter_patterns: expected the full 26-letter alphabet")
    else:
        for ch, dots in sorted(letter_patterns.items()):
            ok = (isinstance(dots, list) and len(dots) >= 1 and
                  all(isinstance(d, int) and 1 <= d <= 6 for d in dots) and
                  len(set(dots)) == len(dots))
            if not ok:
                problems.append(f"letter_patterns.{ch}: expected distinct dot positions in 1..6")
            elif letters.get(ch) != len(dots):
                problems.append(
                    f"letter_patterns.{ch}: {len(dots)} dots contradicts letters.{ch}={letters.get(ch)}"
                )

    rex = spec.get("rename_examples")
    if rex is not None:
        for word in rex.get("words", []):
            problems.extend(rename_word_problems(spec, word))

    pattern_ids = set()
    for p in spec.get("attention_patterns", []):
        pid = p.get("id", "?")
        if pid in pattern_ids:
            problems.append(f"attention_patterns: duplicate id {pid!r}")
        pattern_ids.add(pid)
        beats = p.get("beats", [])
        if not beats:
            problems.append(f"{pid}: no beats")
        for i, b in enumerate(beats):
            for field in ("buzz_ms", "gap_after_ms"):
                v = b.get(field)
                if not isinstance(v, int) or not (1 <= v <= 5000):
                    problems.append(f"{pid} beat {i}: {field}={v} outside 1..5000")
            for value_field, ref_field in (("buzz_ms", "buzz_ref"), ("gap_after_ms", "gap_ref")):
                ref = b.get(ref_field)
                if ref is None:
                    continue
                if ref not in REF_KEY:
                    problems.append(f"{pid} beat {i}: unknown {ref_field} {ref!r}")
                elif REF_KEY[ref] in c and b[value_field] != c[REF_KEY[ref]]:
                    problems.append(
                        f"{pid} beat {i}: {value_field}={b[value_field]} contradicts "
                        f"{ref_field}={ref!r} ({REF_KEY[ref]}={c[REF_KEY[ref]]})"
                    )
            if b.get("kind") not in (None, "ramp", "heart", "fall"):
                problems.append(f"{pid} beat {i}: unknown kind {b.get('kind')!r}")
        if beats and beats[-1].get("gap_ref") != "tail":
            problems.append(f"{pid}: last beat must end with gap_ref 'tail'")

    for mid, cells in spec.get("marks", {}).items():
        if not cells:
            problems.append(f"marks.{mid}: empty")
        for ch in cells:
            if ch not in letters:
                problems.append(f"marks.{mid}: letter {ch!r} not in the alphabet")

    prefix = spec.get("prefix", {})
    if prefix.get("mark") not in spec.get("marks", {}):
        problems.append(f"prefix.mark {prefix.get('mark')!r}: not a known mark")
    for tail_name, pat_id in prefix.get("tails", {}).items():
        if pat_id not in pattern_ids:
            problems.append(f"prefix.tails.{tail_name}: pattern {pat_id!r} not found")
    if prefix.get("breath_after_mark_ms_ref") != "prefix_breath_ms":
        problems.append("prefix.breath_after_mark_ms_ref: must be 'prefix_breath_ms'")

    validate_v4(spec, pattern_ids, problems)


def pattern_total_ms(pattern):
    """Buzz plus silence of every beat: how long one play of the pattern takes."""
    return sum(b.get("buzz_ms", 0) + b.get("gap_after_ms", 0) for b in pattern.get("beats", []))


def validate_v4(spec, pattern_ids, problems):
    """Spec v4: word gap, working cadence, conformance tolerance, kinds, profiles.

    Ranges encode the reasoning in the spec's `rationale` block, so an
    accidental edit that breaks the argument fails here instead of on a
    wrist: the word gap sits strictly between the default cell gap and the
    prefix breath; the working cadence is at least one full `processing`
    play; the tolerance is below the shortest silence anywhere in the spec.
    """
    c = spec.get("constants", {})
    patterns = {p.get("id"): p for p in spec.get("attention_patterns", [])}

    def pos_int(value):
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    if all(pos_int(c.get(k)) for k in ("word_gap_ms", "cell_gap_default_ms", "prefix_breath_ms")):
        if not (c["cell_gap_default_ms"] < c["word_gap_ms"] < c["prefix_breath_ms"]):
            problems.append(
                f"constants.word_gap_ms={c['word_gap_ms']}: must sit strictly between "
                f"cell_gap_default_ms ({c['cell_gap_default_ms']}) and prefix_breath_ms "
                f"({c['prefix_breath_ms']}) — a word boundary is longer than a cell gap and "
                f"never outranks the who/why breath")
    if pos_int(c.get("working_every_ms")):
        working = patterns.get("processing")
        if working is None:
            problems.append("constants.working_every_ms: needs a 'processing' pattern to repeat")
        elif c["working_every_ms"] < pattern_total_ms(working):
            problems.append(
                f"constants.working_every_ms={c['working_every_ms']}: shorter than one play of "
                f"'processing' ({pattern_total_ms(working)} ms) — repeats would overlap")
        if c["working_every_ms"] > 10000:
            problems.append(f"constants.working_every_ms={c['working_every_ms']}: above 10000 — "
                            f"waiting must stay legible (plan §4 invariant 3)")
    if pos_int(c.get("conformance_tolerance_ms")):
        silences = [b["gap_after_ms"] for p in patterns.values() for b in p.get("beats", [])
                    if isinstance(b.get("gap_after_ms"), int)]
        silences += [c[k] for k in ("cell_gap_min_ms", "tail_gap_ms", "prefix_breath_ms", "word_gap_ms")
                     if pos_int(c.get(k))]
        for prof in spec.get("profiles", {}).values():
            if isinstance(prof, dict):
                silences += [prof[k] for k in ("slot_gap_ms", "column_gap_ms") if pos_int(prof.get(k))]
        buzzes = [b["buzz_ms"] for p in patterns.values() for b in p.get("beats", [])
                  if isinstance(b.get("buzz_ms"), int)]
        if pos_int(c.get("cell_base_ms")):
            buzzes.append(c["cell_base_ms"])
        shortest = min(silences + buzzes) if (silences or buzzes) else None
        if shortest is not None and c["conformance_tolerance_ms"] >= shortest:
            problems.append(
                f"constants.conformance_tolerance_ms={c['conformance_tolerance_ms']}: must be below "
                f"the shortest buzz or silence in the spec ({shortest} ms) or a tolerance could hide "
                f"a merged or missing beat")

    kinds = spec.get("kinds")
    if not isinstance(kinds, dict) or not kinds:
        problems.append("kinds: missing or empty — every utterance kind needs a cue and a tail")
        kinds = {}
    for kind, entry in kinds.items():
        if not re.fullmatch(r"[a-z][a-z_]*", kind):
            problems.append(f"kinds.{kind!r}: kind ids are lower-case words")
        if not isinstance(entry, dict) or set(entry) != {"cue", "tail"}:
            problems.append(f"kinds.{kind}: expected exactly {{cue, tail}}")
            continue
        for role in ("cue", "tail"):
            if entry[role] not in pattern_ids:
                problems.append(f"kinds.{kind}.{role}: pattern {entry[role]!r} not found")
    tails = spec.get("prefix", {}).get("tails", {})
    for tail_name, pat_id in tails.items():
        if tail_name not in kinds:
            problems.append(f"prefix.tails.{tail_name}: not a kind in `kinds`")
        elif isinstance(kinds[tail_name], dict) and kinds[tail_name].get("tail") != pat_id:
            problems.append(
                f"prefix.tails.{tail_name}={pat_id!r} disagrees with kinds.{tail_name}.tail="
                f"{kinds[tail_name].get('tail')!r} — one mapping, two views")

    profiles = spec.get("profiles")
    if not isinstance(profiles, dict):
        problems.append("profiles: missing — the reference renderer must know every profile")
        profiles = {}
    for pid, encoding in REQUIRED_PROFILES.items():
        if pid not in profiles:
            problems.append(f"profiles.{pid}: missing")
        elif profiles[pid].get("encoding") != encoding:
            problems.append(f"profiles.{pid}.encoding: expected {encoding!r}")
    for pid, prof in profiles.items():
        if not isinstance(prof, dict):
            problems.append(f"profiles.{pid}: expected an object")
            continue
        encoding = prof.get("encoding")
        if encoding == "chord":
            extra = set(prof) - {"encoding"}
            if extra:
                problems.append(f"profiles.{pid}: a chord profile carries no slot timing ({sorted(extra)})")
        elif encoding == "slots":
            for field in SLOT_FIELDS:
                v = prof.get(field)
                if not pos_int(v) or v > 5000:
                    problems.append(f"profiles.{pid}.{field}={v!r}: expected a positive integer ≤ 5000")
            order = prof.get("order")
            is_permutation = (isinstance(order, list)
                              and all(isinstance(d, int) and not isinstance(d, bool) for d in order)
                              and sorted(order) == list(range(1, SLOT_COUNT + 1)))
            if not is_permutation:
                problems.append(f"profiles.{pid}.order={order!r}: must be a permutation of 1..{SLOT_COUNT}")
            extra = set(prof) - {"encoding", "order", *SLOT_FIELDS}
            if extra:
                problems.append(f"profiles.{pid}: unknown fields {sorted(extra)}")
        else:
            problems.append(f"profiles.{pid}.encoding={encoding!r}: expected 'chord' or 'slots'")


def slot_cell_ms(spec, profile_id="single_actuator"):
    """Fixed duration of one cell on a slots profile: every slot, every slot
    gap but the last, and the column break after the third slot."""
    prof = spec["profiles"][profile_id]
    return (SLOT_COUNT * prof["slot_ms"] + (SLOT_COUNT - 1) * prof["slot_gap_ms"]
            + prof["column_gap_ms"])


def slot_offsets_ms(spec, profile_id="single_actuator"):
    """Start offset of each slot inside a cell, in `order` order."""
    prof = spec["profiles"][profile_id]
    out, t = [], 0
    for i in range(SLOT_COUNT):
        out.append(t)
        t += prof["slot_ms"]
        if i < SLOT_COUNT - 1:
            t += prof["slot_gap_ms"]
        if i == 2:
            t += prof["column_gap_ms"]
    return out


# --- JS block (feel-tool) --------------------------------------------------

def js_beat(b):
    ms = JS_SYMBOL[b["buzz_ref"]] if b.get("buzz_ref") else str(b["buzz_ms"])
    gap = JS_SYMBOL[b["gap_ref"]] if b.get("gap_ref") else str(b["gap_after_ms"])
    kind = ",k:'" + b["kind"] + "'" if b.get("kind") else ""
    return "{ms:%s,gap:%s%s}" % (ms, gap, kind)


def js_block(spec):
    c = spec["constants"]
    L = [JS_BEGIN]
    L.append(f"var CELL_BASE={c['cell_base_ms']}, CELL_PER_DOT={c['cell_per_dot_ms']};")
    L.append(
        "var TICK={tick},TICK_GAP={tick_gap},LONG={long},TAIL_GAP={tail},"
        "PREFIX_BREATH={breath},WORD_GAP={word_gap};".format(
            tick=c["tick_ms"], tick_gap=c["tick_gap_ms"], long=c["long_buzz_ms"],
            tail=c["tail_gap_ms"], breath=c["prefix_breath_ms"], word_gap=c["word_gap_ms"],
        )
    )
    letters = "abcdefghijklmnopqrstuvwxyz"
    L.append("var LETTERS = {")
    entries = [
        ch + ":{n:" + str(spec["letters"][ch]) + ",g:'" + braille_char(spec["letter_patterns"][ch]) + "'}"
        for ch in letters
    ]
    for i in range(0, 26, 4):
        line = ", ".join(entries[i:i + 4])
        if i + 4 < len(entries):
            line += ","
        L.append("  " + line)
    L.append("};")
    L.append("var ATTENTION = [")
    patterns = spec["attention_patterns"]
    for i, p in enumerate(patterns):
        comma = "," if i < len(patterns) - 1 else ""
        L.append(f"  {{id:'{p['id']}', word:{js_str(p['word'])}, meaning:{js_str(p['meaning'])},")
        L.append("   beats:[" + ",".join(js_beat(b) for b in p["beats"]) + "],")
        L.append("   note:" + js_str(p["note"]) + "}" + comma)
    L.append("];")
    L.append("window.ATTENTION=ATTENTION;")
    L.append(f"var SPELL_MAX={spec['ui']['spell_max_letters']};")
    note = spec.get("note", "")
    if note:
        L.append("/* spell_max_letters cap on the spell box; the firmware's runtime word ceiling (HAPTIC_OUT_MAX_WORD_LEN=16) is a separate, deliberate asymmetry. See docs/haptic-timing.json note. */")
        L.append("var SPELL_LIMIT_NOTE=" + js_str(note) + ";")
    L.append("function dur(d){ return CELL_BASE + CELL_PER_DOT * d; }")
    rex = spec.get("rename_examples", {})
    mark = rex.get("same_arc_as", "")
    cells = spec["marks"].get(mark, [])
    arc = "\u00b7".join(str(cell_ms(spec, ch)) for ch in cells)
    L.append("var SPELL_FILLS_NOTE = " + js_str(rex.get("note", "")) + ";")
    L.append("var SPELL_FILLS = [")
    words = rex.get("words", [])
    for i, w in enumerate(words):
        note = "option B \u2014 same arc as " + mark + " (" + arc + ")"
        comma = "," if i < len(words) - 1 else ""
        L.append("  {word:" + js_str(w) + ", note:" + js_str(note) + "}" + comma)
    L.append("];")
    L.append(JS_END)
    return "\n".join(L)


# --- C header (firmware/haptic_out) ----------------------------------------

def c_name(pattern_id):
    return "HAPTIC_" + pattern_id.upper().replace("-", "_")


def c_beat(b):
    buzz = C_SYMBOL[b["buzz_ref"]] if b.get("buzz_ref") else str(b["buzz_ms"])
    gap = C_SYMBOL[b["gap_ref"]] if b.get("gap_ref") else str(b["gap_after_ms"])
    return "{%s, %s}" % (buzz, gap)


def header(spec):
    c = spec["constants"]
    patterns = spec["attention_patterns"]
    letters = "abcdefghijklmnopqrstuvwxyz"
    dots = [spec["letters"][ch] for ch in letters]
    A = lambda s: L.append(s)  # noqa: E731

    L = []
    A("/* GENERATED FILE — do not edit by hand.")
    A(" *")
    A(" * Source of truth: docs/haptic-timing.json")
    A(" * Regenerate:      python tools/haptic_timing.py --write")
    A(" * Consumer:        firmware/haptic_out — DRV2605L vibro-braille sequencer + attention patterns (plan §5)")
    A(" * Readable spec:   docs/HAPTIC_TIMING_SPEC.md")
    A(" *")
    A(" * The phone feel-tool (docs/haptic-name-marks.html) is generated from the same")
    A(" * JSON — never tune a duration here without regenerating both sides.")
    A(" */")
    A("#ifndef HAPTIC_TIMING_H")
    A("#define HAPTIC_TIMING_H")
    A("")
    A("#include <stdint.h>")
    A("")
    A("#ifdef __cplusplus")
    A('extern "C" {')
    A("#endif")
    A("")
    A(f"#define HAPTIC_SPEC_VERSION {spec['version']}")
    A("")
    A("/* Vibro-braille cell: buzz_ms = CELL_BASE_MS + CELL_PER_DOT_MS * dot_count */")
    A(f"#define CELL_BASE_MS {c['cell_base_ms']}")
    A(f"#define CELL_PER_DOT_MS {c['cell_per_dot_ms']}")
    A("")
    A("/* Inter-cell silence is the playback-speed setting (user-tunable on device). */")
    A(f"#define CELL_GAP_DEFAULT_MS {c['cell_gap_default_ms']}")
    A(f"#define CELL_GAP_MIN_MS {c['cell_gap_min_ms']}")
    A(f"#define CELL_GAP_MAX_MS {c['cell_gap_max_ms']}")
    A("")
    A("/* Attention-vocabulary constants (plan §4). One beat = buzz, then silence. */")
    A(f"#define TICK_MS {c['tick_ms']}")
    A(f"#define TICK_GAP_MS {c['tick_gap_ms']}")
    A(f"#define LONG_BUZZ_MS {c['long_buzz_ms']}")
    A(f"#define TAIL_GAP_MS {c['tail_gap_ms']}")
    A(f"#define PREFIX_BREATH_MS {c['prefix_breath_ms']}")
    A("")
    A("/* Spec v4: silence between words of one utterance (inside a word the gap is")
    A(" * the pace); the period at which a device repeats HAPTIC_PROCESSING on its")
    A(" * own clock while an utterance's body is pending (architecture §5.1). */")
    A(f"#define WORD_GAP_MS {c['word_gap_ms']}")
    A(f"#define WORKING_EVERY_MS {c['working_every_ms']}")
    A("")
    single = spec["profiles"]["single_actuator"]
    A("/* single_actuator profile (a phone, architecture §5.2): one cell is")
    A(" * HAPTIC_SLOT_COUNT time slots, one per dot, in HAPTIC_SLOT_ORDER; a raised dot")
    A(" * is a SLOT_MS pulse in its slot, an absent dot SLOT_MS of silence; SLOT_GAP_MS")
    A(" * follows every slot but the last and COLUMN_GAP_MS more follows the third, so")
    A(f" * every cell lasts {slot_cell_ms(spec)} ms whatever the letter.  The band (six_actuator)")
    A(" * drives the raised dots together for haptic_cell_ms() instead. */")
    A(f"#define SLOT_MS {single['slot_ms']}")
    A(f"#define SLOT_GAP_MS {single['slot_gap_ms']}")
    A(f"#define COLUMN_GAP_MS {single['column_gap_ms']}")
    A(f"#define HAPTIC_SLOT_COUNT {SLOT_COUNT}")
    A(f"#define HAPTIC_SLOT_CELL_MS {slot_cell_ms(spec)}")
    A("static const uint8_t HAPTIC_SLOT_ORDER[HAPTIC_SLOT_COUNT] = { "
      + ", ".join(str(d) for d in single["order"]) + " }; /* dot numbers, 1..6 */")
    A("")
    A("/* One haptic beat: buzz for buzz_ms, then stay silent for gap_after_ms. */")
    A("typedef struct {")
    A("    uint16_t buzz_ms;")
    A("    uint16_t gap_after_ms;")
    A("} haptic_beat;")
    A("")
    A("/* --- Attention patterns (plan §4) --- */")
    A("")
    for p in patterns:
        name = c_name(p["id"])
        A(f"#define {name}_LEN {len(p['beats'])}")
        A(f"static const haptic_beat {name}[{name}_LEN] = {{")
        A("    " + ", ".join(c_beat(b) for b in p["beats"]))
        A("};")
        A("")
    A("typedef enum {")
    for i, p in enumerate(patterns):
        suffix = " = 0" if i == 0 else ""
        A("    HAPTIC_PAT_" + p["id"].upper().replace("-", "_") + f"{suffix},")
    A("    HAPTIC_PAT_COUNT")
    A("} haptic_pattern;")
    A("")
    A("static const haptic_beat *const HAPTIC_PATTERN_TABLE[HAPTIC_PAT_COUNT] = {")
    A("    " + ", ".join(c_name(p["id"]) for p in patterns))
    A("};")
    A("static const uint8_t HAPTIC_PATTERN_LEN_TABLE[HAPTIC_PAT_COUNT] = {")
    A("    " + ", ".join(f"{c_name(p['id'])}_LEN" for p in patterns))
    A("};")
    A("")
    A("/* --- Grade-1 alphabet: dot counts and derived cell durations (index 0 = 'a') --- */")
    A("#define HAPTIC_LETTERS 26")
    A("/* " + " ".join(letters) + " */")
    A("static const uint8_t HAPTIC_LETTER_DOTS[HAPTIC_LETTERS] = {")
    A("    " + ", ".join(str(d) for d in dots))
    A("};")
    A("static const uint16_t HAPTIC_LETTER_MS[HAPTIC_LETTERS] = {")
    A("    " + ", ".join(str(c["cell_base_ms"] + c["cell_per_dot_ms"] * d) for d in dots))
    A("};")
    A("static const uint8_t HAPTIC_LETTER_MASKS[HAPTIC_LETTERS] = {")
    A("    /* dot bitmask, bit n = dot n (DRV2605L / LRA pin mapping lives in haptic_out.c) */")
    A("    " + ", ".join("0x%02X" % bitmask(spec["letter_patterns"][ch]) for ch in letters))
    A("};")
    A("")
    A("/* Cell buzz duration for a letter 'a'..'z'. */")
    A("static inline uint16_t haptic_cell_ms(char letter) {")
    A("    return (uint16_t) (CELL_BASE_MS + CELL_PER_DOT_MS * HAPTIC_LETTER_DOTS[letter - 'a']);")
    A("}")
    A("")
    A("/* --- The five candidate marks (letter indices, 0 = 'a'); protocol §0 loads all five --- */")
    mark_names = list(spec["marks"].keys())
    for mid, cells in spec["marks"].items():
        const = "HAPTIC_MARK_" + mid.upper()
        idx = [ord(ch) - ord("a") for ch in cells]
        A(f"#define {const}_LEN {len(cells)}")
        A(f"static const uint8_t {const}[{const}_LEN] = {{ " +
          ", ".join(str(i) for i in idx) + f" }}; /* {' '.join(cells)} */")
    A("#define HAPTIC_MARK_COUNT " + str(len(mark_names)))
    A("static const uint8_t *const HAPTIC_MARK_TABLE[HAPTIC_MARK_COUNT] = {")
    A("    " + ", ".join("HAPTIC_MARK_" + m.upper() for m in mark_names))
    A("};")
    A("static const uint8_t HAPTIC_MARK_LEN_TABLE[HAPTIC_MARK_COUNT] = {")
    A("    " + ", ".join(f"HAPTIC_MARK_{m.upper()}_LEN" for m in mark_names))
    A("};")
    A("")
    A("/* --- Rename examples: protocol §5 option B — same arc, different word (arc-validated only; legal screening per plan §1) --- */")
    rex = spec.get("rename_examples")
    if rex:
        mark = rex.get("same_arc_as", "")
        arc = [spec["letters"][ch] for ch in spec["marks"][mark]]
        A(f"/* same dot-count arc as {mark}: {'-'.join(str(d) for d in arc)} */")
        A(f"#define HAPTIC_RENAME_ARC_REF HAPTIC_MARK_" + mark.upper())
        A(f"#define HAPTIC_RENAME_WORD_COUNT " + str(len(rex.get("words", []))))
    else:
        A("#define HAPTIC_RENAME_WORD_COUNT 0")
    A("")
    A("/* --- Name-mark prefix (plan §4): play a mark, keep silent PREFIX_BREATH_MS, then the tail --- */")
    tails = spec["prefix"]["tails"]
    A("typedef enum {")
    for i, tail_name in enumerate(tails):
        suffix = " = 0" if i == 0 else ""
        A(f"    HAPTIC_TAIL_{tail_name.upper()}{suffix},")
    A("    HAPTIC_TAIL_COUNT")
    A("} haptic_tail;")
    A("")
    A("static const haptic_pattern HAPTIC_PREFIX_TAIL_TABLE[HAPTIC_TAIL_COUNT] = {")
    A("    " + ", ".join("HAPTIC_PAT_" + pid.upper().replace("-", "_") for pid in tails.values()))
    A("};")
    A(f"#define HAPTIC_PREFIX_MARK_INDEX {list(spec['marks']).index(spec['prefix']['mark'])}  /* {spec['prefix']['mark']} — index into HAPTIC_MARK_TABLE */")
    A("")
    A("/* --- Utterance kinds (architecture §2): the arrival cue and the prefix tail per kind. --- */")
    A("/* Order follows the spec's `kinds` block; the wire's Kind enum names the same ids. */")
    kinds = spec["kinds"]
    A("typedef enum {")
    for i, kind in enumerate(kinds):
        suffix = " = 0" if i == 0 else ""
        A(f"    HAPTIC_KIND_{kind.upper()}{suffix},")
    A("    HAPTIC_KIND_COUNT")
    A("} haptic_kind;")
    A("")
    A("static const haptic_pattern HAPTIC_KIND_CUE_TABLE[HAPTIC_KIND_COUNT] = {")
    A("    " + ", ".join("HAPTIC_PAT_" + e["cue"].upper().replace("-", "_") for e in kinds.values()))
    A("};")
    A("static const haptic_pattern HAPTIC_KIND_TAIL_TABLE[HAPTIC_KIND_COUNT] = {")
    A("    " + ", ".join("HAPTIC_PAT_" + e["tail"].upper().replace("-", "_") for e in kinds.values()))
    A("};")
    A("")
    A("#ifdef __cplusplus")
    A("}")
    A("#endif")
    A("")
    A("#endif /* HAPTIC_TIMING_H */")
    return "\n".join(L) + "\n"


# --- readable doc tables ----------------------------------------------------

def doc_tables(spec):
    c = spec["constants"]
    const_rows = [
        ("cell_base_ms", "braille cell buzz floor"),
        ("cell_per_dot_ms", "added per raised dot: `cell_ms = cell_base + cell_per_dot × dots`"),
        ("cell_gap_default_ms", f"silence between cells — the playback-speed control (tunable "
                                f"{c['cell_gap_min_ms']}–{c['cell_gap_max_ms']} ms, step {spec['ui']['cell_gap_step_ms']} ms)"),
        ("tick_ms", "the attention tick"),
        ("tick_gap_ms", "silence between ticks inside a pattern"),
        ("long_buzz_ms", "the error buzz"),
        ("tail_gap_ms", "silence after a pattern's last beat"),
        ("prefix_breath_ms", "silence between the name mark and its attention tail"),
        ("word_gap_ms", "silence between two words of one utterance (inside a word: the pace) — "
                        "longer than the default cell gap, shorter than the prefix breath"),
        ("working_every_ms", "period at which a device repeats `processing` on its own clock while "
                             "an utterance's body is pending"),
        ("conformance_tolerance_ms", "per-beat start-time drift (±) a real renderer may show against "
                                     "the reference timeline; dot mask and buzz length must match exactly"),
    ]
    L = [DOC_BEGIN, ""]
    L.append(f"### Constants — spec v{spec['version']}")
    L.append("")
    L.append("| Constant | ms | Feeds |")
    L.append("|---|---:|---|")
    for key, feeds in const_rows:
        L.append(f"| `{key}` | {c[key]} | {feeds} |")
    L.append("")
    ui = spec["ui"]
    L.append("### UI vs. runtime limits — do not unify")
    L.append("")
    L.append(
        f"- `spell_max_letters` = {ui['spell_max_letters']}: the feel-tool page's spell-box affordance — "
        f"it caps how long a word the page headlines for the wearer. "
        f"- The band firmware's runtime ceiling is `HAPTIC_OUT_MAX_WORD_LEN` = 16: "
        f"the longest word the motors will actually play. "
        f"These are intentionally different settings for different layers (page vs. device), "
        f"not two views of one number — do not unify them."
    )
    L.append("")
    L.append("### Attention patterns (plan §4)")
    L.append("")
    L.append("| Pattern | Meaning | Beats — buzz/gap in ms |")
    L.append("|---|---|---|")
    for p in spec["attention_patterns"]:
        beats = " · ".join(f"{b['buzz_ms']}/{b['gap_after_ms']}" for b in p["beats"])
        L.append(f"| `{p['id']}` | {p['meaning']} | {beats} |")
    L.append("")
    L.append("### Cell durations — the full Grade-1 alphabet")
    L.append("")
    L.append("```")
    items = [f"{ch}={cell_ms(spec, ch)}" for ch in "abcdefghijklmnopqrstuvwxyz"]
    for i in range(0, 26, 8):
        L.append(" ".join(items[i:i + 8]))
    L.append("```")
    L.append("")
    L.append("| Letter | Dots | Pattern | Glyph |")
    L.append("|---|---|---|---|")
    for ch in "abcdefghijklmnopqrstuvwxyz":
        dots = spec["letter_patterns"][ch]
        L.append(f"| {ch} | {len(dots)} | {'-'.join(str(d) for d in dots)} | {braille_char(dots)} |")
    L.append("")
    rex = spec.get("rename_examples")
    if rex:
        mark = rex.get("same_arc_as", "")
        cells = spec["marks"].get(mark, [])
        arc = "-".join(str(spec["letters"][ch]) for ch in cells)
        L.append("### Rename examples (protocol §5 option B)")
        L.append("")
        L.append(
            f"Same dot-count arc as **{mark}** ({arc}): "
            + ", ".join(f"**{w}**" for w in rex.get("words", []))
            + " — arc-validated only; legal screening per plan §1 required before adoption."
        )
        L.append("")
    L.append("### The five candidate marks")
    L.append("")
    L.append("| Mark | Letters | Arc — buzz/gap in ms (last cell bare) |")
    L.append("|---|---|---|")
    for mid, cells in spec["marks"].items():
        arc = " · ".join(
            str(cell_ms(spec, ch)) + ("" if i == len(cells) - 1 else f"/{c['cell_gap_default_ms']}")
            for i, ch in enumerate(cells)
        )
        L.append(f"| {mid} | {'·'.join(cells)} | {arc} |")
    p = spec["prefix"]
    cells = spec["marks"][p["mark"]]
    arc = " · ".join(
        str(cell_ms(spec, ch)) + ("" if i == len(cells) - 1 else f"/{c['cell_gap_default_ms']}")
        for i, ch in enumerate(cells)
    )
    tails = " · ".join(f"{k} = `{v}`" for k, v in p["tails"].items())
    L.append("")
    L.append("### Prefix composition (plan §4)")
    L.append("")
    L.append(f"The {p['mark']} mark ({arc}) → silence {c['prefix_breath_ms']} ms → attention tail: {tails}.")
    L.append("")
    L.append("### Kinds — arrival cue and prefix tail (architecture §2)")
    L.append("")
    L.append("| Kind | Cue | Tail after the mark |")
    L.append("|---|---|---|")
    for kind, e in spec["kinds"].items():
        L.append(f"| `{kind}` | `{e['cue']}` | `{e['tail']}` |")
    L.append("")
    L.append("### Renderer profiles (architecture §5.2)")
    L.append("")
    single = spec["profiles"]["single_actuator"]
    chord_ms = [cell_ms(spec, ch) for ch in "abcdefghijklmnopqrstuvwxyz"]
    mean_chord = sum(chord_ms) / len(chord_ms)
    L.append(
        f"- `six_actuator` (`chord`): a cell is its raised dots driven together for "
        f"`cell_ms` ({min(chord_ms)}–{max(chord_ms)} ms, mean {mean_chord:.0f} ms over the alphabet).")
    L.append(
        f"- `single_actuator` (`slots`): a cell is {SLOT_COUNT} time slots in dot order "
        f"{'-'.join(str(d) for d in single['order'])}; a raised dot is a `slot_ms` = {single['slot_ms']} ms "
        f"pulse in its slot, an absent dot {single['slot_ms']} ms of silence; `slot_gap_ms` = "
        f"{single['slot_gap_ms']} ms follows every slot but the last and `column_gap_ms` = "
        f"{single['column_gap_ms']} ms more follows the third. Every cell lasts "
        f"{SLOT_COUNT} × {single['slot_ms']} + {SLOT_COUNT - 1} × {single['slot_gap_ms']} + "
        f"{single['column_gap_ms']} = **{slot_cell_ms(spec)} ms** whatever the letter "
        f"({slot_cell_ms(spec) / mean_chord:.1f} × the mean chord cell).")
    L.append("")
    L.append("| Slot | Dot | Pulse starts at (ms into the cell) |")
    L.append("|---:|---:|---:|")
    for i, (dot, off) in enumerate(zip(single["order"], slot_offsets_ms(spec)), start=1):
        L.append(f"| {i} | {dot} | {off} |")
    L.append("")
    L.append(DOC_END)
    return "\n".join(L)


# --- Python consumer (ziv/haptics/tables.py) --------------------------------

def py_module(spec):
    """The generated Python timing module: one derivation for tests, the
    relay, and tools. Same shape as the C header — constants, per-letter
    tables, pattern beats in spec order — so the drift guard holds all
    consumers with one checker."""
    c = spec["constants"]
    letters = "abcdefghijklmnopqrstuvwxyz"
    patterns = spec["attention_patterns"]
    marks = spec["marks"]
    L = []
    A = L.append
    A("\"\"\"ziv.haptics.tables — GENERATED Python consumer of the timing spec.")
    A("")
    A("Do not edit by hand; regenerate with:  python tools/haptic_timing.py --write")
    A("Source of truth: docs/haptic-timing.json (spec v%s)." % spec["version"])
    A("")
    A("One derivation for every Python side that needs the haptic vocabulary")
    A("(the Ziv relay, tests, tools): dot tables, cell durations, and pattern")
    A("beats — the same numbers the phone feel-tool (JS block) and the band")
    A("(firmware/haptic_out/haptic_timing.h) play. The drift guard holds all")
    A("consumers together: the checker regenerates and diffs this file too.")
    A("\"\"\"")
    A("")
    A("SPEC_VERSION = %d" % spec["version"])
    A("")
    A("# The spec itself, verbatim, so the relay can serve it (GET /spec) and any")
    A("# renderer can derive its durations from the single source at runtime.")
    A("SPEC = " + repr(spec))
    A("")
    A("# Cell rule: buzz_ms = CELL_BASE_MS + CELL_PER_DOT_MS * dots.")
    A("CELL_BASE_MS = %d" % c["cell_base_ms"])
    A("CELL_PER_DOT_MS = %d" % c["cell_per_dot_ms"])
    A("")
    A("# Attention/lifecycle constants (plan §4). One beat = buzz, then silence.")
    for key in ("tick_ms", "tick_gap_ms", "long_buzz_ms", "tail_gap_ms", "prefix_breath_ms"):
        A("%s = %d" % (key.upper(), c[key]))
    A("")
    A("# Playback-speed envelope + UI cap (spec: constants + ui blocks).")
    A("CELL_GAP_DEFAULT_MS = %d" % c["cell_gap_default_ms"])
    A("CELL_GAP_MIN_MS = %d" % c["cell_gap_min_ms"])
    A("CELL_GAP_MAX_MS = %d" % c["cell_gap_max_ms"])
    A("SPELL_MAX_LETTERS = %d" % spec["ui"]["spell_max_letters"])
    A("")
    A("# Grade-1 alphabet: dots, motor bitmask (bit n = dot n), cell ms (index 0 = 'a').")
    A("LETTERS = '%s'" % letters)
    A("LETTER_DOTS = {")
    for ch in letters:
        A("    '%s': %d," % (ch, spec["letters"][ch]))
    A("}")
    A("LETTER_MASKS = {")
    for ch in letters:
        A("    '%s': 0x%02X," % (ch, bitmask(spec["letter_patterns"][ch])))
    A("}")
    A("LETTER_MS = {")
    for ch in letters:
        A("    '%s': %d," % (ch, cell_ms(spec, ch)))
    A("}")
    A("")
    A("# Attention patterns, in spec order (index == the C HAPTIC_PAT_* enum).")
    A("PATTERN_IDS = (")
    for p in patterns:
        A("    '%s'," % p["id"])
    A(")")
    A("PATTERN_INDEX = {pid: i for i, pid in enumerate(PATTERN_IDS)}")
    A("# id -> ((buzz_ms, gap_after_ms), ...) — the beats, in spec order.")
    A("PATTERN_BEATS = {")
    for p in patterns:
        beats = ", ".join("(%d, %d)" % (b["buzz_ms"], b["gap_after_ms"]) for b in p["beats"])
        # Trailing comma so a single-beat pattern stays a tuple of tuples.
        A("    '%s': (%s,)," % (p["id"], beats))
    A("}")
    A("")
    A("# Candidate marks: letters per position, in spec order (index == the C enum).")
    A("MARK_IDS = (")
    for mid in marks:
        A("    '%s'," % mid)
    A(")")
    A("MARK_INDEX = {mid: i for i, mid in enumerate(MARK_IDS)}")
    A("MARK_CELLS = {")
    for mid, cells in marks.items():
        A("    '%s': %r," % (mid, tuple(cells)))
    A("}")
    A("")
    prefix = spec["prefix"]
    A("# Name-mark prefix composition (plan §4): mark, breath, then the tail pattern.")
    A("PREFIX_MARK = '%s'" % prefix["mark"])
    A("PREFIX_TAILS = {")
    for tail_name, pat_id in prefix["tails"].items():
        A("    '%s': '%s'," % (tail_name, pat_id))
    A("}")
    A("")
    A("# Spec v4: the silence between words (inside a word the gap is the pace), the")
    A("# period at which a device repeats 'processing' while a body is pending, and")
    A("# the per-beat |Δt| the conformance harness allows a real renderer.")
    A("WORD_GAP_MS = %d" % c["word_gap_ms"])
    A("WORKING_EVERY_MS = %d" % c["working_every_ms"])
    A("CONFORMANCE_TOLERANCE_MS = %d" % c["conformance_tolerance_ms"])
    A("")
    A("# Utterance kind -> arrival cue and prefix tail pattern ids (architecture §2).")
    A("KINDS = {")
    for kind, e in spec["kinds"].items():
        A("    '%s': {'cue': '%s', 'tail': '%s'}," % (kind, e["cue"], e["tail"]))
    A("}")
    A("")
    A("# Renderer profiles (architecture §5.2), verbatim from the spec. A 'chord'")
    A("# profile drives a cell's dots together for cell_ms(); a 'slots' profile plays")
    A("# one cell as SLOT_COUNT time slots in `order`, a slot_ms pulse per raised dot.")
    A("SLOT_COUNT = %d" % SLOT_COUNT)
    A("PROFILES = {")
    for pid, prof in spec["profiles"].items():
        A("    '%s': %r," % (pid, prof))
    A("}")
    A("")
    A("")
    A("def cell_ms(letter: str) -> int:")
    A("    \"\"\"Cell buzz duration for a letter 'a'..'z'.\"\"\"")
    A("    return CELL_BASE_MS + CELL_PER_DOT_MS * LETTER_DOTS[letter]")
    A("")
    A("")
    A("def pattern_beats(pattern_id: str) -> tuple:")
    A("    \"\"\"The (buzz_ms, gap_after_ms) beats of one attention pattern.\"\"\"")
    A("    return PATTERN_BEATS[pattern_id]")
    A("")
    A("")
    A("def pattern_ms(pattern_id: str) -> int:")
    A("    \"\"\"How long one play of a pattern takes: every buzz and every gap, tail included.\"\"\"")
    A("    return sum(buzz + gap for buzz, gap in PATTERN_BEATS[pattern_id])")
    A("")
    A("")
    A("def slot_cell_ms(profile_id: str = 'single_actuator') -> int:")
    A("    \"\"\"Fixed duration of one cell on a slots profile (every slot, every slot gap")
    A("    but the last, and the column break after the third slot).\"\"\"")
    A("    p = PROFILES[profile_id]")
    A("    return SLOT_COUNT * p['slot_ms'] + (SLOT_COUNT - 1) * p['slot_gap_ms'] + p['column_gap_ms']")
    A("")
    return "\n".join(L) + "\n"


# --- patching / checking ----------------------------------------------------

def splice(text, begin, end, generated, problems, label):
    i, j = text.find(begin), text.find(end)
    if i == -1 or j == -1 or j < i:
        problems.append(f"{label}: markers not found")
        return None
    return text[:i] + generated + text[j + len(end):]


def block_matches(text, begin, end, generated):
    i, j = text.find(begin), text.find(end)
    if i == -1 or j == -1 or j < i:
        return False
    return text[i:j + len(end)] == generated


def rewrite_slider(html, spec):
    c, ui = spec["constants"], spec["ui"]
    html = re.sub(
        r"<input id=gap type=range min=\d+ max=\d+ step=\d+ value=\d+>",
        f"<input id=gap type=range min={c['cell_gap_min_ms']} max={c['cell_gap_max_ms']} "
        f"step={ui['cell_gap_step_ms']} value={c['cell_gap_default_ms']}>",
        html,
    )
    return re.sub(
        r"(Gap between cells: <span id=gapval>)\d+(</span> ms)",
        r"\g<1>" + str(c["cell_gap_default_ms"]) + r"\g<2>",
        html,
    )


def html_cross_checks(spec, html, problems):
    c = spec["constants"]
    m = re.search(r"<input id=gap type=range min=(\d+) max=(\d+) step=(\d+) value=(\d+)>", html)
    if not m:
        problems.append("html: gap slider line not found")
    elif m.groups() != (str(c["cell_gap_min_ms"]), str(c["cell_gap_max_ms"]),
                        str(spec["ui"]["cell_gap_step_ms"]), str(c["cell_gap_default_ms"])):
        problems.append(f"html: gap slider {m.groups()} drifts from the spec envelope")
    m = re.search(r"Gap between cells: <span id=gapval>(\d+)</span> ms", html)
    if not m:
        problems.append("html: gapval label not found")
    elif m.group(1) != str(c["cell_gap_default_ms"]):
        problems.append("html: gapval label drifts from cell_gap_default_ms")
    for m in re.finditer(r"([a-z]):\{n:(\d+),g:'", html):
        letter, dots = m.group(1), int(m.group(2))
        if spec["letters"].get(letter) != dots:
            problems.append(f"html: LETTERS[{letter}] has {dots} dots, spec says {spec['letters'].get(letter)}")
    for m in re.finditer(r"\{id:'([a-z]+)', word:'[^']*', cells:\[([^\]]*)\]", html):
        mid = m.group(1)
        cells = re.findall(r"[a-z]", m.group(2))
        if spec["marks"].get(mid) != cells:
            problems.append(f"html: MARKS {mid} = {cells}, spec says {spec['marks'].get(mid)}")
    m = re.search(r"var M1_POOL = \[([^\]]*)\]", html)
    if m:
        valid = set(spec["marks"]) | {p["id"] for p in spec["attention_patterns"]}
        for pool_id in re.findall(r"'([^']+)'", m.group(1)):
            if pool_id not in valid:
                problems.append(f"html: M1_POOL id {pool_id!r} is not in the spec")


def rel(path):
    """Repo-relative label for messages; fall back to the full path when the
    consumer lives outside the repo (e.g. a test pointing at temp files)."""
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


_build_ziv_demo = None


def demo_texts(spec):
    """The generated demo pair (ziv_demo_sequence.h/.c) from tools/build_ziv_demo.

    The scripted boot demo's stage table is the demo's single source; the
    27-line HAP fixture is derived from it. Both are timing-spec consumers:
    the fixture is a pure function of the stage table plus the generated
    timing vocabulary, so the drift guard holds them like every other
    consumer.
    """
    global _build_ziv_demo
    if _build_ziv_demo is None:
        tools_dir = str(ROOT / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import build_ziv_demo
        _build_ziv_demo = build_ziv_demo
    return _build_ziv_demo.emit(spec)


def ladder_text(spec):
    """The generated demo-chain block for the QEMU ladder doc.

    Shares build_ziv_demo's DEMO_STAGES single source with the app's stage
    table and the bench fixture: the doc's rung-1/rung-2 description is a
    pure function of that table plus the spec, so the drift guard holds it
    like every other consumer.
    """
    demo_texts(spec)  # ensure the shared module is imported (and derivable)
    return _build_ziv_demo.ladder_section(spec)


def write_consumers(spec, problems):
    """Regenerate every consumer from the spec.  Used by --write and by
    tools/rename_check.py -a (a spec change invalidates nothing else: the
    consumers are pure functions of the JSON)."""
    js = js_block(spec)
    hdr = header(spec)
    doc = doc_tables(spec)

    py = py_module(spec)

    html = HTML_PATH.read_text(encoding="utf-8")
    patched = splice(html, JS_BEGIN, JS_END, js, problems, "html block")
    if patched is None:
        return False
    write_lf(HTML_PATH, rewrite_slider(patched, spec))
    HEADER_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_lf(HEADER_PATH, hdr)
    PY_PKG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_lf(PY_PKG_PATH, py)
    try:
        demo_h, demo_c = demo_texts(spec)
    except (KeyError, ValueError) as exc:
        problems.append("demo stages: cannot derive the ziv_qemu demo pair "
                        "from the spec: %s" % exc)
        return False
    write_lf(DEMO_H_PATH, demo_h)
    write_lf(DEMO_C_PATH, demo_c)
    ladder = ladder_text(spec)
    ladder_now = LADDER_DOC_PATH.read_text(encoding="utf-8")
    patched3 = splice(ladder_now, _build_ziv_demo.LADDER_BEGIN,
                      _build_ziv_demo.LADDER_END, ladder, problems, "ladder doc demo-chain block")
    if patched3 is None:
        return False
    write_lf(LADDER_DOC_PATH, patched3)
    doc_text = DOC_PATH.read_text(encoding="utf-8")
    patched2 = splice(doc_text, DOC_BEGIN, DOC_END, doc, problems, "spec doc tables")
    if patched2 is None:
        return False
    write_lf(DOC_PATH, patched2)
    return True


def write_lf(path, text):
    """Write with LF endings regardless of platform, preserving repo line style."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def load_spec(problems):
    try:
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"spec: cannot load {SPEC_PATH}: {exc}")
        return None
    validate(spec, problems)
    return spec


def check_asymmetry(spec, firmware_hdr, problems):
    """The feel-tool UI cap and the firmware runtime ceiling are intentionally
    different.  If they accidentally unify, verification should fail."""
    ui_spell = spec["ui"]["spell_max_letters"]
    if ui_spell >= 16:
        problems.append(
            f"ui.spell_max_letters={ui_spell}: the page spell-box cap must stay below "
            f"HAPTIC_OUT_MAX_WORD_LEN (16) — do not unify the UI and runtime limits"
        )
        return
    m = RE_MAX_WORD_LEN.search(firmware_hdr)
    if not m:
        problems.append(f"{rel(FIRMWARE_MAX_WORD_LEN_H)}: HAPTIC_OUT_MAX_WORD_LEN not found")
        return
    firmware_len = int(m.group(1))
    if firmware_len <= ui_spell:
        problems.append(
            f"ui.spell_max_letters={ui_spell} is not below HAPTIC_OUT_MAX_WORD_LEN={firmware_len}: "
            f"the asymmetry between the page spell box and the firmware runtime ceiling must be preserved"
        )


def main():
    ap = argparse.ArgumentParser(description="Generate/verify the haptic timing consumers from docs/haptic-timing.json")
    ap.add_argument("--write", action="store_true", help="regenerate consumers from the spec (default: verify only)")
    args = ap.parse_args()

    problems = []
    spec = load_spec(problems)
    if spec is None or problems:
        for p in problems:
            print("spec error:", p)
        return 1

    if args.write:
        if not write_consumers(spec, problems):
            for p in problems:
                print("error:", p)
            return 1

    # verification (always runs — also right after --write, so it checks what landed on disk)
    problems = []
    spec = load_spec(problems)
    if spec is None:
        for p in problems:
            print("spec error:", p)
        return 1
    js = js_block(spec)
    hdr = header(spec)
    doc = doc_tables(spec)

    py = py_module(spec)

    html = HTML_PATH.read_text(encoding="utf-8")
    if not block_matches(html, JS_BEGIN, JS_END, js):
        problems.append("html: generated timing block drifts from the spec (run tools/haptic_timing.py --write)")
    html_cross_checks(spec, html, problems)
    header_now = HEADER_PATH.read_text(encoding="utf-8") if HEADER_PATH.exists() else None
    if header_now != hdr:
        problems.append(f"{rel(HEADER_PATH)}: drifts from the spec (run tools/haptic_timing.py --write)")
    py_now = PY_PKG_PATH.read_text(encoding="utf-8") if PY_PKG_PATH.exists() else None
    if py_now != py:
        problems.append(f"{rel(PY_PKG_PATH)}: drifts from the spec (run tools/haptic_timing.py --write)")
    doc_now = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else None
    if doc_now is None or not block_matches(doc_now, DOC_BEGIN, DOC_END, doc):
        problems.append(f"{rel(DOC_PATH)}: generated tables missing or drifting")
    if FIRMWARE_MAX_WORD_LEN_H.exists():
        check_asymmetry(spec, FIRMWARE_MAX_WORD_LEN_H.read_text(encoding="utf-8"), problems)
    else:
        problems.append(f"{rel(FIRMWARE_MAX_WORD_LEN_H)}: missing (cannot check asymmetry)")
    try:
        demo_h, demo_c = demo_texts(spec)
        ladder = ladder_text(spec)
    except (KeyError, ValueError) as exc:
        problems.append("demo stages: cannot derive the ziv_qemu demo pair "
                        "from the spec: %s" % exc)
    else:
        for path, text in ((DEMO_H_PATH, demo_h), (DEMO_C_PATH, demo_c)):
            now = path.read_text(encoding="utf-8") if path.exists() else None
            if now != text:
                problems.append(f"{rel(path)}: drifts from the spec "
                                "(run tools/haptic_timing.py --write)")
        ladder_now = LADDER_DOC_PATH.read_text(encoding="utf-8") if LADDER_DOC_PATH.exists() else None
        if ladder_now is None or not block_matches(ladder_now, _build_ziv_demo.LADDER_BEGIN,
                                                   _build_ziv_demo.LADDER_END, ladder):
            problems.append(f"{rel(LADDER_DOC_PATH)}: generated demo-chain block "
                            "missing or drifting (run tools/haptic_timing.py --write)")

    if problems:
        for p in problems:
            print("drift:", p)
        return 1

    print(f"spec ok: v{spec['version']} — {len(spec['attention_patterns'])} attention patterns, "
          f"{len(spec['marks'])} marks, {len(spec['letters'])} letters, "
          f"{sum(len(p['beats']) for p in spec['attention_patterns'])} beats")
    print("  docs/haptic-name-marks.html        timing block + slider in sync")
    print("  firmware/haptic_out/haptic_timing.h  in sync")
    print("  ziv/haptics/tables.py                in sync")
    print("  docs/HAPTIC_TIMING_SPEC.md           tables in sync")
    print("  firmware/app/ziv_qemu/main/ziv_demo_sequence.h  demo table in sync")
    print("  firmware/app/ziv_qemu/main/ziv_demo_sequence.c  demo fixture in sync")
    print("  docs/QEMU_SIMULATION_LADDER.md       demo-chain block in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
