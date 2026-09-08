"""Haptic timing spec guard — spec drift can never be committed.

The haptic channel has one clock: docs/haptic-timing.json.  The phone
feel-tool, the firmware header, and the readable spec tables are generated
consumers of it (tools/haptic_timing.py).  This test runs the checker in
verify mode and fails on any drift, so `python -m pytest` — the hermetic
gate in CONTRIBUTING.md — refuses to go green when the spec and its
consumers disagree.  The same check runs in the pre-commit hook
(hooks/pre-commit).

The third test proves the checker itself detects drift, by pointing it at
private temp copies of the spec and consumers — the real repo is never
touched.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "tools" / "haptic_timing.py"
SPEC = REPO_ROOT / "docs" / "haptic-timing.json"
HEADER = REPO_ROOT / "firmware" / "haptic_out" / "haptic_timing.h"


def run_checker(argv=None):
    return subprocess.run(
        [sys.executable, str(CHECKER), *(argv or [])],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_spec_and_consumers_are_in_sync():
    proc = run_checker()
    assert proc.returncode == 0, (
        "haptic timing drift: generated consumers no longer match "
        "docs/haptic-timing.json. Run `python tools/haptic_timing.py --write` "
        "and commit the regenerated files together.\n" + proc.stdout + proc.stderr
    )
    assert "spec ok" in proc.stdout


def test_generated_header_carries_the_spec_version():
    """Independent of the checker: the committed header must exist and carry
    the spec's version, so a deleted or misgenerated header fails even if
    the checker script itself were broken."""
    assert HEADER.is_file(), "firmware/haptic_out/haptic_timing.h is missing"
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    text = HEADER.read_text(encoding="utf-8")
    assert f"HAPTIC_SPEC_VERSION {spec['version']}" in text


def test_checker_detects_drift(tmp_path, monkeypatch, capsys):
    """Point the checker at private copies, regenerate, then break the spec
    without regenerating — verify mode must exit non-zero."""
    sys.path.insert(0, str(REPO_ROOT))
    import tools.haptic_timing as ht

    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    for attr in ("SPEC_PATH", "HTML_PATH", "HEADER_PATH", "DOC_PATH"):
        src = getattr(ht, attr)
        dst = tmp_path / src.name
        if src.is_file():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        monkeypatch.setattr(ht, attr, dst)

    # Regenerate the private consumers from the (pristine) spec.
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py", "--write"])
    assert ht.main() == 0, capsys.readouterr().out

    # Introduce drift the realistic way: a valid spec whose consumers were
    # not regenerated.  Mutate a ramp beat (no buzz_ref annotation, so the
    # spec still self-validates) and keep the consumers stale — verify mode
    # must report the consumer mismatch and exit non-zero.
    spec["attention_patterns"][3]["beats"][0]["buzz_ms"] += 1
    ht.SPEC_PATH.write_text(json.dumps(spec), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["haptic_timing.py"])
    assert ht.main() == 1, "checker accepted drifted consumers"
    assert "drift" in capsys.readouterr().out