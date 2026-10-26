"""Tests for the deploy-time service-worker shell cache guard.

The guard exists to stop a shell change from shipping behind an unchanged
``ziv-phone-band-vN`` cache. These tests exercise the three states that matter
without touching the real client directory:

* a changed shell with the old cache is refused;
* ``--bump`` advances the cache, records the new shell, and then checks clean;
* a cache bumped by hand is recorded once, not incremented a second time;
* a missing manifest fails closed instead of trusting an unknown shell;
* the CLI round trip CI and the deploy script run (``--bump`` then
  ``--check``) works on the real files, not just the imported functions;
* the commit gate (``--staged``) judges the index: a stale commit is refused
  even when the working tree has been put back, a staged bump passes, and a
  manifest that was never staged fails closed with the ``git add`` hint.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ziv_client_cache  # noqa: E402

SCRIPT = SCRIPTS / "ziv_client_cache.py"


def _cli(client: Path, manifest: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the checker the way CI and the deploy script do.

    The checker prints an em-dash in its stale-shell failure, which cp1252
    encodes as 0x97. With a UTF-8-mode parent — `python -X utf8 -m pytest`,
    exactly what CI runs — the decode thread dies on that byte, ``stderr``
    comes back None, and the assertion below raises TypeError instead of
    reporting what the guard said. Pin stdio on both sides so the test reads
    the same on every console code page.
    """
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            *args,
            "--client-dir",
            str(client),
            "--manifest",
            str(manifest),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def _client_and_manifest(tmp_path: Path) -> tuple[Path, Path]:
    client = tmp_path / "client"
    shutil.copytree(ziv_client_cache.DEFAULT_CLIENT_DIR, client)
    manifest = tmp_path / "client-shell-cache.json"
    shutil.copy2(ziv_client_cache.DEFAULT_MANIFEST, manifest)
    return client, manifest


def _change_shell(client: Path) -> None:
    # Bytes, not text mode: Windows would translate the \n to \r\n and the
    # guard would then see a line-ending change as a shell change.
    with (client / "index.html").open("ab") as fh:
        fh.write(b"\n<!-- shell changed by the cache-guard test -->\n")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True
    )


def _scratch_repo(tmp_path: Path, *, track_manifest: bool = True) -> Path:
    """A throwaway repository with a copy of the client (and its baseline).

    ``--staged`` reads a repository's index, so the only honest way to test it
    is a real scratch repository: nothing here can touch this checkout's index.
    """
    repo = tmp_path / "checkout"
    (repo / "agent").mkdir(parents=True)
    shutil.copytree(ziv_client_cache.DEFAULT_CLIENT_DIR, repo / "agent" / "ziv_client")
    manifest = repo / "scripts" / "ziv_client_shell_cache.json"
    manifest.parent.mkdir(parents=True)
    shutil.copy2(ziv_client_cache.DEFAULT_MANIFEST, manifest)
    assert _git(repo, "init", "-q").returncode == 0
    _git(repo, "config", "user.email", "cache-guard@example.invalid")
    _git(repo, "config", "user.name", "cache guard test")
    _git(repo, "config", "commit.gpgsign", "false")
    # Byte-faithful checkout, so a restore puts the worktree back exactly.
    _git(repo, "config", "core.autocrlf", "false")
    if track_manifest:
        assert _git(repo, "add", "-A").returncode == 0
    else:
        assert _git(repo, "add", "agent").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "baseline").returncode == 0
    return repo


def _cache_names(manifest: Path) -> tuple[str, str]:
    """The cache recorded on this tree, and the one a bump should produce.

    Read from the manifest, not hard-coded: this suite itself bumps the cache.
    """
    base = json.loads(manifest.read_text(encoding="utf-8"))["service_worker_cache"]
    return base, f"ziv-phone-band-v{int(base.rsplit('-v', 1)[1]) + 1}"


def _hand_bump_cache(client: Path, base: str, target: str) -> None:
    """Edit the worker's cache line the way a developer would by hand."""
    sw_path = client / "ziv_sw.js"
    sw_path.write_text(
        sw_path.read_text(encoding="utf-8").replace(
            f'const CACHE = "{base}";', f'const CACHE = "{target}";'
        ),
        encoding="utf-8",
    )


