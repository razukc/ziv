#!/usr/bin/env python3
"""m1_summary.py — M1 recognition-gate analyzer for the naming-validation protocol.

Reads the feel-tool session CSVs (docs/haptic-name-marks.html, session mode;
contract: docs/NAMING_VALIDATION_PROTOCOL.md §3a) and applies the §3a gates
deterministically.  The analyzer, not the facilitator, computes the gate —
the sheet's mental math is for the room, the CSV is the record.

Usage:
    python tools/m1_summary.py docs/sessions/P3/              # one participant
    python tools/m1_summary.py docs/sessions/                 # everyone
    python tools/m1_summary.py docs/sessions/P3/ --json       # machine-readable

Paths may be directories (searched recursively for *.csv) or single files.
Exit codes: 0 = applicable gates pass (or not enough data yet),
1 = a gate FAILS (the decision-relevant signal),
2 = bad input (no CSVs found, or none usable).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from statistics import median
from typing import Any

# The contract with the feel-tool's sessionCSV() header row.
REQUIRED_COLS = [
    "participant", "session_id", "started_at", "round", "stimulus_id",
    "stimulus_kind", "expected", "answer", "correct", "rt_ms", "replays",
    "late", "gap_ms",
]
VALID_KINDS = {"mark", "distractor", "attention"}
VALID_ANSWERS = {"name", "not-name"}

SESSION_ROUNDS = 8
GATE_ACC = 0.80                 # mark-only accuracy (per session and pooled)
GATE_SESSION_FLOOR = 3          # no session below 3/4 mark rounds (tier 1 floor)
GATE_RT_MS = 5000.0             # pooled median RT over correct rounds
TIER1_MIN_SESSIONS = 5
TIER1_SESSION_FRAC = 0.80       # 4 of 5 sessions at >= 80% mark accuracy
TIER2_MIN_SESSIONS = 20
TIER2_MIN_PARTICIPANTS = 4
TIER2_SESSION_FRAC = 0.70       # >= 70% of sessions >= 80% individually
GAP_NOMINAL_MS = 420            # the collection envelope: protocol timing
GAP_TOL_MS = 5


def find_csvs(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            out.extend(sorted(path.rglob("*.csv")))
        elif path.is_file():
            out.append(path)
        else:
            print(f"warning: {p} not found", file=sys.stderr)
    return out


def parse_session(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Parse one session CSV.  Returns (session, None) or (None, reason)."""
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                return None, "empty file"
            missing = [c for c in REQUIRED_COLS if c not in reader.fieldnames]
            if missing:
                return None, f"missing columns: {', '.join(missing)}"
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return None, f"unreadable: {exc}"

    if len(rows) != SESSION_ROUNDS:
        return None, f"expected {SESSION_ROUNDS} rounds, found {len(rows)}"
    try:
        for r in rows:
            r["round"] = int(r["round"])
            r["correct"] = int(r["correct"])
            r["rt_ms"] = int(r["rt_ms"])
            r["replays"] = int(r["replays"])
            r["late"] = int(r["late"])
            r["gap_ms"] = int(r["gap_ms"])
    except (TypeError, ValueError):
        return None, "non-integer value in a numeric column"
    if [r["round"] for r in rows] != list(range(1, SESSION_ROUNDS + 1)):
        return None, "round numbers are not 1..8"
    for r in rows:
        if r["stimulus_kind"] not in VALID_KINDS:
            return None, f"round {r['round']}: bad stimulus_kind {r['stimulus_kind']!r}"
        if r["answer"] not in VALID_ANSWERS:
            return None, f"round {r['round']}: bad answer {r['answer']!r}"
        if r["correct"] not in (0, 1) or r["late"] not in (0, 1):
            return None, f"round {r['round']}: correct/late must be 0 or 1"
    bad_gap = [r["gap_ms"] for r in rows
               if abs(r["gap_ms"] - GAP_NOMINAL_MS) > GAP_TOL_MS]
    if bad_gap:
        return None, (f"gap_ms {bad_gap[0]} outside the {GAP_NOMINAL_MS}"
                      f"±{GAP_TOL_MS} ms envelope — timing retuned mid-study? "
                      "re-run the session")
    return {"file": str(path), "rows": rows}, None


