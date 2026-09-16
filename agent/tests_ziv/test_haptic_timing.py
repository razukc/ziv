"""Haptic timing spec guard — spec drift can never be committed.

The haptic channel has one clock: docs/haptic-timing.json.  The phone
feel-tool, the firmware header, the readable spec tables, the scripted boot
demo pair, and the QEMU ladder doc's demo-chain block are generated consumers
of it (tools/haptic_timing.py).  This test runs the checker in
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
PY_MODULE = REPO_ROOT / "tools" / "haptic_timing_gen.py"
LADDER_DOC_PATH = REPO_ROOT / "docs" / "QEMU_SIMULATION_LADDER.md"


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


def test_generated_python_module_carries_the_spec_version():
    """The fourth consumer — the generated Python timing module — must exist,
    carry the spec's version, and hold the same pattern ids the C header
    names. One derivation for the relay, tests, and tools; if it is missing
    or stale, that is a commit-stopping failure even if the checker were
    broken."""
    assert PY_MODULE.is_file(), "tools/haptic_timing_gen.py is missing"
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import haptic_timing_gen as gen

    assert gen.SPEC_VERSION == spec["version"]
    assert gen.PATTERN_IDS == tuple(p["id"] for p in spec["attention_patterns"])
    assert "HAPTIC_PAT_PROCESSING" in HEADER.read_text(encoding="utf-8")
    assert "processing" in gen.PATTERN_BEATS


def test_checker_enforces_ui_and_runtime_limit_asymmetry(tmp_path, monkeypatch, capsys):
    """The checker must refuse a spec whose UI spell_max_letters is not below
    the firmware's HAPTIC_OUT_MAX_WORD_LEN, and must also refuse if the
    firmware header drifts down to a unified value.  Both paths go through
    the checker's asymmetry guard on private copies so the real repo is
    unaffected."""
    sys.path.insert(0, str(REPO_ROOT))
    import tools.haptic_timing as ht

    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    for attr in ("SPEC_PATH", "HTML_PATH", "HEADER_PATH", "DOC_PATH", "PY_PATH",
             "DEMO_H_PATH", "DEMO_C_PATH", "LADDER_DOC_PATH"):
        src = getattr(ht, attr)
        dst = tmp_path / src.name
        if src.is_file():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        monkeypatch.setattr(ht, attr, dst)

    # Regenerate the private consumers from the (pristine) spec so the
    # private fixture is internally consistent before we break it.
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py", "--write"])
    assert ht.main() == 0, capsys.readouterr().out

    # Path 1: unified UI limit (spell_max_letters 16, firmware 16).
    spec["ui"]["spell_max_letters"] = 16
    ht.SPEC_PATH.write_text(json.dumps(spec), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py"])
    assert ht.main() == 1, "checker accepted a unified UI limit"
    out = capsys.readouterr().out
    assert "not below" in out.lower() or "do not unify" in out.lower()
    assert "haptic_out_max_word_len" in out.lower()        # Path 2: firmware header drifts down to the UI limit (12/12).

    monkeypatch.setattr(sys, "argv", ["haptic_timing.py"])
    assert ht.main() == 1, "checker accepted firmware drift to the UI limit"
    out = capsys.readouterr().out
    assert "not below" in out.lower() or "do not unify" in out.lower()
    assert "haptic_out_max_word_len" in out.lower()


def test_ladder_doc_demo_chain_block_is_generated(tmp_path, monkeypatch, capsys):
    """The QEMU ladder doc's rung-1/rung-2 demo chain is a generated consumer:
    the doc must carry the markers, a hand edit to the block must fail
    verification, and --write must heal the block byte-identically.  All on
    private copies — the real repo is never touched."""
    sys.path.insert(0, str(REPO_ROOT))
    import tools.haptic_timing as ht

    # The real doc carries the generated markers.
    assert LADDER_DOC_PATH.is_file(), "docs/QEMU_SIMULATION_LADDER.md is missing"
    real = LADDER_DOC_PATH.read_text(encoding="utf-8")
    assert "haptic-demo-chain:begin" in real and "haptic-demo-chain:end" in real

    # Private copies of every consumer path.
    for attr in ("SPEC_PATH", "HTML_PATH", "HEADER_PATH", "DOC_PATH", "PY_PATH",
                 "DEMO_H_PATH", "DEMO_C_PATH", "LADDER_DOC_PATH"):
        src = getattr(ht, attr)
        dst = tmp_path / src.name
        if src.is_file():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        monkeypatch.setattr(ht, attr, dst)

    # Regenerate the private set so it is internally consistent.
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py", "--write"])
    assert ht.main() == 0, capsys.readouterr().out
    healed = ht.LADDER_DOC_PATH.read_text(encoding="utf-8")

    # Idempotence: a second --write is byte-identical.
    assert ht.main() == 0, capsys.readouterr().out
    assert ht.LADDER_DOC_PATH.read_text(encoding="utf-8") == healed

    # A hand edit inside the generated block must fail verification...
    tampered = healed.replace("Total: 7310 ms", "Total: 9999 ms")
    assert tampered != healed, "sanity: the edit must touch the generated block"
    ht.LADDER_DOC_PATH.write_text(tampered, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py"])
    assert ht.main() == 1, "checker accepted a hand-edited ladder demo-chain block"
    out = capsys.readouterr().out
    assert "ladder" in out.lower()

    # ...and --write heals it back, byte-identically.
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py", "--write"])
    assert ht.main() == 0, capsys.readouterr().out
    assert ht.LADDER_DOC_PATH.read_text(encoding="utf-8") == healed

    # A deleted doc fails verification too (the block cannot be spliced).
    ht.LADDER_DOC_PATH.unlink()
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py"])
    assert ht.main() == 1, "checker accepted a missing ladder doc"


def test_ladder_doc_stage_spans_match_the_spec():
    """Independent of the checker: the generated table's rows must name the
    DEMO_STAGES payloads in order, and the doc's total must equal the
    fixture's final HAP timestamp."""
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    import tools.haptic_timing as ht
    import build_ziv_demo as bzd

    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    doc = LADDER_DOC_PATH.read_text(encoding="utf-8")
    block = doc[doc.index("haptic-demo-chain:begin"):doc.index("haptic-demo-chain:end")]

    names = [bzd.stage_name(mode, payload) for mode, payload in bzd.DEMO_STAGES]
    rows = [line for line in block.splitlines() if line.startswith("| ")][1:]
    assert [r.split("|")[1].strip() for r in rows] == names

    haps = bzd._fixture_lines(spec)
    total_ms = int(haps[-1].split()[1])
    assert ("Total: %d ms" % total_ms) in block
    assert ("%d HAP lines" % len(haps)) in block
