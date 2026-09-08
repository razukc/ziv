#!/usr/bin/env python3
"""haptic_timing.py — the haptic timing spec's generator and verifier.

docs/haptic-timing.json is the single source of truth for every buzz and
silence the Ziv haptic channel plays (plan §4 vocabulary + vibro-braille
cells). This script derives the consumers from it, so the phone mock and the
band play identical patterns by construction:

  - docs/haptic-name-marks.html        generated JS timing block + gap slider
  - firmware/haptic_out/haptic_timing.h  generated C constants + pattern tables
  - docs/HAPTIC_TIMING_SPEC.md         generated readable tables section

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
]
REQUIRED_UI = ["play_lead_ms", "loop_restart_ms", "cell_gap_step_ms"]


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


# --- validation -----------------------------------------------------------

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
        mark = rex.get("same_arc_as")
        if mark not in spec.get("marks", {}):
            problems.append(f"rename_examples.same_arc_as {mark!r}: not a known mark")
        else:
            arc = [letters.get(ch) for ch in spec["marks"][mark]]
            for word in rex.get("words", []):
                if not isinstance(word, str) or not re.fullmatch(r"[a-z]+", word):
                    problems.append(f"rename_examples: word {word!r} must be lowercase a-z")
                elif [letters.get(ch) for ch in word] != arc:
                    problems.append(
                        f"rename_examples: {word!r} does not spell the same dot-count arc as {mark!r}"
                    )

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
            if b.get("kind") not in (None, "ramp", "heart"):
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
        "PREFIX_BREATH={breath};".format(
            tick=c["tick_ms"], tick_gap=c["tick_gap_ms"], long=c["long_buzz_ms"],
            tail=c["tail_gap_ms"], breath=c["prefix_breath_ms"],
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
    ]
    L = [DOC_BEGIN, ""]
    L.append(f"### Constants — spec v{spec['version']}")
    L.append("")
    L.append("| Constant | ms | Feeds |")
    L.append("|---|---:|---|")
    for key, feeds in const_rows:
        L.append(f"| `{key}` | {c[key]} | {feeds} |")
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
    L.append(DOC_END)
    return "\n".join(L)


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

    js = js_block(spec)
    hdr = header(spec)
    doc = doc_tables(spec)

    if args.write:
        html = HTML_PATH.read_text(encoding="utf-8")
        patched = splice(html, JS_BEGIN, JS_END, js, problems, "html block")
        if patched is None:
            for p in problems:
                print("error:", p)
            return 1
        write_lf(HTML_PATH, rewrite_slider(patched, spec))
        HEADER_PATH.parent.mkdir(parents=True, exist_ok=True)
        write_lf(HEADER_PATH, hdr)
        doc_text = DOC_PATH.read_text(encoding="utf-8")
        patched = splice(doc_text, DOC_BEGIN, DOC_END, doc, problems, "spec doc tables")
        if patched is None:
            for p in problems:
                print("error:", p)
            return 1
        write_lf(DOC_PATH, patched)

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

    html = HTML_PATH.read_text(encoding="utf-8")
    if not block_matches(html, JS_BEGIN, JS_END, js):
        problems.append("html: generated timing block drifts from the spec (run tools/haptic_timing.py --write)")
    html_cross_checks(spec, html, problems)
    header_now = HEADER_PATH.read_text(encoding="utf-8") if HEADER_PATH.exists() else None
    if header_now != hdr:
        problems.append(f"{rel(HEADER_PATH)}: drifts from the spec (run tools/haptic_timing.py --write)")
    doc_now = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else None
    if doc_now is None or not block_matches(doc_now, DOC_BEGIN, DOC_END, doc):
        problems.append(f"{rel(DOC_PATH)}: generated tables missing or drifting")

    if problems:
        for p in problems:
            print("drift:", p)
        return 1

    print(f"spec ok: v{spec['version']} — {len(spec['attention_patterns'])} attention patterns, "
          f"{len(spec['marks'])} marks, {len(spec['letters'])} letters, "
          f"{sum(len(p['beats']) for p in spec['attention_patterns'])} beats")
    print("  docs/haptic-name-marks.html        timing block + slider in sync")
    print("  firmware/haptic_out/haptic_timing.h  in sync")
    print("  docs/HAPTIC_TIMING_SPEC.md           tables in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
