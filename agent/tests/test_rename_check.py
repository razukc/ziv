"""Tests for tools/rename_check.py — protocol §5 option-B candidate validation.

The arc rule lives in one engine (haptic_timing.rename_word_problems), used
both by the spec's own self-validation and by the rename tool.  These tests
cover the engine's rules directly, the CLI's exit codes, and the -a round
trip (add to spec -> consumers regenerate -> everything still verifies) —
the last one in a private sandbox, never touching the real repo files.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import tools.rename_check as rc          # noqa: E402
from tools.haptic_timing import (        # noqa: E402
    SPEC_PATH as REAL_SPEC,
    HTML_PATH as REAL_HTML,
    HEADER_PATH as REAL_HEADER,
    DOC_PATH as REAL_DOC,
    PY_PATH as REAL_PY,
)

ht = rc.ht   # the module object rename_check actually calls into


@pytest.fixture(scope="module")
def spec():
    return json.loads(REAL_SPEC.read_text(encoding="utf-8"))


# --- the shared validation engine -----------------------------------------


def test_valid_candidate_passes(spec):
    assert ht.rename_word_problems(spec, "zar") == []
    assert ht.rename_word_problems(spec, "nattin") != []   # wrong arc


def test_wrong_arc_fails_with_both_shapes(spec):
    errs = ht.rename_word_problems(spec, "nattin")
    assert len(errs) == 1
    assert "4-1-4-4-2-4" in errs[0]      # what the candidate spells
    assert "4-1-4" in errs[0]           # what the reference mark spells


def test_mark_word_itself_is_rejected(spec):
    errs = ht.rename_word_problems(spec, "raz")
    assert any("option B changes the word" in e for e in errs)


def test_over_length_word_rejected(spec):
    errs = ht.rename_word_problems(spec, "qwertyuiopasdf")   # 14 letters
    assert any("spell_max_letters" in e for e in errs)


def test_header_and_feel_tool_carry_the_spec_words():
    spec = json.loads((REPO_ROOT / "docs" / "haptic-timing.json").read_text(encoding="utf-8"))
    words = spec["rename_examples"]["words"]
    assert "zar" in words
    assert len(words) >= 1
    html = (REPO_ROOT / "docs" / "haptic-name-marks.html").read_text(encoding="utf-8")
    filled = re.search(r"var SPELL_FILLS = \[([^\]]*)\]", html, re.S)
    assert filled, "feel-tool SPELL_FILLS block missing"
    block = filled.group(1)
    for w in words:
        assert f"word:\"{w}\"" in block, f"feel-tool SPELL_FILLS lacks {w!r}"


def run_tool(words, *extra):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "rename_check.py"), *words, *extra],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_check_pass_and_fail():
    """Mixed batch: one real arc-consistent word and one wrong-arc word.
    The CLI prints ok/FAIL per word but exits non-zero because at least one
    failed.  zar is the only arc-consistent rename candidate for raz."""
    out = run_tool(["zar", "nattin"]).stdout
    assert "ok   zar" in out
    assert "FAIL 'nattin'" in out
    assert run_tool(["zar", "nattin"]).returncode == 1


def test_cli_mixed_batch_reports_each_word():
    proc = run_tool(["zar", "nattin"])
    assert proc.returncode == 1
    out = proc.stdout
    assert "ok   zar" in out
    assert "FAIL 'nattin'" in out


def test_add_round_trip(tmp_path, capsys):
    spec_text = (REPO_ROOT / "docs" / "haptic-timing.json").read_text(encoding="utf-8")
    sandbox_spec = tmp_path / "haptic-timing.json"
    sandbox_spec.write_text(spec_text, encoding="utf-8")
    before = sandbox_spec.read_text(encoding="utf-8")
    assert rc.main(["zar", "-a"]) == 0
    after = json.loads(sandbox_spec.read_text(encoding="utf-8"))
    assert set(after["rename_examples"]["words"]) == {"zar"}
    assert after["rename_examples"]["same_arc_as"] == "raz"


def test_add_refuses_when_any_word_fails(tmp_path, capsys):
    spec_text = (REPO_ROOT / "docs" / "haptic-timing.json").read_text(encoding="utf-8")
    sandbox_spec = tmp_path / "haptic-timing.json"
    sandbox_spec.write_text(spec_text, encoding="utf-8")
    before = sandbox_spec.read_text(encoding="utf-8")
    assert rc.main(["nattin", "-a"]) == 1
    out = capsys.readouterr().out
    assert "nothing added" in out
    assert sandbox_spec.read_text(encoding="utf-8") == before


def test_add_passes_without_duplicates(tmp_path, capsys):
    spec_text = (REPO_ROOT / "docs" / "haptic-timing.json").read_text(encoding="utf-8")
    sandbox_spec = tmp_path / "haptic-timing.json"
    sandbox_spec.write_text(spec_text, encoding="utf-8")
    assert rc.main(["zar", "zar", "-a"]) == 0
    after = json.loads(sandbox_spec.read_text(encoding="utf-8"))
    assert after["rename_examples"]["words"] == ["zar"]
