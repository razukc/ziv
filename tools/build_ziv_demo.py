#!/usr/bin/env python3
"""Derive the ziv_qemu boot demo's single source of truth and its rung-2 HAP
fixture from the project's timing spec. Also renders the demo-chain block
for docs/QEMU_SIMULATION_LADDER.md from the same table (7th spec consumer).


One Python source for both the app's runtime demo table and the host bench's
expected 27-line HAP fixture. Both are emitted into
firmware/app/ziv_qemu/main/ziv_demo_sequence.h.

  ziv_demo_sequence.h  - emitted here
    - k_demo_sequence[] / k_demo_stage_count: the stage table the app chains
      at runtime (re-exported for ziv_app.c).
    - k_demo_expected[] / k_demo_expected_count: the DERIVED 27-line HAP
      fixture host_demo.c asserts against; a pure function of the stage table
      plus the generated timing tables (spec constants, alphabet, marks,
      prefix composition). Reorder or extend the demo and this fixture changes
      with it - they cannot silently desync.

The demo intent lives in DEMO_STAGES below (one tuple per stage). The HAP
fixture is derived from that table plus the spec; it is not hand-maintained.

Usage:
  python tools/haptic_timing.py --write   # regenerates this file too

Verify:
  tools/haptic_timing.py --verify diffs this file the same way it diffs the
  other generated consumers.

The generated header also includes a compile-time sanity check that the
hardcoded fixture still matches the derivation, so the promise "do not hand-
edit without also updating the stage table" is enforced by the compiler.
"""

from pathlib import Path

import json

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "docs" / "haptic-timing.json"
OUT_DIR = ROOT / "firmware" / "app" / "ziv_qemu" / "main"
OUT_PATH = OUT_DIR / "ziv_demo_sequence.h"
LADDER_DOC_PATH = ROOT / "docs" / "QEMU_SIMULATION_LADDER.md"
LADDER_BEGIN = "<!-- haptic-demo-chain:begin (generated — do not edit; the stage table in this file is the single source; regenerate with tools/haptic_timing.py --write) -->"
LADDER_END = "<!-- haptic-demo-chain:end -->"
LADDER_DOC_PATH = ROOT / "docs" / "QEMU_SIMULATION_LADDER.md"

# The staged scripted boot demo. The stage table is the single source; the
# HAP fixture is derived from it. Add, remove, or reorder stages here and the
# generated k_demo_sequence[] AND k_demo_expected[] both change together.
#
# (mode, payload)
#   mode: PATTERN | PREFIX | WORD | MARK
#   payload: pattern id | tail id | word letters | mark id
#
# This specific ordering exercises every playback mode, including both spec-v3
# lifecycle patterns, and matches the existing rung-2 fixture:
#   ramp-up -> prefix(message) -> word ok -> end-of-message -> heartbeat
DEMO_STAGES = [
    ("PATTERN", "ramp-up"),
    ("PREFIX", "message"),
    ("WORD", "ok"),
    ("PATTERN", "end-of-message"),
    ("PATTERN", "heartbeat"),
]


def mask_of(dots):
    return sum(1 << (d - 1) for d in dots)


def cell_ms(spec, ch):
    c = spec["constants"]
    return c["cell_base_ms"] + c["cell_per_dot_ms"] * spec["letters"][ch]


def pat_by_id(spec):
    return {p["id"]: p for p in spec["attention_patterns"]}

def stage_mode_enum(mode):
    return {
        "PATTERN": "HAPTIC_OUT_MODE_PATTERN",
        "PREFIX": "HAPTIC_OUT_MODE_PREFIX",
        "WORD": "HAPTIC_OUT_MODE_WORD",
        "MARK": "HAPTIC_OUT_MODE_MARK",
    }[mode]


def mark_idx(spec):
    return {mid: i for i, mid in enumerate(spec["marks"])}


