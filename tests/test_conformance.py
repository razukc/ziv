"""The conformance harness: the golden set, the expected timelines, and a
player run — the oracle held to itself, and the harness proven to bite.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ziv.haptics import reference as R
from ziv.haptics import tables as T
from ziv.wire import Kind, Profile, Utterance

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFORMANCE = REPO_ROOT / "conformance"
RUN_PY = CONFORMANCE / "run.py"
REFERENCE_PLAYER = CONFORMANCE / "players" / "reference.py"
BUDGET_MS = 15_000     # the budget the two `budget_*` goldens are the longest fit for
MAX_WORD_LETTERS = 32  # ziv.wire.Word
MAX_WORDS = 64         # ziv.wire.MAX_WORDS


def _load_run():
    spec = importlib.util.spec_from_file_location("ziv_conformance_run", RUN_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module   # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def run():
    return _load_run()


@pytest.fixture(scope="module")
def goldens(run):
    return run.load_goldens()


def run_cli(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RUN_PY), *argv], cwd=REPO_ROOT, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=300)


# --- the golden set -------------------------------------------------------------


def test_golden_set_covers_the_contract(goldens):
    names = [name for name, _, _ in goldens]
    utts = [utt for _, utt, _ in goldens]
    assert len(goldens) >= 10
    assert all(utt.spec_version == T.SPEC_VERSION for utt in utts)
    assert {utt.kind for utt in utts} == set(Kind), "every kind, the error kind included"
    assert any(utt.prefix is not None for utt in utts) and any(utt.prefix is None for utt in utts)
    assert any(utt.body_pending and not utt.words for utt in utts)
    assert {len(utt.words) for utt in utts} >= {1, 2, 3}
    assert any(len(w) == MAX_WORD_LETTERS for utt in utts for w in utt.words)
    assert {"budget_six_actuator", "budget_single_actuator"} <= set(names)
    # golden files are the utterance and nothing else (no sidecar keys) — the
    # harness pipes the file text to players byte for byte
    for name, utt, raw in goldens:
        assert Utterance.model_validate_json(raw) == utt
        assert json.loads(raw)["id"].startswith("golden-")


@pytest.mark.parametrize("profile", list(Profile))
def test_budget_golden_is_the_longest_that_fits(goldens, profile):
    name = f"budget_{profile.value}"
    utt = next(u for n, u, _ in goldens if n == name)
    pace = T.CELL_GAP_DEFAULT_MS
    assert R.duration_ms(utt, profile, pace) <= BUDGET_MS

    # the smallest possible extension — one more lightest cell — no longer fits
    lightest = min(T.LETTERS, key=T.cell_ms)
    words = list(utt.words)
    if len(words[-1]) < MAX_WORD_LETTERS:
        words[-1] += lightest
    else:
        assert len(words) < MAX_WORDS
        words.append(lightest)
    longer = utt.model_copy(update={"words": words})
    assert R.duration_ms(longer, profile, pace) > BUDGET_MS


# --- the expected timelines are the reference's --------------------------------


def test_expected_files_are_in_sync_with_the_reference(run):
    assert run.check_expected() == []


def test_every_expected_file_is_the_reference_timeline(run, goldens):
    for name, utt, _ in goldens:
        for profile in run.PROFILES:
            path = run.expected_path(name, profile)
            assert path.is_file(), f"{path.name} missing — run conformance/run.py --write"
            beats = R.from_jsonl(path.read_text(encoding="utf-8"))
            assert beats == R.timeline(utt, profile, run.DEFAULT_PACE_MS)
            assert beats[0].t_ms == 0


def test_run_check_exits_zero():
    proc = run_cli("--check")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "in sync" in proc.stdout


def test_check_catches_drift_and_write_heals_it(run, tmp_path):
    expected = tmp_path / "expected"
    run.write_expected(expected_dir=expected)
    assert run.check_expected(expected_dir=expected) == []

    # a stale file: one beat moved
    victim = run.expected_path("message_two_words", "six_actuator", expected)
    beats = R.from_jsonl(victim.read_text(encoding="utf-8"))
    b = beats[3]
    beats[3] = R.Beat(b.t_ms + 1, b.dot_mask, b.buzz_ms, b.label)
    victim.write_text(R.to_jsonl(beats), encoding="utf-8")
    problems = run.check_expected(expected_dir=expected)
    assert len(problems) == 1 and "drifts" in problems[0] and victim.name in problems[0]

    # a missing file and an orphan are drift too
    victim.unlink()
    orphan = expected / "nobody.six_actuator.jsonl"
    orphan.write_text("", encoding="utf-8")
    problems = run.check_expected(expected_dir=expected)
    assert any("missing" in p for p in problems) and any("orphan" in p for p in problems)

    # --write heals both and is idempotent
    run.write_expected(expected_dir=expected)
    assert run.check_expected(expected_dir=expected) == []
    assert not orphan.exists()
    assert run.write_expected(expected_dir=expected) == []


def test_invalid_golden_is_refused(run, tmp_path):
    golden = tmp_path / "golden"
    golden.mkdir()
    (golden / "bad_one.json").write_text(json.dumps({"id": "golden-bad", "wearer": "w_1", "kind": "message",
                                                      "from": {"sender": "x"}, "words": [], "spec_version": 4}),
                                         encoding="utf-8")
    with pytest.raises(ValueError, match="not a valid utterance"):
        run.load_goldens(golden)


# --- the differ bites -----------------------------------------------------------


def test_perturbed_timeline_fails_diff(goldens):
    tol = T.CONFORMANCE_TOLERANCE_MS
    for name, utt, _ in goldens:
        expected = R.timeline(utt, "single_actuator", T.CELL_GAP_DEFAULT_MS)
        assert R.diff(expected, expected, tolerance_ms=tol) == []
        i = len(expected) // 2
        b = expected[i]
        late = list(expected)
        late[i] = R.Beat(b.t_ms + tol + 1, b.dot_mask, b.buzz_ms, b.label)
        assert R.diff(expected, late, tolerance_ms=tol), name
        merged = expected[:i] + expected[i + 1:]
        assert R.diff(expected, merged, tolerance_ms=tol), name


# --- a player run ---------------------------------------------------------------


def test_reference_player_conforms_on_single_actuator(goldens):
    proc = run_cli("--player", f"{sys.executable} {REFERENCE_PLAYER}", "--profile", "single_actuator")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = proc.stdout.splitlines()
    assert sum(line.startswith("PASS") for line in lines) == len(goldens)
    assert not any(line.startswith("FAIL") for line in lines)
    assert lines[-1] == f"conformance: {len(goldens)}/{len(goldens)} PASS on single_actuator"


def test_reference_player_conforms_on_six_actuator_in_process(run, goldens):
    # the full set runs on single_actuator above; here the other profile flows
    # through the in-process API on a subset, in golden order, in parallel
    subset = goldens[:4]
    results = run.run_player(f"{sys.executable} {REFERENCE_PLAYER}", "six_actuator", subset, jobs=4)
    assert [r.name for r in results] == [name for name, _, _ in subset]
    assert [r.ok for r in results] == [True] * len(subset)
    assert all(r.beats > 0 and r.duration_ms > 0 for r in results)


def test_player_honours_the_pace_flag(run, goldens):
    slow = run.run_player(f"{sys.executable} {REFERENCE_PLAYER}", "six_actuator", goldens[:1],
                          pace_ms=T.CELL_GAP_MAX_MS)
    assert slow[0].ok and slow[0].duration_ms > run.run_player(
        f"{sys.executable} {REFERENCE_PLAYER}", "six_actuator", goldens[:1])[0].duration_ms


def test_a_drifting_player_fails(run, goldens, tmp_path):
    player = tmp_path / "late_player.py"
    player.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(CONFORMANCE / 'players')!r})\n"
        "from ziv.haptics import reference as R\n"
        "from ziv.wire import Utterance\n"
        "import argparse\n"
        "ap = argparse.ArgumentParser(); ap.add_argument('--profile'); ap.add_argument('--pace', type=int)\n"
        "a = ap.parse_args()\n"
        "utt = Utterance.model_validate_json(sys.stdin.read())\n"
        "beats = R.timeline(utt, a.profile, a.pace)\n"
        f"late = [R.Beat(b.t_ms + (0 if i < 2 else {3 * T.CONFORMANCE_TOLERANCE_MS}), b.dot_mask, b.buzz_ms, b.label)"
        " for i, b in enumerate(beats)]\n"
        "sys.stdout.write(R.to_jsonl(late))\n",
        encoding="utf-8")
    results = run.run_player(f"{sys.executable} {player}", "single_actuator", goldens[:2])
    assert [r.ok for r in results] == [False, False]
    assert all(any("t_ms" in p for p in r.problems) for r in results)
    assert run.main(["--player", f"{sys.executable} {player}", "--profile", "single_actuator",
                     "--only", goldens[0][0]]) == 1


def test_a_broken_player_fails_loudly(run, goldens, tmp_path):
    silent = tmp_path / "silent.py"
    silent.write_text("import sys; sys.stdin.read(); print('')\n", encoding="utf-8")
    crashing = tmp_path / "crash.py"
    crashing.write_text("import sys; sys.stdin.read(); print('boom', file=sys.stderr); sys.exit(3)\n", encoding="utf-8")
    garbage = tmp_path / "garbage.py"
    garbage.write_text("import sys; sys.stdin.read(); print('HAP 0 START')\n", encoding="utf-8")
    one = goldens[:1]
    assert run.run_player(f"{sys.executable} {silent}", "six_actuator", one)[0].problems[0].startswith("beat count")
    crashed = run.run_player(f"{sys.executable} {crashing}", "six_actuator", one)[0]
    assert crashed.problems == ["player exited 3"] and "boom" in crashed.stderr
    assert "not a timeline" in run.run_player(f"{sys.executable} {garbage}", "six_actuator", one)[0].problems[0]
    assert "could not start" in run.run_player("/nonexistent/player", "six_actuator", one)[0].problems[0]
    with pytest.raises(ValueError, match="unknown profile"):
        run.run_player(f"{sys.executable} {silent}", "two_actuator", one)
