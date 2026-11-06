"""Haptic timing spec guard — spec drift can never be committed.

The haptic channel has one clock: docs/haptic-timing.json. The phone
feel-tool, the firmware header, the Python tables the relay and the
reference renderer import, the readable spec tables, the scripted boot demo
pair and the QEMU ladder doc's demo-chain block are generated consumers of it
(tools/haptic_timing.py). These tests run the checker in verify mode and fail
on any drift, so the suite refuses to go green when the spec and its
consumers disagree. The same check runs in the pre-commit hook and in CI.

Several tests prove the checker itself detects drift by pointing it at
private temp copies of the spec and consumers; the real repo is never
touched.

tools/ is a directory of scripts, not a package, so these tests import it by
path. That is the one place in the suite where sys.path is touched.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "tools" / "haptic_timing.py"
SPEC = REPO_ROOT / "docs" / "haptic-timing.json"
HEADER = REPO_ROOT / "firmware" / "haptic_out" / "haptic_timing.h"
PY_MODULE = REPO_ROOT / "ziv" / "haptics" / "tables.py"
LADDER_DOC_PATH = REPO_ROOT / "docs" / "QEMU_SIMULATION_LADDER.md"
QEMU_TIMELINE = REPO_ROOT / "tools" / "qemu_timeline.py"

CONSUMER_ATTRS = ("SPEC_PATH", "HTML_PATH", "HEADER_PATH", "DOC_PATH", "PY_PKG_PATH",
                  "DEMO_H_PATH", "DEMO_C_PATH", "LADDER_DOC_PATH")


def _tools():
    for p in (str(REPO_ROOT), str(REPO_ROOT / "tools")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import tools.haptic_timing as ht  # noqa: PLC0415
    import build_ziv_demo as bzd  # noqa: PLC0415
    return ht, bzd


def run_checker(argv=None):
    return subprocess.run(
        [sys.executable, str(CHECKER), *(argv or [])],
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=60,
    )


def _private_copies(ht, tmp_path, monkeypatch):
    for attr in CONSUMER_ATTRS:
        src = getattr(ht, attr)
        dst = tmp_path / src.name
        if src.is_file():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        monkeypatch.setattr(ht, attr, dst)


def test_spec_and_consumers_are_in_sync():
    proc = run_checker()
    assert proc.returncode == 0, (
        "haptic timing drift: run `python tools/haptic_timing.py --write` and "
        "commit the regenerated files together.\n" + proc.stdout + proc.stderr
    )
    assert "spec ok" in proc.stdout


def test_generated_header_carries_the_spec_version():
    assert HEADER.is_file(), "firmware/haptic_out/haptic_timing.h is missing"
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert f"HAPTIC_SPEC_VERSION {spec['version']}" in HEADER.read_text(encoding="utf-8")


def test_generated_python_tables_carry_the_spec():
    """The package's tables are the relay's and the oracle's only source of
    numbers: they must exist, match the spec's version, name the same
    patterns the C header names, and carry the v4 sections."""
    assert PY_MODULE.is_file(), "ziv/haptics/tables.py is missing"
    from ziv.haptics import tables as gen

    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert gen.SPEC_VERSION == spec["version"]
    assert gen.SPEC == spec
    assert gen.PATTERN_IDS == tuple(p["id"] for p in spec["attention_patterns"])
    assert "HAPTIC_PAT_PROCESSING" in HEADER.read_text(encoding="utf-8")
    assert "processing" in gen.PATTERN_BEATS
    assert gen.WORD_GAP_MS == spec["constants"]["word_gap_ms"]
    assert set(gen.KINDS) == set(spec["kinds"])
    assert set(gen.PROFILES) == set(spec["profiles"])


def test_checker_enforces_ui_and_runtime_limit_asymmetry(tmp_path, monkeypatch, capsys):
    ht, _ = _tools()
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    _private_copies(ht, tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py", "--write"])
    assert ht.main() == 0, capsys.readouterr().out

    spec["ui"]["spell_max_letters"] = 16
    ht.SPEC_PATH.write_text(json.dumps(spec), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py"])
    assert ht.main() == 1, "checker accepted a unified UI limit"
    out = capsys.readouterr().out.lower()
    assert "not below" in out or "do not unify" in out
    assert "haptic_out_max_word_len" in out


def test_checker_refuses_a_v4_section_that_is_malformed(tmp_path, monkeypatch, capsys):
    """The v4 sections are validated like everything else: a slot order that
    is not a permutation of 1..6 and a kind whose cue is not a pattern both
    fail verification on private copies."""
    ht, _ = _tools()
    _private_copies(ht, tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py", "--write"])
    assert ht.main() == 0, capsys.readouterr().out

    spec = json.loads(ht.SPEC_PATH.read_text(encoding="utf-8"))
    spec["profiles"]["single_actuator"]["order"] = [1, 2, 3, 4, 5, 5]
    ht.SPEC_PATH.write_text(json.dumps(spec), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py"])
    assert ht.main() == 1, "checker accepted a slot order that is not a permutation"
    capsys.readouterr()

    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    spec["kinds"]["message"]["cue"] = "no-such-pattern"
    ht.SPEC_PATH.write_text(json.dumps(spec), encoding="utf-8")
    assert ht.main() == 1, "checker accepted a kind cue that names no pattern"


def test_ladder_doc_demo_chain_block_is_generated(tmp_path, monkeypatch, capsys):
    ht, _ = _tools()
    assert LADDER_DOC_PATH.is_file()
    real = LADDER_DOC_PATH.read_text(encoding="utf-8")
    assert "haptic-demo-chain:begin" in real and "haptic-demo-chain:end" in real

    _private_copies(ht, tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py", "--write"])
    assert ht.main() == 0, capsys.readouterr().out
    healed = ht.LADDER_DOC_PATH.read_text(encoding="utf-8")
    assert ht.main() == 0, capsys.readouterr().out
    assert ht.LADDER_DOC_PATH.read_text(encoding="utf-8") == healed

    tampered = healed.replace("Total: 7310 ms", "Total: 9999 ms")
    assert tampered != healed
    ht.LADDER_DOC_PATH.write_text(tampered, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py"])
    assert ht.main() == 1, "checker accepted a hand-edited ladder demo-chain block"
    assert "ladder" in capsys.readouterr().out.lower()

    monkeypatch.setattr(sys, "argv", ["haptic_timing.py", "--write"])
    assert ht.main() == 0, capsys.readouterr().out
    assert ht.LADDER_DOC_PATH.read_text(encoding="utf-8") == healed

    ht.LADDER_DOC_PATH.unlink()
    monkeypatch.setattr(sys, "argv", ["haptic_timing.py"])
    assert ht.main() == 1, "checker accepted a missing ladder doc"


def test_ladder_doc_stage_spans_match_the_spec():
    _, bzd = _tools()
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


# --- rung-2 boot check: tools/qemu_timeline.py reads the derived fixture -----


def run_differ(argv):
    return subprocess.run(
        [sys.executable, str(QEMU_TIMELINE), *argv],
        cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=60,
    )


def _shift_at(line, delta_ms):
    return re.sub(r"^HAP (\d+)", lambda m: "HAP %d" % (int(m.group(1)) + delta_ms), line)


def test_qemu_timeline_self_check_is_green():
    r = run_differ([])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "self-check: OK" in r.stdout
    assert "generated .c agrees" in r.stdout


def test_qemu_timeline_boot_check_golden(tmp_path):
    _, bzd = _tools()
    expected = bzd.demo_fixture_lines()
    bench = tmp_path / "bench_hap.log"
    bench.write_text("\n".join(expected) + "\n", encoding="utf-8")
    qemu_lines = ["ESP-ROM:esp32s3-20210310", "I (312) cpu_start: Starting app", ""]
    qemu_lines += [_shift_at(ln, 3) for ln in expected]
    qemu = tmp_path / "qemu.log"
    qemu.write_text("\n".join(qemu_lines) + "\n", encoding="utf-8")
    r = run_differ([str(bench), str(qemu)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "%d HAP events" % len(expected) in r.stdout


def test_qemu_timeline_catches_real_drift(tmp_path):
    _, bzd = _tools()
    expected = bzd.demo_fixture_lines()
    bench = tmp_path / "bench_hap.log"
    bench.write_text("\n".join(expected) + "\n", encoding="utf-8")

    def run(qemu_lines, name):
        q = tmp_path / name
        q.write_text("\n".join(qemu_lines) + "\n", encoding="utf-8")
        return run_differ([str(bench), str(q)])

    word_buzz = next(i for i, ln in enumerate(expected) if " BUZZ WORD " in ln)
    tampered = list(expected)
    tampered[word_buzz] = re.sub(
        r"(BUZZ WORD \S+ )([0-9A-F]{2})",
        lambda m: m.group(1) + ("%02X" % ((int(m.group(2), 16) ^ 0x01) & 0x3F)),
        tampered[word_buzz],
    )
    r = run(tampered, "mask.log")
    assert r.returncode == 1 and "differs" in r.stdout

    drifted = [_shift_at(ln, 500 if i == 10 else 3) for i, ln in enumerate(expected)]
    r = run(drifted, "drift.log")
    assert r.returncode == 1 and "timestamp drift" in r.stdout

    r = run(expected[:-1], "short.log")
    assert r.returncode == 1 and "event count differs" in r.stdout


def test_qemu_timeline_refuses_a_stale_generated_fixture(tmp_path, monkeypatch):
    _tools()
    import tools.qemu_timeline as qt  # noqa: PLC0415

    stale = tmp_path / "ziv_demo_sequence.c"
    stale.write_text('const char *const k_demo_expected[5] = {\n    "HAP 0 END",\n};\n', encoding="utf-8")
    monkeypatch.setattr(qt, "DEMO_C_PATH", stale)
    with pytest.raises(SystemExit) as ei:
        qt.demo_fixture_lines()
    assert ei.value.code == 2
    monkeypatch.setattr(qt, "DEMO_C_PATH", tmp_path / "absent.c")
    with pytest.raises(SystemExit) as ei:
        qt.demo_fixture_lines()
    assert ei.value.code == 2