def session_metrics(sess: dict[str, Any]) -> dict[str, Any]:
    rows = sess["rows"]
    mark = [r for r in rows if r["stimulus_kind"] == "mark"]
    mark_correct = sum(r["correct"] for r in mark)
    correct_rts = [r["rt_ms"] for r in rows if r["correct"] == 1]
    confusions = []
    for r in rows:
        if r["stimulus_kind"] == "mark" and r["answer"] == "not-name":
            confusions.append(f"{sess['rows'][0]['session_id']}: mark "
                              f"({r['stimulus_id']}) round {r['round']} called not-name")
        if r["stimulus_kind"] == "attention" and r["answer"] == "name":
            confusions.append(f"{sess['rows'][0]['session_id']}: {r['stimulus_id']} "
                              f"round {r['round']} called name")
    false_alarms = sorted({r["stimulus_id"] for r in rows
                           if r["stimulus_kind"] == "distractor"
                           and r["answer"] == "name"})
    return {
        "file": sess["file"],
        "participant": rows[0]["participant"],
        "session_id": rows[0]["session_id"],
        "rounds": len(rows),
        "accuracy": sum(r["correct"] for r in rows) / len(rows),
        "mark_n": len(mark),
        "mark_correct": mark_correct,
        "mark_acc": (mark_correct / len(mark)) if mark else 0.0,
        "median_rt_ms": median(correct_rts) if correct_rts else None,
        "correct_rts_ms": correct_rts,
        "late_count": sum(r["late"] for r in rows),
        "replays": sum(r["replays"] for r in rows),
        "m3_confusions": confusions,
        "distractor_false_alarms": false_alarms,
    }


def session_gate(m: dict[str, Any]) -> bool:
    """Per-session pass line: >= 80% on the mark rounds."""
    return m["mark_acc"] >= GATE_ACC


def tier1_gate(ms: list[dict[str, Any]]) -> dict[str, Any]:
    """Protocol §3a tier 1: >= 80% of sessions at the session gate, no session
    below the 3/4 floor, zero M3 confusions, pooled median RT <= 5 s."""
    n = len(ms)
    at_gate = sum(1 for m in ms if session_gate(m))
    below_floor = [m["session_id"] for m in ms
                   if m["mark_correct"] < GATE_SESSION_FLOOR]
    confusions = [c for m in ms for c in m["m3_confusions"]]
    rts = [rt for m in ms for rt in m["correct_rts_ms"]]
    pooled_rt = median(rts) if rts else None
    rt_ok = pooled_rt is not None and pooled_rt <= GATE_RT_MS
    checks = {
        f"sessions at >= {int(GATE_ACC * 100)}% mark accuracy": (
            at_gate / n >= TIER1_SESSION_FRAC,
            f"{at_gate}/{n} (need >= {int(TIER1_SESSION_FRAC * n)} of {n})"),
        f"session floor (no session below {GATE_SESSION_FLOOR}/4 mark rounds)": (
            not below_floor,
            "ok" if not below_floor else "below floor: " + ", ".join(below_floor)),
        "M3 confusions (mark-vs-content)": (
            not confusions,
            "zero" if not confusions else "; ".join(confusions)),
        f"pooled median RT (correct rounds) <= {GATE_RT_MS / 1000:g} s": (
            rt_ok,
            "no correct rounds" if pooled_rt is None
            else f"{pooled_rt / 1000:.1f} s"),
    }
    return {"gate": "tier 1", "pass": all(ok for ok, _ in checks.values()),
            "checks": checks, "n_sessions": n}


def tier2_gate(ms: list[dict[str, Any]]) -> dict[str, Any]:
    """Protocol §3a tier 2: the pooled gate across >= 20 sessions and >= 4
    participants — the evidence tier for the §5 rename conversation."""
    n = len(ms)
    participants = {m["participant"] for m in ms}
    mark_rounds = sum(m["mark_n"] for m in ms)
    mark_correct = sum(m["mark_correct"] for m in ms)
    pooled_acc = (mark_correct / mark_rounds) if mark_rounds else 0.0
    at_gate = sum(1 for m in ms if session_gate(m))
    confusions = [c for m in ms for c in m["m3_confusions"]]
    rts = [rt for m in ms for rt in m["correct_rts_ms"]]
    pooled_rt = median(rts) if rts else None
    rt_ok = pooled_rt is not None and pooled_rt <= GATE_RT_MS
    checks = {
        f"pooled mark accuracy >= {int(GATE_ACC * 100)}%": (
            pooled_acc >= GATE_ACC, f"{pooled_acc * 100:.0f}% over {mark_rounds} mark rounds"),
        f"sessions at >= {int(GATE_ACC * 100)}% individually": (
            at_gate / n >= TIER2_SESSION_FRAC,
            f"{at_gate}/{n} (need >= {TIER2_SESSION_FRAC * 100:g}%)"),
        "M3 confusions (mark-vs-content)": (
            not confusions, "zero" if not confusions else "; ".join(confusions)),
        f"pooled median RT <= {GATE_RT_MS / 1000:g} s": (
            rt_ok, "no correct rounds" if pooled_rt is None
            else f"{pooled_rt / 1000:.1f} s"),
    }
    enough = n >= TIER2_MIN_SESSIONS and len(participants) >= TIER2_MIN_PARTICIPANTS
    return {"gate": "tier 2", "pass": enough and all(ok for ok, _ in checks.values()),
            "enough_data": enough, "n_sessions": n,
            "n_participants": len(participants), "checks": checks}


