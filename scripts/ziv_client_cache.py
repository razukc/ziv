#!/usr/bin/env python3
"""Keep the PWA service-worker cache in step with the client shell.

``agent/ziv_client/ziv_sw.js`` serves the shell cache-first. If
``index.html`` (or any other file in its ``SHELL`` list) changes while
``const CACHE`` stays the same, an already-installed PWA keeps serving the
old page forever: the install event never runs again and nothing refreshes
the cached shell. A deploy that misses the cache bump is therefore a silent
failed deploy for every returning/installed client.

This script records the shell fingerprint and the cache name in
``scripts/ziv_client_shell_cache.json``. ``--check`` (the default) fails the
deploy when the shell changed without a cache bump, or when the manifest does
not match the current worker/cache. ``--bump`` advances ``vN`` to ``vN+1``
and records the current shell fingerprint.

The hash covers exactly the entries the service worker's own ``SHELL`` list
names, in order, plus their bytes. Adding a file to that list therefore
changes the fingerprint too — the check cannot be bypassed by editing the
cache list without a bump.

Usage:
    python scripts/ziv_client_cache.py --check
    python scripts/ziv_client_cache.py --bump
    python scripts/ziv_client_cache.py --check --staged   # the commit gate
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLIENT_DIR = REPO_ROOT / "agent" / "ziv_client"
DEFAULT_MANIFEST = REPO_ROOT / "scripts" / "ziv_client_shell_cache.json"

CACHE_RE = re.compile(r'const CACHE = "(ziv-phone-band-v(\d+))";')
SHELL_RE = re.compile(r"const SHELL = \[(.*?)\];", re.S)

# The worker's shell entry is the URL a browser requests; the file on disk
# keeps its longer source name.
SERVED_FILE_ALIASES = {
    "./manifest.json": "ziv_manifest.json",
}


def _cache_name(sw_text: str) -> tuple[str, int]:
    match = CACHE_RE.search(sw_text)
    if not match:
        raise SystemExit(
            "ziv_sw.js has no `const CACHE = \"ziv-phone-band-vN\";` line"
        )
    return match.group(1), int(match.group(2))


def _shell_files(client_dir: Path, sw_text: str) -> list[tuple[str, Path]]:
    match = SHELL_RE.search(sw_text)
    if not match:
        raise SystemExit("ziv_sw.js has no `const SHELL = [...]` list")
    entries = re.findall(r'"(\./[^"]+)"', match.group(1))
    if not entries:
        raise SystemExit("ziv_sw.js SHELL list is empty")
    result: list[tuple[str, Path]] = []
    for entry in entries:
        name = entry[2:]
        path = client_dir / SERVED_FILE_ALIASES.get(entry, name)
        if not path.is_file():
            raise SystemExit(f"SHELL entry {entry} is missing on disk: {path}")
        result.append((entry, path))
    return result


def _canonical(data: bytes) -> bytes:
    """Line endings are a checkout artifact, not a shell change.

    Git stores text as LF and a Windows checkout smudges it to CRLF, so the
    same commit would otherwise hash differently per machine — and the commit
    gate, which reads the index, would call every Windows worktree stale.
    Both sides are normalised to LF before hashing.
    """
    return data.replace(b"\r\n", b"\n")


def shell_fingerprint(client_dir: Path) -> str:
    """SHA-256 over the worker's own shell list, names and LF-normalised bytes."""
    sw_text = (client_dir / "ziv_sw.js").read_text(encoding="utf-8")
    digest = hashlib.sha256()
    for entry, path in _shell_files(client_dir, sw_text):
        digest.update(entry.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_canonical(path.read_bytes()))
        digest.update(b"\0")
    return digest.hexdigest()


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise SystemExit(
            f"{path} is not inside {repo_root}; --staged reads that repository's index"
        ) from exc


def _git(repo_root: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ("git", *args), cwd=repo_root, capture_output=True
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout


def check_staged(
    client_dir: Path, manifest_path: Path, *, repo_root: Path = REPO_ROOT
) -> int:
    """Check the index — exactly the bytes the commit will contain.

    The working tree is the wrong source for a commit gate: ``--bump`` writes
    ``ziv_sw.js`` and the manifest to disk, so a bump that ran but was never
    staged would pass a worktree check while the commit still shipped the new
    page behind the old cache name. Blob bytes are read raw (``cat-file``), so
    checkout-time EOL and smudge filters cannot make a correct commit look
    stale either.
    """
    client_rel = _repo_relative(client_dir, repo_root)
    manifest_rel = _repo_relative(manifest_path, repo_root)
    staged = [
        name
        for name in _git(repo_root, "ls-files", "-z", "--", client_rel, manifest_rel)
        .decode("utf-8")
        .split("\0")
        if name
    ]
    if manifest_rel not in staged:
        print(
            f"FAIL: {manifest_rel} is not in the index, so this commit carries "
            "no recorded cache baseline.\n"
            "Run: python scripts/ziv_client_cache.py --bump\n"
            f"     git add {manifest_rel}",
            file=sys.stderr,
        )
        return 1
    worker = f"{client_rel}/ziv_sw.js"
    if worker not in staged:
        print(
            f"FAIL: {worker} is not in the index, so this commit carries no "
            "worker to name a cache.\n"
            f"Stage the whole client: git add {client_rel}",
            file=sys.stderr,
        )
        return 1
    with tempfile.TemporaryDirectory(prefix="ziv-staged-") as tmp:
        root = Path(tmp)
        for name in staged:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_git(repo_root, "cat-file", "blob", f":{name}"))
        return check(root / client_rel, root / manifest_rel)


