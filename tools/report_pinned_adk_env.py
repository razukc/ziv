#!/usr/bin/env python3
"""
Surface the pinned ADK reference state as a plain-text summary file
so any downstream step can read it without needing the repo to be
healthy enough for git commands.

This is intentionally a separate, offline-safe diagnostic: it reads
the hash record we wrote and inspects the repo's on-disk refs only
through the filesystem, never through git.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(r"C:\tmp\adk-samples-full")
GIT = REPO / ".git"
RECORD = GIT / "sparse-hash-record.txt"

HEAD_FILE = GIT / "HEAD"
REFS_HEADS = GIT / "refs" / "heads"
REFS_REMOTES_ORIGIN = GIT / "refs" / "remotes" / "origin"


def read_ref(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        return None


def _scan_refs() -> dict[str, str]:
    out: dict[str, str] = {}
    if (GIT / "packed-refs").is_file():
        try:
            for line in (GIT / "packed-refs").read_text(errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2 and parts[1].startswith("refs/"):
                    out[parts[1]] = parts[0]
        except Exception:
            pass
    for label, root in (
        ("heads", REFS_HEADS),
        ("remotes/origin", REFS_REMOTES_ORIGIN),
    ):
        if root.is_dir():
            try:
                for p in sorted(root.iterdir()):
                    if p.suffix in {".lock", ".tmp"}:
                        continue
                    sha = read_ref(p)
                    if sha:
                        out[f"refs/{label}/{p.name}"] = sha
            except Exception:
                pass
    return out


def _scan_refs_as_text() -> str:
    rows = []
    for key, sha in sorted(_scan_refs().items()):
        rows.append(f"{key}\t{sha}")
    return "\n".join(rows)


def main() -> int:
    lines: list[str] = []
    lines.append("ADK_REFERENCE_ENVIRONMENT")
    lines.append(f"repo={REPO}")
    lines.append(f"git_dir={GIT}")
    lines.append("")

    rec = ""
    try:
        rec = RECORD.read_text().strip()
    except FileNotFoundError:
        rec = "(no sparse-hash-record.txt)"

    lines.append("sparse_hash_record=" + rec)
    lines.append("")

    head = read_ref(HEAD_FILE)
    lines.append(f"HEAD_file={head or '(missing)'}")
    lines.append("")

    main_sha = read_ref(REFS_HEADS / "main")
    lines.append(f"refs/heads/main_file={main_sha or '(missing)'}")
    lines.append("")

    origin_refs = []
    if REFS_REMOTES_ORIGIN.is_dir():
        for p in sorted(REFS_REMOTES_ORIGIN.iterdir()):
            if p.suffix in {".lock", ".tmp"}:
                continue
            sha = read_ref(p)
            origin_refs.append(f"{p.name}={sha or '(unreadable)'}")
    lines.append("refs/remotes/origin entries=" + ("; ".join(origin_refs) if origin_refs else "(none)"))
    lines.append("")

    # content hash of the on-disk refs/ state
    blob = json.dumps(_scan_refs(), sort_keys=True, indent=None, separators=(",", ":")).encode("utf-8")
    lines.append("refs_on_disk_hash_sha256=" + hashlib.sha256(blob).hexdigest())
    lines.append("refs_on_disk_snapshot=" + _scan_refs_as_text())
    lines.append("")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
