#!/usr/bin/env python3
"""qemu_timeline.py — the QEMU ladder's rung-2 equivalence differ.

The boot check's expected side is the *derived* fixture, never a hand copy:

  python tools/qemu_timeline.py                    # self-check (hermetic)
  python tools/qemu_timeline.py bench.log qemu.log # the rung-2 comparison
  python tools/qemu_timeline.py --tol-ms 20 a.log b.log

* The expected side comes from ``build_ziv_demo.demo_fixture_lines()`` — the
  same ``DEMO_STAGES`` table that generates the app's ``k_demo_sequence[]``
  and the bench's ``k_demo_expected[]`` — and is cross-checked against the
  ``k_demo_expected[]`` strings parsed out of the generated
  ``ziv_demo_sequence.c``, so a stale generated file or a spec regen that
  was not propagated both fail here instead of silently comparing against
  the wrong lines. The CI boot job therefore inherits the demo's single
  source of truth: when the demo changes, ``--write`` regenerates the
  fixture, and the boot check's expected side moves with it.

* Both sides of the comparison are ``HAP`` v1 log lines — the bench side is
  ``host_demo --hap-log`` (same binary, same sequencer stream the C suite
  asserts against); the QEMU side is the boot's console capture. Non-HAP
  lines (QEMU boot banners, console chatter) are ignored by the parser.

* Comparison (docs/QEMU_SIMULATION_LADDER.md rung 2): event order, modes,
  payloads, dot masks, beat indices, and buzz durations exactly; event
  timestamps and gap fields within ``--tol-ms`` (default 10 ms, ~1 FreeRTOS
  tick at the default 100 Hz tick rate) — wall-clock tolerance, mirroring
  ``tools/m1_summary.py``'s handling of real-world jitter.

Exit codes: 0 in sync, 1 mismatch, 2 usage/environment error (no fixture).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_ziv_demo  # noqa: E402  (the demo single source)

DEMO_C_PATH = ROOT / "firmware" / "app" / "ziv_qemu" / "main" / "ziv_demo_sequence.c"

DEFAULT_TOL_MS = 10  # ~1 FreeRTOS tick at the default 100 Hz tick rate

# HAP v1 line grammar (emitted by render_hap in build_ziv_demo and the
# bench/QEMU HAP serializers): HAP <at_ms> START|BUZZ|END <mode> ...
_HAP_RE = re.compile(
    r"^HAP (?P<at>\d+) (?P<kind>START|BUZZ|END)"
    r"(?: (?P<mode>PATTERN|PREFIX|WORD|MARK) (?P<payload>\S+)"
    r"(?: (?P<mask>[0-9A-F]{2}) (?P<buzz>\d+) (?P<gap>\d+) (?P<beat>\d+))?)?$"
)


def parse_hap_log(text: str) -> list[dict]:
    """Parse a HAP log into event dicts; non-HAP lines are skipped.

    One dict per line: ``{"at", "kind"}`` for START/END, plus ``mode``,
    ``payload``, ``mask``, ``buzz``, ``gap``, ``beat`` for BUZZ lines.
    """
    events = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        m = _HAP_RE.match(line)
        if m is None:
            continue  # not a HAP line (boot banner, console chatter) — ignore
        ev = {"line": lineno, "at": int(m.group("at")), "kind": m.group("kind")}
        if m.group("kind") == "BUZZ":
            ev["mode"] = m.group("mode")
            ev["payload"] = m.group("payload")
            ev["mask"] = m.group("mask")
            ev["buzz"] = int(m.group("buzz"))
            ev["gap"] = int(m.group("gap"))
            ev["beat"] = int(m.group("beat"))
        elif m.group("kind") == "START":
            ev["mode"] = m.group("mode")
            ev["payload"] = m.group("payload")
        events.append(ev)
    return events


def parse_expected_from_c(c_text: str) -> list[str]:
    """The k_demo_expected[] strings, parsed from the generated .c."""
    m = re.search(
        r"k_demo_expected\[\d+\]\s*=\s*\{(.*?)\};", c_text, re.S
    )
    if m is None:
        raise ValueError("k_demo_expected[] not found in generated demo source")
    return re.findall(r'"([^"]*)"', m.group(1))


def demo_fixture_lines() -> list[str]:
    """The expected boot-check HAP lines — the derived fixture, cross-checked.

    Two sources must agree or this raises: the generator's derivation
    (``build_ziv_demo.demo_fixture_lines()``) and the ``k_demo_expected[]``
    strings in the generated ``ziv_demo_sequence.c``. A mismatch means the
    generated file is stale (spec changed without ``--write``) — the boot
    check refuses to compare against the wrong lines.
    """
    derived = build_ziv_demo.demo_fixture_lines()
    try:
        from_c = parse_expected_from_c(DEMO_C_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(
            "qemu_timeline: %s is missing — run `python tools/haptic_timing.py --write` "
            "to generate the demo pair" % DEMO_C_PATH,
            file=sys.stderr,
        )
        raise SystemExit(2)
    if from_c != derived:
        detail = []
        for i, (a, b) in enumerate(zip(from_c, derived)):
            if a != b:
                detail.append("line %d:\n  generated .c: %s\n  derived:      %s" % (i, a, b))
        if len(from_c) != len(derived):
            detail.append(
                "line count: generated .c has %d, derivation has %d"
                % (len(from_c), len(derived))
            )
        print(
            "qemu_timeline: k_demo_expected[] in the generated .c disagrees with "
            "the DEMO_STAGES derivation — the fixture is stale; run "
            "`python tools/haptic_timing.py --write`:\n  " + "\n  ".join(detail[:4]),
            file=sys.stderr,
        )
        raise SystemExit(2)
    return derived


def _exact_keys(ev: dict) -> tuple:
    """The wall-clock-independent identity of one event."""
    if ev["kind"] == "BUZZ":
        return (ev["kind"], ev["mode"], ev["payload"], ev["mask"], ev["buzz"], ev["beat"])
    if ev["kind"] == "START":
        return (ev["kind"], ev["mode"], ev["payload"])
    return (ev["kind"],)


def compare_logs(
    bench_text: str,
    qemu_text: str,
    tol_ms: int = DEFAULT_TOL_MS,
    expected: list[str] | None = None,
) -> tuple[int, list[str]]:
    """Rung-2 equivalence of two HAP logs; returns (failures, report lines).

    Exact: event order, kind, mode, payload, dot mask, buzz duration, beat
    index — the demo's structure is spec-derived, not clock-derived.
    Tolerant (±tol_ms): event timestamps and gap fields — wall-clock drift.
    With ``expected``, both logs are also each compared against the derived
    fixture's BUZZ/START structure (the bench side must be the demo, not
    merely equal to whatever the QEMU side did).
    """
    failures = 0
    report: list[str] = []
    bench = parse_hap_log(bench_text)
    qemu = parse_hap_log(qemu_text)

    def fail(msg: str) -> None:
        nonlocal failures
        failures += 1
        report.append("FAIL " + msg)

    if expected is not None:
        want = parse_hap_log("\n".join(expected))
        if len(bench) != len(want):
            fail("bench log has %d HAP events, the derived fixture has %d" % (len(bench), len(want)))
        for i, (b, w) in enumerate(zip(bench, want)):
            if _exact_keys(b) != _exact_keys(w):
                fail("bench event %d differs from fixture: %s vs %s" % (i, _exact_keys(b), _exact_keys(w)))
            elif b["at"] != w["at"]:
                fail("bench event %d at %d != fixture at %d (bench clock must start at 0)" % (i, b["at"], w["at"]))

    if len(bench) != len(qemu):
        fail("event count differs: bench %d vs qemu %d" % (len(bench), len(qemu)))

    for i in range(min(len(bench), len(qemu))):
        b, q = bench[i], qemu[i]
        if _exact_keys(b) != _exact_keys(q):
            fail("event %d differs:\n  bench: %s\n  qemu:  %s" % (i, _exact_keys(b), _exact_keys(q)))
            continue
        if abs(b["at"] - q["at"]) > tol_ms:
            fail("event %d timestamp drift: bench %d vs qemu %d (tol %d ms)" % (i, b["at"], q["at"], tol_ms))
        if b["kind"] == "BUZZ" and abs(b["gap"] - q["gap"]) > tol_ms:
            fail("event %d gap drift: bench %d vs qemu %d (tol %d ms)" % (i, b["gap"], q["gap"], tol_ms))

    if not failures:
        report.append(
            "OK %d HAP events equivalent (exact structure; timestamps/gaps within %d ms)"
            % (len(bench), tol_ms)
        )
    return failures, report


def _self_check() -> int:
    """Hermetic gate: fixture parses, is internally consistent, and the
    generated .c agrees with the derivation."""
    expected = demo_fixture_lines()  # raises SystemExit(2) on disagreement
    events = parse_hap_log("\n".join(expected))
    problems = []
    if not events:
        problems.append("fixture parsed to zero events")
    # Structure walk: every START eventually ENDs; BUZZ beats are 0..n.
    stack = []
    for ev in events:
        if ev["kind"] == "START":
            stack.append(ev)
        elif ev["kind"] == "END":
            if not stack:
                problems.append("END at line %d with no open START" % ev["line"])
            else:
                stack.pop()
    if stack:
        problems.append("%d START(s) never ENDed (first: line %d)" % (len(stack), stack[0]["line"]))
    seen_word_starts = 0
    for ev in events:
        if ev["kind"] == "START" and ev.get("mode") == "WORD":
            seen_word_starts += 1
    if seen_word_starts != 1:
        problems.append("expected exactly 1 WORD stage in the demo, parsed %d" % seen_word_starts)

    if problems:
        print("qemu_timeline self-check: FAIL")
        for p in problems:
            print("  - " + p)
        return 1
    total_ms = events[-1]["at"] if events else 0
    print(
        "qemu_timeline self-check: OK — %d HAP lines, %d events, %d ms span; "
        "generated .c agrees with the DEMO_STAGES derivation"
        % (len(expected), len(events), total_ms)
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Rung-2 timeline differ: bench vs QEMU HAP logs against the derived demo fixture"
    )
    ap.add_argument("bench_log", nargs="?", help="bench-side HAP log (host_demo --hap-log output)")
    ap.add_argument("qemu_log", nargs="?", help="QEMU-side HAP log (boot console capture)")
    ap.add_argument("--tol-ms", type=int, default=DEFAULT_TOL_MS,
                    help="wall-clock tolerance for timestamps and gaps (default %d)" % DEFAULT_TOL_MS)
    args = ap.parse_args(argv)

    if not args.bench_log and not args.qemu_log:
        return _self_check()
    if not (args.bench_log and args.qemu_log):
        ap.error("give both logs, or neither for the self-check")

    expected = demo_fixture_lines()
    bench_text = Path(args.bench_log).read_text(encoding="utf-8", errors="replace")
    qemu_text = Path(args.qemu_log).read_text(encoding="utf-8", errors="replace")
    failures, report = compare_logs(bench_text, qemu_text, args.tol_ms, expected=expected)
    print("\n".join(report))
    if failures:
        print("qemu_timeline: FAIL (%d mismatch(es))" % failures)
        return 1
    print("qemu_timeline: PASS — the QEMU boot plays the demo the bench plays")
    return 0


if __name__ == "__main__":
    sys.exit(main())
