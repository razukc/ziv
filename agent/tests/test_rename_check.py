"""Tests for tools/rename_check.py — protocol §5 option-B candidate validation.

The arc rule lives in one engine (haptic_timing.rename_word_problems), used
both by the spec's own self-validation and by the rename tool.  These tests
cover the engine's rules directly, the CLI's exit codes, and the -a round
trip (add to spec -> consumers regenerate -> everything still verifies) —
the last one in a private sandbox, never touching the real repo files.
"""
import json
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
)

ht = rc.ht   # the module object rename_check actually calls into


@pytest.fixture(scope="module")
def spec():
    return json.loads(REAL_SPEC.read_text(encoding="utf-8"))


# --- the shared validation engine -----------------------------------------

def test_valid_candidate_passes(spec):
    assert ht.rename_word_problems(spec, "tin") == []
    assert ht.rename_word_problems(spec, "wiz") == []


def test_wrong_arc_fails_with_both_shapes(spec):
    errs = ht.rename_word_problems(spec, "nattin")
    assert len(errs) == 1
    assert "4-1-4-4-2-4" in errs[0]      # what the candidate spells
    assert "4-2-4" in errs[0]            # what the mark spells


def test_mark_word_itself_is_rejected(spec):
    errs = ht.rename_word_problems(spec, "ziv")
    assert any("option B changes the word" in e for e in errs)


def test_non_letters_rejected(spec):
    for bad in ("Tin", "x-y", "", "tin1"):
        assert ht.rename_word_problems(spec, bad) != []


def test_over_length_word_rejected(spec):
    errs = ht.rename_word_problems(spec, "qwertyuiopasdf")   # 14 letters
    assert any("spell_max_letters" in e for e in errs)


def test_committed_spec_words_all_validate(spec):
    """The spec's own rename_examples must pass the same engine the CLI uses."""
    problems = []
    ht.validate(spec, problems)
    assert problems == []


# --- the consumers carry the rename set ------------------------------------

def test_header_and_feel_tool_carry_the_spec_words(spec):
    words = spec["rename_examples"]["words"]
    header = REAL_HEADER.read_text(encoding="utf-8")
    assert f"HAPTIC_RENAME_WORD_COUNT {len(words)}" in header
    html = REAL_HTML.read_text(encoding="utf-8")
    fills = html[html.index("var SPELL_FILLS = ["):html.index("];", html.index("var SPELL_FILLS = ["))]
    for w in words:
        assert f"word:\"{w}\"" in fills, f"feel-tool SPELL_FILLS lacks {w!r}"


def test_spell_max_is_generated_not_handwritten(spec):
    html = REAL_HTML.read_text(encoding="utf-8")
    assert f"var SPELL_MAX={spec['ui']['spell_max_letters']};" in html
    assert "var SPELL_MAX = 12" not in html   # the hand-written copy is gone


# --- the CLI ----------------------------------------------------------------

def run_tool(argv):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "rename_check.py"), *argv],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )


def test_cli_check_pass_and_fail():
    assert run_tool(["tin", "wiz"]).returncode == 0
    proc = run_tool(["nattin"])
    assert proc.returncode == 1
    assert "FAIL" in proc.stdout


def test_cli_mixed_batch_reports_each_word():
    proc = run_tool(["tin", "nattin"])
    assert proc.returncode == 1
    assert "ok   tin" in proc.stdout
    assert "FAIL" in proc.stdout


# --- the -a round trip, in a private sandbox --------------------------------

@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Private copies of the spec + consumers; the checker's paths point at them."""
    for attr, src in (("SPEC_PATH", REAL_SPEC), ("HTML_PATH", REAL_HTML),
                      ("HEADER_PATH", REAL_HEADER), ("DOC_PATH", REAL_DOC)):
        dst = tmp_path / src.name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        monkeypatch.setattr(ht, attr, dst)
    return tmp_path


def test_add_round_trip(sandbox, capsys):
    assert rc.main(["win", "-a"]) == 0
    capsys.readouterr()

    spec_now = json.loads((sandbox / "haptic-timing.json").read_text(encoding="utf-8"))
    assert "win" in spec_now["rename_examples"]["words"]

    # the regenerated consumers agree, and verify mode is green
    monkeypatch_argv = ["haptic_timing.py"]
    original = sys.argv
    sys.argv = monkeypatch_argv
    try:
        assert ht.main() == 0
    finally:
        sys.argv = original
    html = (sandbox / "haptic-name-marks.html").read_text(encoding="utf-8")
    assert 'word:"win"' in html
    header = (sandbox / "haptic_timing.h").read_text(encoding="utf-8")
    assert f"HAPTIC_RENAME_WORD_COUNT {len(spec_now['rename_examples']['words'])}" in header

    # adding it again is idempotent
    assert rc.main(["win", "-a"]) == 0
    spec_again = json.loads((sandbox / "haptic-timing.json").read_text(encoding="utf-8"))
    assert spec_again["rename_examples"]["words"].count("win") == 1


def test_add_refuses_when_any_word_fails(sandbox, capsys):
    before = (sandbox / "haptic-timing.json").read_text(encoding="utf-8")
    assert rc.main(["win", "nattin", "-a"]) == 1
    out = capsys.readouterr().out
    assert "nothing added" in out
    assert (sandbox / "haptic-timing.json").read_text(encoding="utf-8") == before
    assert "win" not in before   # sanity: the sandbox spec really is unchanged


def test_add_passes_without_duplicates(sandbox, capsys):
    assert rc.main(["tin", "-a"]) == 0
    out = capsys.readouterr().out
    assert "nothing to add" in out