def test_changed_shell_without_a_cache_bump_is_refused(tmp_path, capsys):
    client, manifest = _client_and_manifest(tmp_path)
    _change_shell(client)
    base, _ = _cache_names(manifest)

    assert ziv_client_cache.check(client, manifest) == 1
    stderr = capsys.readouterr().err
    assert "installed PWAs would keep the old shell" in stderr
    assert base in stderr
    assert "--bump" in stderr


def test_bump_advances_cache_records_shell_and_round_trips(tmp_path, capsys):
    client, manifest = _client_and_manifest(tmp_path)
    _change_shell(client)
    base, target = _cache_names(manifest)

    assert ziv_client_cache.bump(client, manifest) == 0
    sw_text = (client / "ziv_sw.js").read_text(encoding="utf-8")
    assert f'const CACHE = "{target}";' in sw_text
    assert base not in sw_text

    recorded = json.loads(manifest.read_text(encoding="utf-8"))
    assert recorded["service_worker_cache"] == target
    assert recorded["client_shell_sha256"] == ziv_client_cache.shell_fingerprint(client)
    assert ziv_client_cache.check(client, manifest) == 0
    assert f"OK: {target}" in capsys.readouterr().out


def test_manual_cache_bump_is_recorded_without_double_increment(tmp_path):
    client, manifest = _client_and_manifest(tmp_path)
    _change_shell(client)
    base, target = _cache_names(manifest)

    # A developer already changed the cache line by hand. Recording must keep
    # the hand-picked name; bumping again would needlessly invalidate every
    # installed shell.
    _hand_bump_cache(client, base, target)
    assert ziv_client_cache.bump(client, manifest) == 0

    sw_text = (client / "ziv_sw.js").read_text(encoding="utf-8")
    assert f'const CACHE = "{target}";' in sw_text
    recorded = json.loads(manifest.read_text(encoding="utf-8"))
    assert recorded["service_worker_cache"] == target
    assert ziv_client_cache.check(client, manifest) == 0


def test_missing_manifest_fails_closed(tmp_path, capsys):
    """A fresh checkout with no recorded baseline must not be trusted: the
    guard cannot know which shell an installed PWA is still holding."""
    client, manifest = _client_and_manifest(tmp_path)
    manifest.unlink()

    assert ziv_client_cache.check(client, manifest) == 1
    stderr = capsys.readouterr().err
    assert "no cache manifest" in stderr
    assert "--bump" in stderr


def test_hand_edited_cache_that_was_never_recorded_is_still_refused(tmp_path, capsys):
    """The second stale branch: the worker already says v5 but the manifest
    still records v4. Deploying here would ship an unverified shell."""
    client, manifest = _client_and_manifest(tmp_path)
    _change_shell(client)
    base, target = _cache_names(manifest)
    _hand_bump_cache(client, base, target)

    assert ziv_client_cache.check(client, manifest) == 1
    stderr = capsys.readouterr().err
    assert f"the worker now says {target}" in stderr
    assert f"still records {base}" in stderr


def _repo_paths(repo: Path) -> tuple[Path, Path]:
    return (
        repo / "agent" / "ziv_client",
        repo / "scripts" / "ziv_client_shell_cache.json",
    )


def test_staged_shell_change_is_refused_even_with_a_clean_worktree(tmp_path, capsys):
    """The commit gate's whole reason for reading the index: stage a shell
    change, put the worktree back, and the worktree check passes while the
    commit would still ship the new page behind the old cache name."""
    repo = _scratch_repo(tmp_path)
    client, manifest = _repo_paths(repo)
    _change_shell(client)
    assert _git(repo, "add", "agent/ziv_client/index.html").returncode == 0
    # Worktree only: `git checkout HEAD -- <path>` would also rewrite the index
    # and quietly undo the staged change this test needs to keep.
    assert _git(repo, "restore", "--worktree", "--source=HEAD", "--", "agent/ziv_client/index.html").returncode == 0

    assert ziv_client_cache.check(client, manifest) == 0
    assert ziv_client_cache.check_staged(client, manifest, repo_root=repo) == 1
    assert "installed PWAs would keep the old shell" in capsys.readouterr().err