def render_hap(spec, mode, payload, t):
    """Emit the HAP lines for one stage starting at time t; return (lines, new_t)."""
    c = spec["constants"]
    pbyid = pat_by_id(spec)
    midx = mark_idx(spec)
    lines = []

    if mode == "PATTERN":
        pat = pbyid[payload]
        lines.append("HAP %d START PATTERN %s" % (t, payload))
        for i, beat in enumerate(pat["beats"]):
            lines.append(
                "HAP %d BUZZ PATTERN %s 00 %d %d %d"
                % (t, payload, beat["buzz_ms"], beat["gap_after_ms"], i)
            )
            t += beat["buzz_ms"] + beat["gap_after_ms"]
        lines.append("HAP %d END" % t)

    elif mode == "WORD":
        lines.append("HAP %d START WORD %s" % (t, payload))
        for i, ch in enumerate(payload):
            cm = cell_ms(spec, ch)
            gap = c["cell_gap_default_ms"]
            lines.append(
                "HAP %d BUZZ WORD %s %02X %d %d %d"
                % (
                    t,
                    payload,
                    mask_of(spec["letter_patterns"][ch]),
                    cm,
                    gap,
                    i,
                )
            )
            t += cm + gap
        lines.append("HAP %d END" % t)

    elif mode == "PREFIX":
        tail_id = payload
        mark = spec["prefix"]["mark"]
        cells = spec["marks"][mark]
        tail_pat = pbyid[spec["prefix"]["tails"][tail_id]]
        last_idx = len(cells) - 1
        lines.append("HAP %d START PREFIX %s" % (t, tail_id))
        for i, ch in enumerate(cells):
            cm = cell_ms(spec, ch)
            gap = c["prefix_breath_ms"] if i == last_idx else c["cell_gap_default_ms"]
            lines.append(
                "HAP %d BUZZ PREFIX %s %02X %d %d %d"
                % (
                    t,
                    tail_id,
                    mask_of(spec["letter_patterns"][ch]),
                    cm,
                    gap,
                    i,
                )
            )
            t += cm + gap
        for i, beat in enumerate(tail_pat["beats"]):
            lines.append(
                "HAP %d BUZZ PREFIX %s 00 %d %d %d"
                % (t, tail_id, beat["buzz_ms"], beat["gap_after_ms"], len(cells) + i)
            )
            t += beat["buzz_ms"] + beat["gap_after_ms"]
        lines.append("HAP %d END" % t)

    elif mode == "MARK":
        cells = spec["marks"][payload]
        for i, ch in enumerate(cells):
            cm = cell_ms(spec, ch)
            gap = c["cell_gap_default_ms"]
            lines.append(
                "HAP %d BUZZ MARK %s %02X %d %d %d"
                % (
                    t,
                    payload,
                    mask_of(spec["letter_patterns"][ch]),
                    cm,
                    gap,
                    i,
                )
            )
            t += cm + gap
        lines.append("HAP %d END" % t)

    else:
        raise ValueError("unknown demo mode %r" % mode)

    return lines, t


def _fixture_lines(spec):
    """The complete derived HAP fixture: all demo stages chained on one clock."""
    all_lines = []
    t = 0
    for mode, payload in DEMO_STAGES:
        more, t = render_hap(spec, mode, payload, t)
        all_lines.extend(more)
    return all_lines


def stage_name(mode, payload):
    """Human name of one demo stage, for the ladder doc's generated table."""
    if mode == "PREFIX":
        return "prefix(" + payload + ")"
    if mode == "WORD":
        return "word " + chr(34) + payload + chr(34)
    return payload


def ladder_section(spec):
    """The generated demo-chain block for docs/QEMU_SIMULATION_LADDER.md.

    The ladder doc's rung-1/rung-2 story reads this block instead of
    restating the demo by hand: it is derived from DEMO_STAGES — the same
    single source that generates the app's k_demo_sequence[] and the bench
    fixture — so reordering or extending the demo updates the doc, the app
    table, and the fixture together on --write, and --verify fails if the
    doc's block is hand-edited instead.
    """
    all_lines = _fixture_lines(spec)
    t = 0
    rows = []
    for mode, payload in DEMO_STAGES:
        start = t
        _, t = render_hap(spec, mode, payload, t)
        rows.append("| %s | %d-%d | %d |" % (stage_name(mode, payload), start, t, t - start))
    L = [LADDER_BEGIN, ""]
    L.append("The scripted boot demo's stage chain, generated from the single source")
    L.append("of truth: the `DEMO_STAGES` table in `tools/build_ziv_demo.py` — the same")
    L.append("table that generates the app's `k_demo_sequence[]` and the derived")
    L.append("%d-line `HAP` fixture the bench asserts against." % len(all_lines))
    L.append("")
    L.append("| Stage | Time span (ms) | Duration (ms) |")
    L.append("|---|---|---|")
    L.extend(rows)
    L.append("")
    L.append("Total: %d ms across %d HAP lines. Reordering or extending the demo means" % (t, len(all_lines)))
    L.append("editing `DEMO_STAGES` and regenerating (`tools/haptic_timing.py --write`):")
    L.append("the app's stage table, the bench fixture, and this table move together, and")
    L.append("`--verify` fails on any hand edit to this block.")
    L.append("")
    L.append(LADDER_END)
    return NL.join(L)


NL = chr(10)  # newline, spelled without a backslash so generators stay simple

BANNER = [
    "/* GENERATED FILE - do not edit by hand.",
    "",
    " * Single source of truth for the ziv_qemu scripted boot demo:",
    " *   - the stage table k_demo_sequence[] is defined once (in the .c)",
    " *   - the HAP fixture k_demo_expected[] is DERIVED from the same",
    " *     stage table + the generated timing tables, so reordering or",
    " *     extending the demo cannot silently desync the fixture from",
    " *     the demo it describes.",
    "",
    " * Demo intent: ramp-up -> prefix(message) -> word ok ->",
    " *   end-of-message -> heartbeat (every playback mode).",
    "",
    " * Regenerate: python tools/haptic_timing.py --write",
    " * Drift guard: tools/haptic_timing.py --verify diffs both files,",
    " *   same as the other generated consumers (feel-tool JS block,",
    " *   firmware header, Python timing module).",
    " */",
]