def summarize(usable: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"n_usable": len(usable),
                           "n_participants": len({s["rows"][0]["participant"] for s in usable}),
                           "sessions": [session_metrics(s) for s in usable]}
    ms = out["sessions"]
    if len(ms) >= TIER1_MIN_SESSIONS:
        out["tier1"] = tier1_gate(ms)
    if len(ms) >= TIER2_MIN_SESSIONS and len({m["participant"] for m in ms}) >= TIER2_MIN_PARTICIPANTS:
        out["tier2"] = tier2_gate(ms)
    return out


def print_report(rep: dict[str, Any], unusable: list[tuple[str, str]]) -> None:
    print(f"M1 summary — {rep['n_usable']} usable session(s), "
          f"{rep['n_participants']} participant(s)")
    for m in rep["sessions"]:
        rt = ("—" if m["median_rt_ms"] is None
              else f"{m['median_rt_ms'] / 1000:.1f} s")
        late = f" late {m['late_count']}" if m["late_count"] else ""
        m3 = "; ".join(m["m3_confusions"]) or "M3 ok"
        fa = (f"  false alarms: {', '.join(m['distractor_false_alarms'])}"
              if m["distractor_false_alarms"] else "")
        print(f"  {m['participant']:<8} {m['session_id']:<24} "
              f"mark {m['mark_correct']}/{m['mark_n']}  "
              f"acc {m['accuracy'] * 100:.0f}%  medRT {rt}{late}"
              f"  replays {m['replays']}  {m3}{fa}")
    for f, why in unusable:
        print(f"  UNUSABLE {f}: {why}")
    for key in ("tier1", "tier2"):
        if key not in rep:
            continue
        t = rep[key]
        print(f"{t['gate']} gate: {'PASS' if t['pass'] else 'FAIL'}")
        for name, (ok, detail) in t["checks"].items():
            print(f"  [{'ok' if ok else 'FAIL'}] {name}: {detail}")
    if "tier2" not in rep:
        need = TIER2_MIN_SESSIONS - rep["n_usable"]
        print(f"tier 2 gate: not yet (need >= {TIER2_MIN_SESSIONS} sessions "
              f"across >= {TIER2_MIN_PARTICIPANTS} participants; "
              f"have {rep['n_usable']}/{TIER2_MIN_SESSIONS}, "
              f"{rep['n_participants']}/{TIER2_MIN_PARTICIPANTS} participants"
              + (f", {need} sessions to go" if need > 0 else "") + ")")
    if "tier1" not in rep:
        print(f"tier 1 gate: not yet (need >= {TIER1_MIN_SESSIONS} usable sessions; "
              f"have {rep['n_usable']})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="session CSVs and/or directories")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    files = find_csvs(args.paths)
    if not files:
        print("no CSV files found", file=sys.stderr)
        return 2
    usable, unusable = [], []
    for f in files:
        sess, reason = parse_session(f)
        if sess is None:
            unusable.append((str(f), reason or "?"))
        else:
            usable.append(sess)
    if not usable:
        for f, why in unusable:
            print(f"UNUSABLE {f}: {why}", file=sys.stderr)
        return 2

    rep = summarize(usable)
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print_report(rep, unusable)

    if "tier2" in rep:
        return 0 if rep["tier2"]["pass"] else 1
    if "tier1" in rep:
        return 0 if rep["tier1"]["pass"] else 1
    return 0   # collecting: not enough data for any gate yet


if __name__ == "__main__":
    sys.exit(main())
