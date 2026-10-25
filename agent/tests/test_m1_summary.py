"""Tests for tools/m1_summary.py — the M1 recognition-gate analyzer.

Builds synthetic session CSVs in the feel-tool's exact format (the analyzer's
REQUIRED_COLS is used as the header, so a header drift fails both sides) and
asserts the protocol §3a gates: per-session accuracy, the tier 1 pass/fail
rules (session fraction, 3/4 floor, M3 confusions, RT), the tier 2 pooled
rules, the gap envelope, and unusable-file handling.
"""
import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("m1_summary", ROOT / "tools" / "m1_summary.py")
m1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m1)

HEADER = m1.REQUIRED_COLS   # the analyzer's own contract IS the header

PARTICIPANT = "P1"
SESSION_ID = "m1-20260909-120000"


def write_session(dir_path: Path, name: str, marks_correct: int = 4,
                  distractors_correct: int = 4, mark_rts: int | None = 2000,
                  distractor_rts: int | None = 4000, replays: int = 0,
                  late: int = 0, participant: str = PARTICIPANT,
                  session_id: str = SESSION_ID, gaps: int | None = None,
                  distractor_kind: str = "distractor",
                  attention_false_alarm: bool = False) -> Path:
    """Write one 8-round session: 4 mark rounds + 4 distractor rounds."""
    if gaps is None:
        gaps = 420
    rows = []
    for i in range(4):   # mark rounds 1-4
        hit = i < marks_correct
        rows.append([i + 1, "ziv", "mark", "name", "name" if hit else "not-name",
                     1 if hit else 0, mark_rts, replays, 1 if i < late else 0, gaps])
    for i in range(4):   # distractor rounds 5-8
        answer_ok = i < distractors_correct
        kind = "attention" if (i == 3 and attention_false_alarm) else distractor_kind
        sid = "double-tap" if kind == "attention" else "boaz"
        # attention false alarm: the pattern is answered 'name'
        answer = ("name" if (attention_false_alarm and i == 3)
                  else ("not-name" if answer_ok else "name"))
        correct = 1 if answer == "not-name" else 0
        rt = distractor_rts
        rows.append([5 + i, sid, kind, "not-name", answer,
                     correct, rt, replays, 1 if 4 + i < late else 0, gaps])
    path = dir_path / name
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        for r in rows:
            w.writerow([participant, session_id, "2026-09-09T12:00:00Z"] + r)
    return path


@pytest.fixture
def sessdir(tmp_path: Path) -> Path:
    return tmp_path


def test_per_session_metrics(sessdir: Path):
    write_session(sessdir, "a.csv", distractors_correct=3, replays=2, late=1)
    rep = m1.summarize([m1.parse_session(sessdir / "a.csv")[0]])
    m = rep["sessions"][0]
    assert m["mark_correct"] == 4
    assert m["mark_acc"] == 1.0
    assert m["accuracy"] == 7 / 8
    assert m["late_count"] == 1
    # replays is a per-round column and the fixture writes it on all 8 rows:
    assert m["replays"] == 16
    assert m["median_rt_ms"] == 2000
    assert m["m3_confusions"] == []   # an arc miss is not an M3 confusion


def test_parse_rejects_bad_gap(sessdir: Path):
    write_session(sessdir, "a.csv", gaps=500)   # outside 420±5
    sess, reason = m1.parse_session(sessdir / "a.csv")
    assert sess is None
    assert "420" in reason


def test_parse_rejects_wrong_round_count(sessdir: Path):
    p = write_session(sessdir, "a.csv")
    lines = p.read_text().splitlines()
    p.write_text("\n".join(lines[:5]) + "\n")   # keep header + 4 rows
    sess, reason = m1.parse_session(p)
    assert sess is None
    assert "8 rounds" in reason


def test_parse_rejects_missing_column(sessdir: Path):
    p = write_session(sessdir, "a.csv")
    lines = p.read_text().splitlines()
    p.write_text(lines[0].replace(",late", "") + "\n" + "\n".join(lines[1:]) + "\n")
    sess, reason = m1.parse_session(p)
    assert sess is None
    assert "late" in reason


def test_tier1_not_reached_below_five_sessions(sessdir: Path):
    for i in range(4):
        write_session(sessdir, f"s{i}.csv", session_id=f"m1-{i}")
    rep = m1.summarize([m1.parse_session(p)[0] for p in sorted(sessdir.glob("*.csv"))])
    assert "tier1" not in rep
    assert rep["n_usable"] == 4


def test_tier1_pass_all_strong(sessdir: Path):
    for i in range(5):
        write_session(sessdir, f"s{i}.csv", session_id=f"m1-{i}")
    rep = m1.summarize([m1.parse_session(p)[0] for p in sorted(sessdir.glob("*.csv"))])
    t1 = rep["tier1"]
    assert t1["pass"] is True
    assert all(ok for ok, _ in t1["checks"].values())


def test_tier1_fails_when_two_sessions_below_gate(sessdir: Path):
    for i in range(3):
        write_session(sessdir, f"ok{i}.csv", session_id=f"m1-ok{i}")
    write_session(sessdir, "weak1.csv", marks_correct=3, session_id="m1-w1")
    write_session(sessdir, "weak2.csv", marks_correct=3, session_id="m1-w2")
    rep = m1.summarize([m1.parse_session(p)[0] for p in sorted(sessdir.glob("*.csv"))])
    t1 = rep["tier1"]
    assert t1["pass"] is False
    frac = t1["checks"]["sessions at >= 80% mark accuracy"]
    assert frac[0] is False
    assert "3/5" in frac[1]


