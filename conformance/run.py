#!/usr/bin/env python
"""conformance/run.py — the harness every Ziv renderer is measured against.

The reference renderer (``ziv.haptics.reference``) defines correct playback.
This script holds it to a checked-in golden set and holds every real renderer
to it:

  --write              render each golden utterance on every profile at the
                       spec's default pace and write conformance/expected/
                       <name>.<profile>.jsonl (orphans are removed)
  --check              fail if any expected file is missing, stale or orphaned:
                       the oracle's own drift guard (the suite and CI run it)
  --player "<command>" --profile P
                       run a player for each golden utterance and diff its
                       timeline against the reference with the spec's
                       conformance tolerance; exit 0 only when every utterance
                       conforms (see conformance/README.md for the interface)

Player interface, in one paragraph: the harness runs
``<command> --profile <profile> --pace <pace_ms>`` from the repository root
with the golden utterance's JSON on stdin; the player prints its timeline as
JSON Lines — ``{"t_ms":int,"dot_mask":int,"buzz_ms":int,"label":str}`` per
beat, ``t_ms`` from the first beat's start — and exits 0.

Every number comes from the spec through ``ziv.haptics.tables``: the profiles,
the default pace, the tolerance. Nothing here sleeps; a player may.
"""
from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from ziv.haptics import reference as R
from ziv.haptics import tables as T
from ziv.wire import Utterance

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GOLDEN_DIR = HERE / "golden"
EXPECTED_DIR = HERE / "expected"
PROFILES = tuple(T.PROFILES)
DEFAULT_PACE_MS = T.CELL_GAP_DEFAULT_MS
TOLERANCE_MS = T.CONFORMANCE_TOLERANCE_MS
GOLDEN_NAME = re.compile(r"^[a-z0-9_]+$")
WRITE_HINT = "run: .venv/bin/python conformance/run.py --write"
# Player runs are independent (a conformant player keeps time on a virtual
# clock, never the wall clock), so the harness runs several at once.
DEFAULT_JOBS = max(1, min(8, os.cpu_count() or 1))


# --- the golden set -------------------------------------------------------------


def load_goldens(golden_dir: Path = GOLDEN_DIR) -> list[tuple[str, Utterance, str]]:
    """``(name, utterance, raw_json)`` for every golden file, sorted by name.
    Every file must validate against ``ziv.wire.Utterance``; a golden that does
    not is a ``ValueError`` — the set is part of the contract."""
    out = []
    for path in sorted(golden_dir.glob("*.json")):
        name = path.stem
        if not GOLDEN_NAME.match(name):
            raise ValueError(f"{path.name}: golden names are [a-z0-9_]+ (they name expected files)")
        raw = path.read_text(encoding="utf-8")
        try:
            utt = Utterance.model_validate_json(raw)
        except Exception as exc:  # pydantic.ValidationError, kept generic for the message
            raise ValueError(f"{path.name}: not a valid utterance: {exc}") from None
        out.append((name, utt, raw))
    if not out:
        raise ValueError(f"no golden utterances in {golden_dir}")
    return out


def expected_path(name: str, profile: str, expected_dir: Path = EXPECTED_DIR) -> Path:
    return expected_dir / f"{name}.{profile}.jsonl"


def expected_text(utt: Utterance, profile: str, pace_ms: int = DEFAULT_PACE_MS) -> str:
    return R.to_jsonl(R.timeline(utt, profile, pace_ms))


def write_expected(golden_dir: Path = GOLDEN_DIR, expected_dir: Path = EXPECTED_DIR,
                   pace_ms: int = DEFAULT_PACE_MS) -> list[Path]:
    """Write every expected timeline; remove orphans; return the written paths."""
    expected_dir.mkdir(parents=True, exist_ok=True)
    goldens = load_goldens(golden_dir)
    keep: set[Path] = set()
    written: list[Path] = []
    for name, utt, _ in goldens:
        for profile in PROFILES:
            path = expected_path(name, profile, expected_dir)
            text = expected_text(utt, profile, pace_ms)
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
                written.append(path)
            keep.add(path)
    for stray in sorted(expected_dir.glob("*.jsonl")):
        if stray not in keep:
            stray.unlink()
    return written


