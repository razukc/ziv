"""Hermetic contract tests for the dev-band client's loud redial give-up.

``agent/ziv_client/index.html`` is a single-file PWA — its redial logic
ships inline and only runs in a browser (the full behavior is proven by the
Playwright e2e suite, ``test_redial_giveup_e2e.py``). What a hermetic test
CAN hold, everywhere the suite runs, is the contract: the give-up path must
exist and must be LOUD — a visible dead-end note that names the message and
the spent budget, a wire log line, a guard so a dead redial never fires, and
clearing on the wearer's actions (disarm, armed re-arm, successful send).

These tests read the client's own source, so a regression that makes the
give-up quiet (or fires a dead redial) fails the suite even on machines
without a browser.
"""

import re
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[1] / "ziv_client" / "index.html"


def _source() -> str:
    return CLIENT.read_text(encoding="utf-8")


def test_client_file_exists_with_redial_machinery():
    src = _source()
    assert "function armRedial" in src
    assert "function fireRedialIfFree" in src
    assert 'id="redialNote"' in src


def test_giveup_shows_a_visible_dead_end_note():
    """The give-up branch must SHOW a note naming the dead end — never just
    log and vanish. Loud-not-silent applies to a spent budget too."""
    src = _source()
    m = re.search(r"if \(RD\.attempts >= RD\.max\) \{(.*?)\n  \}", src, re.S)
    assert m, "the give-up branch in armRedial() is missing"
    branch = m.group(1)
    assert "RD.dead = true" in branch
    assert "RD.el.hidden = false" in branch
    assert "gave up after" in branch
    assert "Send manually when ready" in branch
    # The wire log carries the give-up line too.
    assert "redial gave up after" in branch


def test_dead_redial_never_fires_and_note_is_not_stuck():
    """fireRedialIfFree must refuse to fire a dead redial, and the note's
    lifecycle must clear the dead flag in every exit path — a stuck dead-end
    note is its own kind of silence (it would read as still-armed)."""
    src = _source()
    # The guard: a dead redial never fires.
    guard = re.search(
        r"async function fireRedialIfFree\(\) \{\n(.*?)\n\}", src, re.S
    )
    assert guard, "fireRedialIfFree() is missing"
    assert re.search(r"if \(!RD\.body \|\| RD\.dead\) return;", guard.group(1)), (
        "fireRedialIfFree must bail when the redial is dead"
    )
    # disarmRedial treats a dead note as an armed state (clears the flag).
    disarm = re.search(r"function disarmRedial\(why\) \{(.*?)\n\}", src, re.S)
    assert disarm and "RD.dead = false" in disarm.group(1)
    assert "RD.body !== null || RD.dead" in disarm.group(1)
    # armRedial's armed path resets the dead flag (re-arm after give-up is
    # impossible while the label lives, but a different message re-arms).
    armed = re.search(r"RD\.dead = false;\n  RD\.url = url;", src)
    assert armed, "the armed path must clear the dead flag"
    # A successful delivery clears the dead state (POST ok branch).
    ok_branch = re.search(
        r'log\("sys", "POST ok .*?\);(.*?)\} catch \(e\)', src, re.S
    )
    assert ok_branch, "the POST-ok branch is missing"
    assert "RD.dead = false" in ok_branch.group(1)


def test_budget_shape_is_three_and_survives_edit_cancel():
    """The budget stays 3 and the cancel paths (edit, manual send) still
    route through disarmRedial — the dead-end note must be clearable by the
    same gestures that cancel an armed redial."""
    src = _source()
    assert "max: 3," in src
    # Three distinct cancel triggers reach disarmRedial with a reason.
    triggers = re.findall(r'disarmRedial\("([^"]+)"\)', src)
    assert any("edited" in t for t in triggers), triggers
    assert any("sent manually" in t for t in triggers), triggers