def test_tier1_fails_on_session_below_floor(sessdir: Path):
    for i in range(4):
        write_session(sessdir, f"ok{i}.csv", session_id=f"m1-ok{i}")
    write_session(sessdir, "bad.csv", marks_correct=2, session_id="m1-bad")
    rep = m1.summarize([m1.parse_session(p)[0] for p in sorted(sessdir.glob("*.csv"))])
    t1 = rep["tier1"]
    assert t1["pass"] is False
    floor = t1["checks"]["session floor (no session below 3/4 mark rounds)"]
    assert floor[0] is False
    assert "m1-bad" in floor[1]


def test_tier1_fails_on_m3_confusion(sessdir: Path):
    for i in range(4):
        write_session(sessdir, f"ok{i}.csv", session_id=f"m1-ok{i}")
    # one mark round answered not-name: 3/4 marks is >= floor, so only M3 fails
    write_session(sessdir, "conf.csv", marks_correct=3, session_id="m1-conf")
    rep = m1.summarize([m1.parse_session(p)[0] for p in sorted(sessdir.glob("*.csv"))])
    t1 = rep["tier1"]
    assert t1["pass"] is False
    m3 = t1["checks"]["M3 confusions (mark-vs-content)"]
    assert m3[0] is False
    assert "ziv" in m3[1]


def test_tier1_fails_on_attention_false_alarm(sessdir: Path):
    for i in range(4):
        write_session(sessdir, f"ok{i}.csv", session_id=f"m1-ok{i}")
    write_session(sessdir, "fa.csv", session_id="m1-fa", attention_false_alarm=True)
    rep = m1.summarize([m1.parse_session(p)[0] for p in sorted(sessdir.glob("*.csv"))])
    t1 = rep["tier1"]
    assert t1["pass"] is False
    m3 = t1["checks"]["M3 confusions (mark-vs-content)"]
    assert m3[0] is False
    assert "double-tap" in m3[1]


def test_tier1_fails_on_slow_rt(sessdir: Path):
    for i in range(5):
        write_session(sessdir, f"s{i}.csv", mark_rts=9000, session_id=f"m1-{i}")
    rep = m1.summarize([m1.parse_session(p)[0] for p in sorted(sessdir.glob("*.csv"))])
    t1 = rep["tier1"]
    assert t1["pass"] is False
    rt = t1["checks"]["pooled median RT (correct rounds) <= 5 s"]
    assert rt[0] is False


def test_tier2_gate_and_insufficient_data(sessdir: Path):
    # 20 sessions / 4 participants, all marks correct (zero M3 confusions)
    for p in range(4):
        for s in range(5):
            write_session(sessdir, f"p{p}s{s}.csv",
                          participant=f"P{p}", session_id=f"m1-p{p}s{s}")
    files = sorted(sessdir.glob("*.csv"))
    rep = m1.summarize([m1.parse_session(p)[0] for p in files])
    assert "tier2" in rep
    t2 = rep["tier2"]
    assert t2["enough_data"] is True
    assert t2["pass"] is True

    # drop one participant's five sessions -> 15 sessions / 3 participants
    for p in sorted(sessdir.glob("p3*.csv")):
        p.unlink()
    rep3 = m1.summarize([m1.parse_session(p)[0] for p in sorted(sessdir.glob("*.csv"))])
    assert "tier2" not in rep3
    assert rep3["n_usable"] == 15
    assert rep3["n_participants"] == 3


def test_main_exit_codes(sessdir: Path, capsys):
    # gate failing -> exit 1
    for i in range(5):
        write_session(sessdir, f"ok{i}.csv", session_id=f"m1-ok{i}")
    write_session(sessdir, "bad.csv", marks_correct=2, session_id="m1-bad")
    assert m1.main([str(sessdir)]) == 1
    # not enough data -> exit 0 (collecting)
    tmp2 = sessdir / "few"
    tmp2.mkdir()
    write_session(tmp2, "a.csv")
    assert m1.main([str(tmp2)]) == 0
    # no files at all -> exit 2
    empty = sessdir / "empty"
    empty.mkdir()
    assert m1.main([str(empty)]) == 2


def test_json_output_is_serializable(sessdir: Path, capsys):
    for i in range(5):
        write_session(sessdir, f"s{i}.csv", session_id=f"m1-{i}")
    m1.main([str(sessdir), "--json"])
    out = capsys.readouterr().out
    rep = json.loads(out)
    assert rep["tier1"]["pass"] is True
    assert len(rep["sessions"]) == 5


def test_feel_tool_header_matches_analyzer_contract():
    """The feel-tool's sessionCSV() header must carry every column the
    analyzer requires — a drift on either side fails the suite here."""
    html = (ROOT / "docs" / "haptic-name-marks.html").read_text(encoding="utf-8")
    marker = "var head = '"
    i = html.index(marker) + len(marker)
    j = html.index("';", i)
    page_header = html[i:j].split(",")
    for col in m1.REQUIRED_COLS:
        assert col in page_header, f"feel-tool CSV lacks analyzer column {col!r}"