def check_expected(golden_dir: Path = GOLDEN_DIR, expected_dir: Path = EXPECTED_DIR,
                   pace_ms: int = DEFAULT_PACE_MS) -> list[str]:
    """Problems (empty = in sync): a missing, stale or orphaned expected file."""
    problems: list[str] = []
    goldens = load_goldens(golden_dir)
    keep: set[Path] = set()
    for name, utt, _ in goldens:
        for profile in PROFILES:
            path = expected_path(name, profile, expected_dir)
            keep.add(path)
            label = f"{expected_dir.name}/{path.name}"
            if not path.exists():
                problems.append(f"{label}: missing ({WRITE_HINT})")
                continue
            text = expected_text(utt, profile, pace_ms)
            on_disk = path.read_text(encoding="utf-8")
            if on_disk == text:
                continue
            try:
                first = R.diff(R.from_jsonl(text), R.from_jsonl(on_disk), tolerance_ms=0)[:1]
                why = first[0] if first else "same beats, different text"
            except ValueError as exc:
                why = f"unreadable: {exc}"
            problems.append(f"{label}: drifts from the reference — {why} ({WRITE_HINT})")
    for stray in sorted(expected_dir.glob("*.jsonl")) if expected_dir.exists() else []:
        if stray not in keep:
            problems.append(f"{expected_dir.name}/{stray.name}: orphan, no golden utterance ({WRITE_HINT})")
    return problems


# --- running a player -------------------------------------------------------


@dataclass
class PlayerResult:
    name: str
    profile: str
    ok: bool
    beats: int = 0
    duration_ms: int = 0
    problems: list[str] = field(default_factory=list)
    stderr: str = ""


def run_player_once(command: str, profile: str, utt: Utterance, raw: str, name: str,
                    pace_ms: int, tolerance_ms: int, timeout_s: float) -> PlayerResult:
    expected = R.timeline(utt, profile, pace_ms)
    result = PlayerResult(name=name, profile=profile, ok=False, beats=len(expected),
                          duration_ms=R.duration_ms(utt, profile, pace_ms))
    argv = shlex.split(command) + ["--profile", profile, "--pace", str(pace_ms)]
    try:
        proc = subprocess.run(argv, input=raw, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=ROOT, timeout=timeout_s)
    except FileNotFoundError as exc:
        result.problems.append(f"player could not start: {exc}")
        return result
    except subprocess.TimeoutExpired:
        result.problems.append(f"player did not finish within {timeout_s:g} s")
        return result
    result.stderr = proc.stderr
    if proc.returncode != 0:
        result.problems.append(f"player exited {proc.returncode}")
        return result
    try:
        actual = R.from_jsonl(proc.stdout)
    except ValueError as exc:
        result.problems.append(f"player output is not a timeline: {exc}")
        return result
    result.problems = R.diff(expected, actual, tolerance_ms=tolerance_ms)
    result.ok = not result.problems
    return result


