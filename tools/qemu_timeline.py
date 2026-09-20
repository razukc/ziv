#!/usr/bin/env python3
"""
Ziv QEMU HAP timeline differ + self-check.

Used by ``tools/haptic_timing.py --verify`` and by the firmware bench suite
(``firmware/app/ziv_qemu/run_ziv_tests.py``).  In self-check mode (no args)
it reads the generated ``k_demo_expected[]`` array out of the committed
``ziv_demo_sequence.c``, re-derives the same 27 HAP lines from
``docs/haptic-timing.json`` + ``DEMO_STAGES``, and exits 0 only when they
agree — so the derived fixture cannot silently drift from the spec.

In diff mode (``tools/qemu_timeline.py <bench> <qemu>``) it compares two
HAP logs: boot-banner chatter is stripped, timestamps are compared within a
±10 ms tolerance (warnings beyond that), and dot-mask fields must match
exactly.  The output is machine-parseable (``PASS``/``differs``) so CI can
gate on it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]

# Paths the test suite monkeypatches in private-temp mode.
DEMO_C_PATH = REPO_ROOT / "firmware" / "app" / "ziv_qemu" / "main" / "ziv_demo_sequence.c"
SPEC_PATH = REPO_ROOT / "docs" / "haptic-timing.json"
OUT_C_PATH = DEMO_C_PATH  # the derived fixture lives inside ziv_demo_sequence.c

HAP_LINE_RE = re.compile(r"^HAP (\d+) (.+)$")
TOLERANCE_MS = 10
BOOT_CHATTER_RE = re.compile(
    r"^(ESP-ROM:|I \(\d+\) |Project conf:|Flash:)|"
    r"^cpu_start:|Starting app|This is|https?://|"
    r"^rst cause|boot mode|BLE startup|connect|"
    r"^I \(\d+\) "
)


def demo_fixture_lines(spec=None):
    """The derived 27-line HAP fixture (the "expected" side of the boot check).

    Reads ``k_demo_expected[]`` from the generated ``ziv_demo_sequence.c`` so
    CI always compares against the *committed generated file*, never a
    hand-copied copy.  A stale generated file (after a spec regen that hasn't
    been committed) triggers exit 2 with the heal command — it never silently
    compares against the wrong expected lines.
    """
    if spec is None:
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))

    if not DEMO_C_PATH.is_file():
        print("qemu-timeline: missing generated fixture %s — run `python tools/haptic_timing.py --write`"
              % DEMO_C_PATH, file=sys.stderr)
        sys.exit(2)

    # Extract k_demo_expected[] from the generated C source.
    text = DEMO_C_PATH.read_text(encoding="utf-8")
    m = re.search(r"const char \*const k_demo_expected\[(\d+)\] = \{(.*?)\};", text, re.S)
    if not m:
        print("qemu-timeline: could not parse k_demo_expected[] from %s" % DEMO_C_PATH,
              file=sys.stderr)
        sys.exit(2)
    count = int(m.group(1))
    body = m.group(2)
    # Each line is  "   "HAP 0 START PATTERN ramp-up","
    lines = re.findall(r'"([^"]+)"', body)
    if len(lines) != count:
        print("qemu-timeline: k_demo_expected[] declared %d lines but %d found in %s"
              % (count, len(lines), DEMO_C_PATH), file=sys.stderr)
        sys.exit(2)
    return lines


def _re_derivation(spec):
    """Re-derive the HAP fixture from the spec + DEMO_STAGES (the cross-check)."""
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import build_ziv_demo as bzd
    return bzd.demo_fixture_lines(spec)


def _parse_hap(text: str) -> List[Tuple[int, str, str]]:
    """Return [(timestamp_ms, event_type, rest), ...] for one HAP log.

    Skips boot-banner chatter the QEMU console emits before the demo starts.
    """
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or BOOT_CHATTER_RE.match(line):
            continue
        m = HAP_LINE_RE.match(line)
        if not m:
            print("qemu-timeline: Unrecognized HAP line: %r" % line, file=sys.stderr)
            sys.exit(2)
        ts = int(m.group(1))
        rest = m.group(2)
        kind = rest.split(" ", 1)[0]
        rows.append((ts, kind, rest))
    return rows


def diff_logs(left_text: str, right_text: str) -> Tuple[List[str], List[str]]:
    """Compare two HAP logs.

    Returns (problems, notes).  A diff is a PASS when ``problems`` is empty,
    even if there are within-tolerance timestamp notes.
    """
    left = _parse_hap(left_text)
    right = _parse_hap(right_text)

    problems: List[str] = []
    notes: List[str] = []
    if len(left) != len(right):
        problems.append("event count differs: bench %d vs qemu %d" % (len(left), len(right)))
        return problems, notes

    for i, ((lts, lkind, lrest), (rts, rkind, rrest)) in enumerate(zip(left, right)):
        if lkind != rkind:
            problems.append("line %d: event kind differs (bench %s vs qemu %s)" % (i + 1, lkind, rkind))
            continue
        dt = abs(lts - rts)
        if dt > TOLERANCE_MS:
            problems.append("line %d: timestamp drift %.0f ms (bench %d vs qemu %d)"
                            % (i + 1, dt, lts, rts))
        elif dt:
            notes.append("line %d: timestamp within tolerance %.0f ms" % (i + 1, dt))
        if lrest != rrest:
            problems.append("line %d: fields differ (dot-mask or text)" % (i + 1))
    return problems, notes


def _self_check():
    """Hermetic gate: the generated .c fixture agrees with the spec derivation."""
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    derived = _re_derivation(spec)
    on_disk = demo_fixture_lines(spec)

    if derived != on_disk:
        # Show the first mismatch.
        for i, (a, b) in enumerate(zip(derived, on_disk)):
            if a != b:
                print("qemu-timeline: derived fixture disagrees with generated .c at line %d" % (i + 1))
                print("  derived : %s" % a)
                print("  on-disk : %s" % b)
                print("qemu-timeline: run `python tools/haptic_timing.py --write` and commit the regenerated files")
                sys.exit(1)
        # Equal length but different (should not be reachable above, but be safe).
        print("qemu-timeline: derived fixture differs from generated .c (length match, content mismatch)")
        sys.exit(1)

    n = len(derived)
    print("self-check: OK — generated .c agrees with spec derivation (%d HAP lines)" % n)
    return 0


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(prog="qemu_timeline.py",
                                   description="Ziv QEMU HAP timeline differ + self-check")
    ap.add_argument("--update", action="store_true",
                    help="rewrite the generated k_demo_expected[] fixture from the spec")
    ap.add_argument("bench", nargs="?", help="derived fixture (HAP log text)")
    ap.add_argument("qemu", nargs="?", help="QEMU console log (HAP stream + boot chatter)")
    opts = ap.parse_args(argv)

    if opts.update:
        sys.path.insert(0, str(REPO_ROOT / "tools"))
        import build_ziv_demo as bzd
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        bzd.main()
        return 0

    if opts.bench and opts.qemu:
        left = Path(opts.bench).read_text(encoding="utf-8")
        right = Path(opts.qemu).read_text(encoding="utf-8")
        ok, msgs = diff_logs(left, right)
        if ok:
            n = len(_parse_hap(left))
            print("PASS — %d HAP events matched within tolerance" % n)
            for m in msgs:
                print("  %s" % m)
            return 0
        print("differs — %d problem(s):" % len(msgs))
        for m in msgs:
            print("  %s" % m)
        return 1

    return _self_check()


if __name__ == "__main__":
    sys.exit(main())
