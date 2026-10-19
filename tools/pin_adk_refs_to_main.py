#!/usr/bin/env python3
"""
Pin the ADK reference repo to origin/main and fix its broken HEAD.

The ADK sparse-checkout clone at C:\tmp\adk-samples-full is a git
repository even when its work tree looks empty; the current code runs
git commands inside `cd` there, which worked for the earlier wake-up
diagnostics but the origin/main pin needs explicit git-dir / work-tree
so it never depends on the process cwd.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REMOTE = Path(r"C:\tmp\adk-samples-full")
GIT_DIR = REMOTE / ".git"
WORK_TREE = REMOTE

GIT = ["git", f"--git-dir={GIT_DIR}", f"--work-tree={WORK_TREE}"]

HASH_FILE = REMOTE / ".git" / "sparse-hash-record.txt"


def run(cmd: list[str], label: str = "", check: bool = False):
    print(f"== {label} ==")
    print("CMD:", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, check=check)
    print("RC:", r.returncode)
    if r.stdout:
        print("OUT:", r.stdout[:3000])
    if r.stderr:
        print("ERR:", r.stderr[:2000])
    print()
    return r


def resolve_origin_main() -> str | None:
    # Try rev-parse first — it uses the local refs/remotes/origin/main if present.
    r = run(GIT + ["rev-parse", "origin/main^{commit}"], "rev-parse origin/main")
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()

    # Fall back to ls-remote against the configured remote.
    remote_url = None
    rr = run(GIT + ["remote", "get-url", "origin"], "remote url", check=False)
    if rr.returncode == 0 and rr.stdout.strip():
        remote_url = rr.stdout.strip().splitlines()[0]

    if not remote_url:
        rr = run(
            GIT + ["remote", "-v"],
            "remote -v",
            check=False,
        )
        if rr.returncode == 0:
            for line in rr.stdout.splitlines():
                if line.startswith("origin\t") and " (fetch)" in line:
                    remote_url = line.split()[1]
                    break

    if not remote_url:
        print("WARN: could not read origin url; aborting.")
        return None

    r = run(
        ["git", "ls-remote", "--heads", remote_url, "main"],
        "ls-remote main",
        check=False,
    )
    if r.returncode == 0 and r.stdout.strip():
        sha = r.stdout.strip().split()[0]
        print("ls-remote main ->", sha)
        return sha

    return None


def write_hash_record(ref: str, sha: str) -> None:
    HASH_FILE.write_text(f"ref={ref}\nsha={sha}\n")


def read_hash_record() -> str | None:
    try:
        return HASH_FILE.read_text().strip()
    except FileNotFoundError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--reresolve-origin-main",
        action="store_true",
        help="Re-resolve origin/main before touching HEAD (used after wake-up).",
    )
    ap.add_argument(
        "--then-pin-head",
        action="store_true",
        help="If we have a clean origin/main, also fix the broken HEAD/refs.",
    )
    args = ap.parse_args()

    print("WORKDIR:", REMOTE)
    print("GIT_DIR:", GIT_DIR)
    print("WORK_TREE:", WORK_TREE)
    print()

    sha: str | None = None

    if args.reresolve_origin_main or args.then_pin_head:
        sha = resolve_origin_main()

    if not sha:
        # Use any previously recorded sha only as a last resort.
        rec = read_hash_record()
        if rec and rec.startswith("sha="):
            sha = rec.split("=", 1)[1]
            print("Using recorded sha:", sha)
        else:
            print("ERR: no origin/main ref available.")
            return 2

    print("resolved origin/main ->", sha)
    write_hash_record("refs/remotes/origin/main", sha)

    if args.then_pin_head:
        run(
            GIT + ["update-ref", "--delete", "refs/heads/.invalid"],
            "delete broken ref",
            check=False,
        )
        run(
            GIT + ["symbolic-ref", "HEAD", "refs/heads/main"],
            "point HEAD to main",
            check=False,
        )
        run(
            GIT + ["reset", "--mixed", "origin/main"],
            "reset index",
            check=False,
        )
        run(
            GIT + ["checkout", "-f", "main"],
            "checkout main",
            check=False,
        )

    print("hash record now:", read_hash_record())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