def run_player(command: str, profile: str, goldens=None, *, pace_ms: int = DEFAULT_PACE_MS,
               tolerance_ms: int = TOLERANCE_MS, timeout_s: float = 30.0,
               only: str | None = None, jobs: int = DEFAULT_JOBS) -> list[PlayerResult]:
    """One ``PlayerResult`` per golden utterance, in golden order. Up to ``jobs``
    player processes run at once; a player that cannot run in parallel (a
    shared device, say) is run with ``jobs=1``."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; the spec knows {list(PROFILES)}")
    goldens = goldens if goldens is not None else load_goldens()
    selected = [(name, utt, raw) for name, utt, raw in goldens if only is None or name == only]
    if not selected:
        return []

    def one(item):
        name, utt, raw = item
        return run_player_once(command, profile, utt, raw, name, pace_ms, tolerance_ms, timeout_s)

    if jobs <= 1 or len(selected) == 1:
        return [one(item) for item in selected]
    with ThreadPoolExecutor(max_workers=min(jobs, len(selected))) as pool:
        return list(pool.map(one, selected))


def format_results(results: list[PlayerResult], max_diffs: int = 5) -> str:
    width = max((len(r.name) for r in results), default=10)
    lines = []
    for r in results:
        if r.ok:
            lines.append(f"PASS  {r.name:<{width}}  {r.beats:>3} beats  {r.duration_ms:>6} ms")
        else:
            n = len(r.problems)
            lines.append(f"FAIL  {r.name:<{width}}  {n} difference{'s' if n != 1 else ''}")
            for problem in r.problems[:max_diffs]:
                lines.append(f"      {problem}")
            if n > max_diffs:
                lines.append(f"      … {n - max_diffs} more")
            if r.stderr.strip():
                tail = r.stderr.strip().splitlines()[-3:]
                for line in tail:
                    lines.append(f"      stderr: {line}")
    return "\n".join(lines)


# --- CLI ------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="conformance/run.py",
        description="Hold the expected timelines to the reference renderer, and a player to both.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate conformance/expected/ from the reference")
    mode.add_argument("--check", action="store_true", help="fail if conformance/expected/ drifts from the reference")
    mode.add_argument("--player", metavar="COMMAND",
                      help="run this player for every golden utterance and diff it against the reference")
    ap.add_argument("--profile", choices=PROFILES, help="renderer profile the player is asked for (with --player)")
    ap.add_argument("--pace", type=int, default=DEFAULT_PACE_MS,
                    help=f"cell gap in ms (default: the spec's {DEFAULT_PACE_MS}; expected files use the default)")
    ap.add_argument("--tolerance", type=int, default=TOLERANCE_MS,
                    help=f"per-beat |Δt| allowed, ms (default: the spec's {TOLERANCE_MS})")
    ap.add_argument("--timeout", type=float, default=30.0, help="seconds a player may take per utterance")
    ap.add_argument("--jobs", type=int, default=DEFAULT_JOBS,
                    help=f"player processes to run at once (default {DEFAULT_JOBS}; 1 for a player that must run alone)")
    ap.add_argument("--only", metavar="NAME", help="run a single golden utterance")
    ap.add_argument("--max-diffs", type=int, default=5, help="differences to print per failing utterance")
    ap.add_argument("--golden-dir", type=Path, default=GOLDEN_DIR, help=argparse.SUPPRESS)
    ap.add_argument("--expected-dir", type=Path, default=EXPECTED_DIR, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    try:
        if args.write:
            written = write_expected(args.golden_dir, args.expected_dir, args.pace)
            goldens = load_goldens(args.golden_dir)
            print(f"conformance: {len(goldens)} golden utterances × {len(PROFILES)} profiles at "
                  f"pace {args.pace} ms — {len(written)} expected file(s) written, "
                  f"{len(goldens) * len(PROFILES) - len(written)} unchanged")
            problems = check_expected(args.golden_dir, args.expected_dir, args.pace)
            for p in problems:
                print("drift:", p)
            return 1 if problems else 0

        if args.check:
            problems = check_expected(args.golden_dir, args.expected_dir, args.pace)
            if problems:
                for p in problems:
                    print("drift:", p)
                return 1
            goldens = load_goldens(args.golden_dir)
            print(f"conformance: expected timelines in sync with the reference "
                  f"({len(goldens)} utterances × {len(PROFILES)} profiles, pace {args.pace} ms)")
            return 0

        if not args.profile:
            ap.error("--player needs --profile")
        goldens = load_goldens(args.golden_dir)
        results = run_player(args.player, args.profile, goldens, pace_ms=args.pace,
                             tolerance_ms=args.tolerance, timeout_s=args.timeout, only=args.only,
                             jobs=args.jobs)
        if not results:
            print(f"conformance: no golden utterance named {args.only!r}")
            return 2
        print(f"conformance: profile {args.profile}, pace {args.pace} ms, tolerance ±{args.tolerance} ms, "
              f"player: {args.player}")
        print(format_results(results, args.max_diffs))
        passed = sum(r.ok for r in results)
        print(f"conformance: {passed}/{len(results)} PASS on {args.profile}")
        return 0 if passed == len(results) else 1
    except ValueError as exc:
        print(f"conformance: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