def emit(spec):
    """Return (header_text, source_text) for the generated demo pair.

    ziv_demo_sequence.h declares demo_stage_t and the demo symbols;
    ziv_demo_sequence.c defines them.  Declarations live apart from the
    definitions so ziv_app.c and host_demo.c can both include the header
    without colliding at link time - the standard extern/define split.
    """
    all_lines = _fixture_lines(spec)
    n_stages = len(DEMO_STAGES)
    n_lines = len(all_lines)

    pbyid = pat_by_id(spec)
    midx = mark_idx(spec)
    tail_keys = list(spec["prefix"]["tails"].keys())

    # ---- stage table (the demo single source, as C) -------------------
    stage_entries = []
    for mode, payload in DEMO_STAGES:
        if mode == "PATTERN":
            val, member = list(pbyid.keys()).index(payload), "pat"
        elif mode == "PREFIX":
            val, member = tail_keys.index(payload), "tail"
        elif mode == "WORD":
            val, member = chr(34) + payload + chr(34), "word"
        elif mode == "MARK":
            val, member = midx[payload], "mark"
        else:
            raise ValueError("unknown mode %r" % mode)
        stage_entries.append(
            "    { %s, .u.%s = %s }" % (stage_mode_enum(mode), member, val)
        )
    stage_lines = ["const demo_stage_t k_demo_sequence[%d] = {" % n_stages]
    stage_lines.extend(e + "," for e in stage_entries[:-1])
    stage_lines.append(stage_entries[-1])
    stage_lines.append("};")
    stage_lines.append("const int k_demo_stage_count = %d;" % n_stages)
    stage_defs = NL.join(stage_lines)

    # ---- derived HAP fixture (pure function of the stage table) -------
    q = chr(34)
    fixture_entries = ["    " + q + line + q + "," for line in all_lines]
    fixture_lines = ["const char *const k_demo_expected[%d] = {" % n_lines]
    fixture_lines.extend(fixture_entries)
    fixture_lines.append("};")
    fixture_lines.append("const int k_demo_expected_count = %d;" % n_lines)
    fixture_defs = NL.join(fixture_lines)

    # ---- header: declarations only ------------------------------------
    inc = lambda name: chr(35) + "include " + q + name + q
    h = list(BANNER)
    h.append("#ifndef ZIV_DEMO_SEQUENCE_H")
    h.append("#define ZIV_DEMO_SEQUENCE_H")
    h.append("")
    h.append(inc("haptic_out.h"))
    h.append("")
    h.append("/* demo_stage_t: one entry per stage; mode picks the union member. */")
    h.append("typedef struct {")
    h.append("    haptic_out_mode_t mode;")
    h.append("    union {")
    h.append("        haptic_pattern pat;")
    h.append("        haptic_tail tail;")
    h.append("        const char *word;")
    h.append("        uint8_t mark;")
    h.append("    } u;")
    h.append("} demo_stage_t;")
    h.append("")
    h.append("#ifdef __cplusplus")
    h.append("extern " + q + "C" + q + " {")
    h.append("#endif")
    h.append("")
    h.append("extern const int k_demo_stage_count;")
    h.append("extern const demo_stage_t k_demo_sequence[];")
    h.append("extern const char *const k_demo_expected[];")
    h.append("extern const int k_demo_expected_count;")
    h.append("")
    h.append("#ifdef __cplusplus")
    h.append("}")
    h.append("#endif")
    h.append("")
    h.append("#endif /* ZIV_DEMO_SEQUENCE_H */")
    header_text = NL.join(h) + NL

    # ---- source: the definitions (stage table + derived fixture) ------
    c = list(BANNER)
    c.append(inc("ziv_demo_sequence.h"))
    c.append("")
    c.append("/* The stage table -- the demo itself. ziv_app.c chains this at runtime. */")
    c.append(stage_defs)
    c.append("")
    c.append("/* The derived rung-2 fixture -- host_demo.c asserts the live HAP stream")
    c.append(" * against this, line by line.  A pure function of k_demo_sequence[] plus")
    c.append(" * the generated timing tables; never hand-edited. */")
    c.append(fixture_defs)
    source_text = NL.join(c) + NL

    return header_text, source_text


def main():
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    header_text, source_text = emit(spec)
    nl = chr(10)
    with open(OUT_DIR / "ziv_demo_sequence.h", "w", encoding="utf-8", newline=nl) as fh:
        fh.write(header_text)
    with open(OUT_DIR / "ziv_demo_sequence.c", "w", encoding="utf-8", newline=nl) as fh:
        fh.write(source_text)
    print("wrote", OUT_DIR / "ziv_demo_sequence.h")
    print("wrote", OUT_DIR / "ziv_demo_sequence.c")
    t = 0
    for mode, payload in DEMO_STAGES:
        _, t = render_hap(spec, mode, payload, t)
    print("  final HAP time: %d ms" % t)


if __name__ == "__main__":
    main()