def _read_manifest(path: Path) -> dict[str, str] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot read cache manifest {path}: {exc}") from exc
    cache = data.get("service_worker_cache")
    shell = data.get("client_shell_sha256")
    if not isinstance(cache, str) or not isinstance(shell, str):
        raise SystemExit(
            f"cache manifest {path} must contain service_worker_cache and "
            "client_shell_sha256 strings"
        )
    return {"service_worker_cache": cache, "client_shell_sha256": shell}


def _write_manifest(path: Path, cache: str, shell: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "service_worker_cache": cache,
        "client_shell_sha256": shell,
    }
    path.write_bytes((json.dumps(payload, indent=2) + "\n").encode("utf-8"))


def check(client_dir: Path, manifest_path: Path) -> int:
    sw_text = (client_dir / "ziv_sw.js").read_text(encoding="utf-8")
    cache, _ = _cache_name(sw_text)
    shell = shell_fingerprint(client_dir)
    manifest = _read_manifest(manifest_path)

    if manifest is None:
        print(
            f"FAIL: no cache manifest at {manifest_path}.\n"
            "Run: python scripts/ziv_client_cache.py --bump",
            file=sys.stderr,
        )
        return 1

    if manifest["client_shell_sha256"] != shell:
        if manifest["service_worker_cache"] == cache:
            detail = (
                f"the client shell changed but the worker still caches {cache}"
            )
        else:
            detail = (
                f"the client shell changed and the worker now says {cache}, "
                f"but the manifest still records {manifest['service_worker_cache']}"
            )
        print(
            "FAIL: installed PWAs would keep the old shell — " + detail + ".\n"
            "Run: python scripts/ziv_client_cache.py --bump\n"
            f"  shell now: {shell}\n"
            f"  manifest:  {manifest['client_shell_sha256']}",
            file=sys.stderr,
        )
        return 1

    if manifest["service_worker_cache"] != cache:
        print(
            f"FAIL: ziv_sw.js uses {cache} but {manifest_path} records "
            f"{manifest['service_worker_cache']}.\n"
            "Run: python scripts/ziv_client_cache.py --bump",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {cache} matches shell sha256 {shell}")
    return 0


def bump(client_dir: Path, manifest_path: Path) -> int:
    sw_path = client_dir / "ziv_sw.js"
    sw_text = sw_path.read_text(encoding="utf-8")
    cache, number = _cache_name(sw_text)
    shell = shell_fingerprint(client_dir)
    manifest = _read_manifest(manifest_path)

    if manifest is None:
        # First baseline: record the current cache rather than inventing a
        # bump that no installed client has seen yet.
        target = cache
    elif manifest["service_worker_cache"] != cache:
        # The cache was already bumped by hand; record that bump instead of
        # incrementing a second time.
        target = cache
    else:
        target = f"ziv-phone-band-v{number + 1}"

    if target != cache:
        old_line = f'const CACHE = "{cache}";'.encode("utf-8")
        new_line = f'const CACHE = "{target}";'.encode("utf-8")
        data = sw_path.read_bytes()
        if data.count(old_line) != 1:
            raise SystemExit(f"expected exactly one {old_line!r} in {sw_path}")
        sw_path.write_bytes(data.replace(old_line, new_line, 1))

    _write_manifest(manifest_path, target, shell)
    print(f"bumped/recorded: cache={target} shell={shell}")
    print(f"manifest: {manifest_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the manifest matches the client shell and cache (default)",
    )
    parser.add_argument(
        "--bump",
        action="store_true",
        help="advance the service-worker cache and record the shell fingerprint",
    )
    parser.add_argument(
        "--print-shell",
        action="store_true",
        help="print the files the service worker caches, one per line",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="verify the index (what a commit would contain), not the working tree",
    )
    parser.add_argument(
        "--client-dir",
        type=Path,
        default=DEFAULT_CLIENT_DIR,
        help=f"client directory (default: {DEFAULT_CLIENT_DIR})",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"cache manifest path (default: {DEFAULT_MANIFEST})",
    )
    args = parser.parse_args()
    actions = [args.check, args.bump, args.print_shell]
    if sum(actions) > 1:
        parser.error("--check, --bump and --print-shell are mutually exclusive")
    if args.staged and (args.bump or args.print_shell):
        parser.error("--staged verifies the index; combine it with --check only")
    if args.print_shell:
        sw_text = (args.client_dir / "ziv_sw.js").read_text(encoding="utf-8")
        names = [path.name for _, path in _shell_files(args.client_dir, sw_text)]
        names.append("ziv_sw.js")
        # Binary write avoids Windows' text-mode CRLF translation; callers
        # feed this straight into shell loops and scp paths.
        sys.stdout.buffer.write(("\n".join(names) + "\n").encode("utf-8"))
        return 0
    if args.bump:
        return bump(args.client_dir, args.manifest)
    if args.staged:
        return check_staged(args.client_dir, args.manifest)
    return check(args.client_dir, args.manifest)


if __name__ == "__main__":
    raise SystemExit(main())
