"""prove.py — one command, one paste-able block of proof.

The submission makes four kinds of claims and used to make each one with a
different command, typed by hand into six different files (which is how
"126 passed" and "133 passing" and "127" all ended up in one repo at
once). This runs all four checks, prints one block with the real counts,
and exits non-zero if anything fails.

    python tools/prove.py            # hermetic + firmware + drift guard
    python tools/prove.py --e2e      # also the browser tier (needs Playwright)
    python tools/prove.py --json     # machine-readable, for CI

Checks, in order:

1. the hermetic relay suite   — agent, pytest -m "not e2e"
2. the haptic bench           — firmware/haptic_out/run_tests.py
3. the QEMU host suite        — firmware/app/ziv_qemu/run_ziv_tests.py
4. the drift guard            — tools/haptic_timing.py --verify

The counts printed here are the ones to paste. Nothing else should be
hand-maintained.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _interpreter() -> str:
    """Prefer the repo's own venv.

    The firmware suites compile C through ``ziglang``, which lives in
    agent/venv. Running them with an ambient interpreter that lacks it fails
    with a compiler error, not a code error — so a green run here means the
    green run a judge gets.
    """
    for rel in ("venv/Scripts/python.exe", "venv/bin/python"):
        candidate = ROOT / "agent" / rel
        if candidate.is_file():
            return str(candidate)
    return sys.executable


PY = _interpreter()

CHECKS = [
    ("hermetic relay suite", [PY, "-m", "pytest", "-q", "-m", "not e2e"], "agent"),
    ("haptic bench", [PY, "firmware/haptic_out/run_tests.py"], "."),
    ("QEMU host suite", [PY, "firmware/app/ziv_qemu/run_ziv_tests.py"], "."),
    ("drift guard", [PY, "tools/haptic_timing.py", "--verify"], "."),
]

E2E = ("browser e2e (real chromium)", [PY, "-m", "pytest", "-q", "-m", "e2e"], "agent")

_COUNT_PATTERNS = [
    # pytest: "131 passed"
    re.compile(r"(\d+) passed"),
    # firmware suites: "274 checks, 0 failures" / "49 checks, 0 failures"
    re.compile(r"(\d+)\s+checks?,\s*\d+\s+failures?", re.I),
    re.compile(r"all\s+(\d+)\s+checks\s+passed", re.I),
]


def _counts(output: str) -> dict[str, int]:
    """Pull the headline number out of a suite's own output."""
    for pattern in _COUNT_PATTERNS:
        found = pattern.search(output)
        if found:
            return {"checks": int(found.group(1))}
    return {}


def _run(name: str, cmd: list[str], cwd: str) -> dict:
    started = time.perf_counter()
    proc = subprocess.run(
        cmd, cwd=ROOT / cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=900,
    )
    elapsed = time.perf_counter() - started
    output = (proc.stdout or "") + (proc.stderr or "")
    return {
        "name": name,
        "command": " ".join(cmd[1:]),
        "ok": proc.returncode == 0,
        "seconds": round(elapsed, 1),
        **_counts(output),
        "tail": output.strip().splitlines()[-1] if output.strip() else "",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--e2e", action="store_true",
        help="also run the browser tier (needs Playwright + chromium)",
    )
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    args = ap.parse_args()

    checks = list(CHECKS) + ([E2E] if args.e2e else [])
    results = [_run(name, cmd, cwd) for name, cmd, cwd in checks]
    failed = [r for r in results if not r["ok"]]

    if args.json:
        print(json.dumps({"results": results, "ok": not failed}, indent=2))
        return 1 if failed else 0

    print()
    print("  Ziv — proof")
    print(f"  interpreter: {PY}")
    print("  " + "-" * 62)
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        count = r.get("checks")
        count_s = f"{count:>4} checks" if count is not None else "       "
        print(f"  {mark}  {r['name']:<30} {count_s}   {r['seconds']:>5.1f}s")
        if not r["ok"]:
            print(f"        -> {r['tail']}")
    print("  " + "-" * 62)
    total = sum(r.get("checks", 0) for r in results if r["ok"])
    print(f"  {total} checks green across {len(results)} suites" if not failed
          else f"  {len(failed)} suite(s) FAILED — do not paste any of these numbers")
    print()
    print("  Paste the PASS lines above. Do not hand-type them anywhere.")
    print()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())