def test_staged_bump_and_manifest_pass(tmp_path, capsys):
    repo = _scratch_repo(tmp_path)
    client, manifest = _repo_paths(repo)
    _change_shell(client)
    _, target = _cache_names(manifest)

    assert ziv_client_cache.bump(client, manifest) == 0
    assert _git(repo, "add", "-A").returncode == 0

    assert ziv_client_cache.check_staged(client, manifest, repo_root=repo) == 0
    assert f"OK: {target}" in capsys.readouterr().out


def test_manifest_that_was_never_staged_fails_closed(tmp_path, capsys):
    """An untracked record cannot gate a commit: the deployed shell would have
    no baseline anywhere outside one developer's working tree."""
    repo = _scratch_repo(tmp_path, track_manifest=False)
    client, manifest = _repo_paths(repo)
    assert manifest.is_file()

    assert ziv_client_cache.check_staged(client, manifest, repo_root=repo) == 1
    stderr = capsys.readouterr().err
    assert "is not in the index" in stderr
    assert "git add scripts/ziv_client_shell_cache.json" in stderr


def test_fingerprint_ignores_checkout_line_endings(tmp_path):
    """Git stores LF and a Windows checkout smudges CRLF, so the same commit
    must hash the same on both — otherwise the index-based gate would call
    every Windows worktree stale (and CI would disagree with the machine the
    baseline was recorded on)."""
    client, _ = _client_and_manifest(tmp_path)
    canonical = ziv_client_cache.shell_fingerprint(client)
    for path in (client / "index.html", client / "ziv_sw.js"):
        data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        path.write_bytes(data)

    assert ziv_client_cache.shell_fingerprint(client) == canonical


def test_precommit_hook_gates_on_the_staged_tree():
    """The hook's substance is one command; pin it so a later edit cannot
    quietly downgrade the gate to a working-tree check."""
    hook = (REPO_ROOT / "hooks" / "pre-commit").read_text(encoding="utf-8")
    assert "ziv_client_cache.py --check --staged" in hook
    assert "git diff --cached --quiet -- agent/ziv_client" in hook


def test_cli_bump_then_check_round_trips_the_manifest(tmp_path):
    """The exact two commands CI and the deploy script run, on real files."""
    client, manifest = _client_and_manifest(tmp_path)
    _change_shell(client)
    _, target = _cache_names(manifest)

    stale = _cli(client, manifest, "--check")
    assert stale.returncode == 1, stale.stdout + stale.stderr
    assert "installed PWAs would keep the old shell" in stale.stderr

    bumped = _cli(client, manifest, "--bump")
    assert bumped.returncode == 0, bumped.stderr
    assert f"bumped/recorded: cache={target}" in bumped.stdout

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert set(payload) == {"service_worker_cache", "client_shell_sha256"}
    assert payload["service_worker_cache"] == target
    assert payload["client_shell_sha256"] == ziv_client_cache.shell_fingerprint(client)

    # The recorded round trip is what the deploy gate reads back.
    checked = _cli(client, manifest, "--check")
    assert checked.returncode == 0, checked.stderr
    expected = f"OK: {target} matches shell sha256 {payload['client_shell_sha256']}"
    assert expected in checked.stdout


def test_cli_decoding_is_pinned_against_the_console_code_page(tmp_path):
    """Drop the stdio pinning in ``_cli`` and this fails, not only Windows CI.

    CI starts pytest with ``-X utf8``, a flag a child never inherits. If the
    child is left to the locale it writes the checker's em-dash as cp1252
    0x97, the UTF-8 parent's reader thread dies, and ``stderr`` arrives as
    None. Reproduce that split in a child interpreter — UTF-8-mode parent,
    cp1252 child — so the assertion is about the helper's pinning rather than
    about which console happens to run the suite.
    """
    client, manifest = _client_and_manifest(tmp_path)
    _change_shell(client)
    script = (
        "import sys\n"
        "sys.path.insert(0, 'tests')\n"
        "import test_client_cache_guard as guard\n"
        "from pathlib import Path\n"
        "proc = guard._cli(Path(sys.argv[1]), Path(sys.argv[2]), '--check')\n"
        "assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)\n"
        "assert proc.stderr and 'installed PWAs would keep the old shell' in proc.stderr, proc.stderr\n"
    )
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script, str(client), str(manifest)],
        cwd=REPO_ROOT / "agent",
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
