"""The reference renderer: hand-derived goldens and structural invariants.

The golden tests pin spec v4 numbers derived by hand from docs/haptic-timing.json
(the derivation is in the comments). They are meant to break when the spec
changes: re-derive them, do not loosen them. The invariant tests hold for any
utterance the wire admits, on both profiles, at any pace — Hypothesis
generates the cases.
"""
from __future__ import annotations

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from ziv.haptics import reference as R
from ziv.haptics import tables as T
from ziv.haptics.reference import Beat
from ziv.wire import Kind, Profile, Utterance

DEFAULT_PACE = T.CELL_GAP_DEFAULT_MS
CLOSE_LEN = len(T.pattern_beats(R.CLOSE_PATTERN))
CLOSE_TAIL_GAP = T.pattern_beats(R.CLOSE_PATTERN)[-1][1]


def make(kind: str = "message", words=(), *, prefix: bool = False, pending: bool = False,
         mark: str = "ziv", tail: str | None = None) -> Utterance:
    d = {
        "id": "test-utterance-1", "wearer": "w_1", "kind": kind,
        "from": {"sender": "agent"}, "words": list(words), "body_pending": pending,
        "spec_version": T.SPEC_VERSION,
    }
    if prefix:
        d["prefix"] = {"mark": mark, "tail": tail or T.KINDS[kind]["tail"]}
    return Utterance.model_validate(d)


def cells_of(beats: list[Beat]) -> list[Beat]:
    return [b for b in beats if b.label.startswith(R.LABEL_CELL + ":")]


# --- the spec and the wire agree -----------------------------------------------


def test_spec_kinds_and_profiles_are_the_wire_vocabularies():
    assert set(T.KINDS) == {k.value for k in Kind}
    assert set(T.PROFILES) == {p.value for p in Profile}
    for kind, entry in T.KINDS.items():
        assert set(entry) == {"cue", "tail"}
        assert entry["cue"] in T.PATTERN_IDS and entry["tail"] in T.PATTERN_IDS
    assert T.PROFILES["six_actuator"]["encoding"] == "chord"
    assert T.PROFILES["single_actuator"]["encoding"] == "slots"
    assert sorted(T.PROFILES["single_actuator"]["order"]) == list(range(1, T.SLOT_COUNT + 1))


# --- goldens, derived by hand from spec v4 ------------------------------------

pytestmark_golden = pytest.mark.skipif(False, reason="")


def _needs_v4():
    assert T.SPEC_VERSION == 4, "the hand-derived goldens below are spec v4 — re-derive them"


def test_six_actuator_message_without_prefix():
    _needs_v4()
    # cue double-tap: 70/160 · 70/420 → first cell at 0+70+160+70+420 = 720
    # a (dot 1, 110 ms) at 720, ends 830; + pace 420 → b (dots 1-2, 170 ms) at 1250, ends 1420
    # + tail gap 420 → close at 1840: 200/120 · 140/120 · 90/120 · 50/420 → ends 3100
    utt = make(words=["ab"])
    assert R.timeline(utt, Profile.six_actuator, DEFAULT_PACE) == [
        Beat(0, 0x00, 70, "cue"), Beat(230, 0x00, 70, "cue"),
        Beat(720, 0x01, 110, "cell:a"), Beat(1250, 0x03, 170, "cell:b"),
        Beat(1840, 0, 200, "close"), Beat(2160, 0, 140, "close"),
        Beat(2420, 0, 90, "close"), Beat(2630, 0, 50, "close"),
    ]
    assert R.duration_ms(utt, Profile.six_actuator, DEFAULT_PACE) == 3100


def test_six_actuator_reminder_with_prefix_and_two_words():
    _needs_v4()
    # mark ziv: z (1-3-5-6 = 0x35, 290) at 0; +420 → i (2-4 = 0x0A, 170) at 710;
    # +420 → v (1-2-3-6 = 0x27, 290) at 1300, ends 1590; + breath 550 → 2140
    # tail triple-pulse 70/160 · 70/160 · 70/420 at 2140, 2370, 2600 → 3090
    # cue triple-pulse at 3090, 3320, 3550 → 4040
    # a at 4040 (110) ends 4150; + WORD GAP 520 → b at 4670 (170) ends 4840
    # + tail gap 420 → close at 5260, 5580, 5840, 6050 → 6520
    utt = make("reminder", ["a", "b"], prefix=True)
    assert R.timeline(utt, "six_actuator", DEFAULT_PACE) == [
        Beat(0, 0x35, 290, "prefix:z"), Beat(710, 0x0A, 170, "prefix:i"), Beat(1300, 0x27, 290, "prefix:v"),
        Beat(2140, 0, 70, "tail"), Beat(2370, 0, 70, "tail"), Beat(2600, 0, 70, "tail"),
        Beat(3090, 0, 70, "cue"), Beat(3320, 0, 70, "cue"), Beat(3550, 0, 70, "cue"),
        Beat(4040, 0x01, 110, "cell:a"), Beat(4670, 0x03, 170, "cell:b"),
        Beat(5260, 0, 200, "close"), Beat(5580, 0, 140, "close"),
        Beat(5840, 0, 90, "close"), Beat(6050, 0, 50, "close"),
    ]
    assert R.duration_ms(utt, "six_actuator", DEFAULT_PACE) == 6520


def test_single_actuator_one_cell_is_six_slots():
    _needs_v4()
    # slots 50 ms, slot gap 30, column gap 80 after slot 3:
    # slot starts 0, 80, 160, 320, 400, 480 → cell = 530 ms
    # c = dots 1-4 → pulses at cell+0 (0x01) and cell+320 (0x08)
    # cue ends 720 → cell at 720, ends 1250; + tail gap 420 → close at 1670 … ends 2930
    utt = make(words=["c"])
    assert R.timeline(utt, Profile.single_actuator, DEFAULT_PACE) == [
        Beat(0, 0, 70, "cue"), Beat(230, 0, 70, "cue"),
        Beat(720, 0x01, 50, "cell:c"), Beat(1040, 0x08, 50, "cell:c"),
        Beat(1670, 0, 200, "close"), Beat(1990, 0, 140, "close"),
        Beat(2250, 0, 90, "close"), Beat(2460, 0, 50, "close"),
    ]
    assert R.duration_ms(utt, Profile.single_actuator, DEFAULT_PACE) == 2930


def test_single_actuator_prefix_message():
    _needs_v4()
    # z (1-3-5-6): pulses at 0, 160, 400, 480; cell ends 530; +420 → i at 950
    # i (2-4): pulses at 950+80 = 1030, 950+320 = 1270; ends 1480; +420 → v at 1900
    # v (1-2-3-6): 1900, 1980, 2060, 2380; ends 2430; + breath 550 → tail at 2980
    # tail double-tap 2980, 3210 → 3700; cue 3700, 3930 → 4420
    # a: pulse at 4420; cell ends 4950; + 420 → close at 5370, 5690, 5950, 6160 → 6630
    utt = make("message", ["a"], prefix=True)
    assert R.timeline(utt, "single_actuator", DEFAULT_PACE) == [
        Beat(0, 0x01, 50, "prefix:z"), Beat(160, 0x04, 50, "prefix:z"),
        Beat(400, 0x10, 50, "prefix:z"), Beat(480, 0x20, 50, "prefix:z"),
        Beat(1030, 0x02, 50, "prefix:i"), Beat(1270, 0x08, 50, "prefix:i"),
        Beat(1900, 0x01, 50, "prefix:v"), Beat(1980, 0x02, 50, "prefix:v"),
        Beat(2060, 0x04, 50, "prefix:v"), Beat(2380, 0x20, 50, "prefix:v"),
        Beat(2980, 0, 70, "tail"), Beat(3210, 0, 70, "tail"),
        Beat(3700, 0, 70, "cue"), Beat(3930, 0, 70, "cue"),
        Beat(4420, 0x01, 50, "cell:a"),
        Beat(5370, 0, 200, "close"), Beat(5690, 0, 140, "close"),
        Beat(5950, 0, 90, "close"), Beat(6160, 0, 50, "close"),
    ]
    assert R.duration_ms(utt, "single_actuator", DEFAULT_PACE) == 6630


def test_body_pending_header_plays_one_processing():
    _needs_v4()
    # cue → 720; processing 70/350 · 70/420 at 720, 1140 → 1630; no words, so no tail gap;
    # close at 1630, 1950, 2210, 2420 → 2890
    utt = make(pending=True)
    assert R.timeline(utt, "six_actuator", DEFAULT_PACE) == [
        Beat(0, 0, 70, "cue"), Beat(230, 0, 70, "cue"),
        Beat(720, 0, 70, "working"), Beat(1140, 0, 70, "working"),
        Beat(1630, 0, 200, "close"), Beat(1950, 0, 140, "close"),
        Beat(2210, 0, 90, "close"), Beat(2420, 0, 50, "close"),
    ]
    assert R.duration_ms(utt, "six_actuator", DEFAULT_PACE) == 2890


# --- invariants, for any admissible utterance ---------------------------------

letters = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=6)
words_st = st.lists(letters, min_size=0, max_size=4)
kind_st = st.sampled_from([k.value for k in Kind])
profile_st = st.sampled_from([p.value for p in Profile])
pace_st = st.integers(min_value=0, max_value=3000)


@settings(max_examples=120, deadline=None)
@given(kind=kind_st, words=words_st, prefix=st.booleans(), pending=st.booleans(),
       profile=profile_st, pace=pace_st)
def test_timeline_invariants(kind, words, prefix, pending, profile, pace):
    assume(words or pending)
    utt = make(kind, words, prefix=prefix, pending=pending)
    beats = R.timeline(utt, profile, pace)
    clamped = R.clamp_pace(pace)

    # strictly increasing starts, no overlapping buzzes, origin at the first buzz
    assert beats and beats[0].t_ms == 0
    for a, b in zip(beats, beats[1:]):
        assert a.t_ms < b.t_ms
        assert a.end_ms <= b.t_ms
    assert all(b.buzz_ms > 0 for b in beats)

    # the prefix comes first (when present), the close last
    if prefix:
        assert beats[0].label == f"prefix:{utt.prefix.mark[0]}"
    else:
        assert beats[0].label == R.LABEL_CUE
    assert [b.label for b in beats[-CLOSE_LEN:]] == [R.LABEL_CLOSE] * CLOSE_LEN
    assert beats[-CLOSE_LEN - 1].label != R.LABEL_CLOSE
    assert [b.buzz_ms for b in beats[-CLOSE_LEN:]] == [buzz for buzz, _ in T.pattern_beats(R.CLOSE_PATTERN)]

    # the cue is the kind's; whole-device beats carry no dots
    cue = [b for b in beats if b.label == R.LABEL_CUE]
    assert [b.buzz_ms for b in cue] == [buzz for buzz, _ in T.pattern_beats(T.KINDS[kind]["cue"])]
    assert all(b.dot_mask == 0 for b in beats if not b.label.startswith(("cell:", "prefix:")))

    # body_pending with no words adds exactly one processing play, otherwise none
    working = [b for b in beats if b.label == R.LABEL_WORKING]
    if pending and not words:
        assert [b.buzz_ms for b in working] == [buzz for buzz, _ in T.pattern_beats(R.WORKING_PATTERN)]
    else:
        assert working == []

    # the duration is the last beat's end plus the close's tail gap
    assert R.duration_ms(utt, profile, pace) == beats[-1].end_ms + CLOSE_TAIL_GAP

    # cells carry exactly the letters' dots
    expected_letters = list("".join(words))
    if profile == "six_actuator":
        cells = cells_of(beats)
        assert [b.label[len("cell:"):] for b in cells] == expected_letters
        for b in cells:
            ch = b.label[len("cell:"):]
            assert b.dot_mask == T.LETTER_MASKS[ch]
            assert b.buzz_ms == T.cell_ms(ch)
    else:
        groups = _slot_cells(cells_of(beats))
        assert [label[len("cell:"):] for label, _ in groups] == expected_letters
        slot = T.PROFILES["single_actuator"]["slot_ms"]
        for label, group in groups:
            ch = label[len("cell:"):]
            masks = [b.dot_mask for b in group]
            assert all(m and (m & (m - 1)) == 0 for m in masks), "one dot per slot beat"
            assert len(masks) == T.LETTER_DOTS[ch]
            combined = 0
            for m in masks:
                combined |= m
            assert combined == T.LETTER_MASKS[ch]
            assert all(b.buzz_ms == slot for b in group)
            # the pulses fall on the slot offsets of their dots
            start = group[0].t_ms - _slot_offset(group[0].dot_mask)
            assert [b.t_ms - start for b in group] == [_slot_offset(m) for m in masks]

    # inside a word, consecutive cells are one clamped pace apart
    if profile == "six_actuator":
        cells = cells_of(beats)
        i = 0
        for word in words:
            for _ in range(len(word) - 1):
                assert cells[i + 1].t_ms - cells[i].end_ms == clamped
                i += 1
            i += 1


def _slot_offset(mask: int) -> int:
    """Start offset of the slot that plays one dot, from the spec's slot layout."""
    p = T.PROFILES["single_actuator"]
    dot = mask.bit_length()          # single-bit mask -> dot number 1..6
    t = 0
    for i, d in enumerate(p["order"]):
        if d == dot:
            return t
        t += p["slot_ms"]
        if i < T.SLOT_COUNT - 1:
            t += p["slot_gap_ms"]
        if i == T.SLOT_COUNT // 2 - 1:
            t += p["column_gap_ms"]
    raise AssertionError(f"mask {mask:#x} is not one dot")


def _slot_cells(cells: list[Beat]) -> list[tuple[str, list[Beat]]]:
    """Group single-actuator cell beats back into cells: a new cell starts when
    the label changes or a beat falls a whole slot-cell after the group's first."""
    cell_ms = T.slot_cell_ms()
    groups: list[tuple[str, list[Beat]]] = []
    for b in cells:
        if groups and groups[-1][0] == b.label and b.t_ms < groups[-1][1][0].t_ms + cell_ms:
            groups[-1][1].append(b)
        else:
            groups.append((b.label, [b]))
    return groups


def test_word_gap_sits_exactly_between_words_and_nowhere_else():
    assert T.WORD_GAP_MS != DEFAULT_PACE, "the test needs the word gap and the pace to differ"
    utt = make("message", ["ab", "cd", "e"])
    cells = cells_of(R.timeline(utt, "six_actuator", DEFAULT_PACE))
    gaps = [b.t_ms - a.end_ms for a, b in zip(cells, cells[1:])]
    # a→b pace, b→c word gap, c→d pace, d→e word gap
    assert gaps == [DEFAULT_PACE, T.WORD_GAP_MS, DEFAULT_PACE, T.WORD_GAP_MS]
    assert gaps.count(T.WORD_GAP_MS) == len(utt.words) - 1
    # and the single-actuator profile spaces whole cells the same way
    cells = cells_of(R.timeline(utt, "single_actuator", DEFAULT_PACE))
    groups = _slot_cells(cells)
    starts = [g[0].t_ms - _slot_offset(g[0].dot_mask) for _, g in groups]
    gaps = [b - a - T.slot_cell_ms() for a, b in zip(starts, starts[1:])]
    assert gaps == [DEFAULT_PACE, T.WORD_GAP_MS, DEFAULT_PACE, T.WORD_GAP_MS]


def test_prefix_breath_and_tail_gap_frame_the_words():
    utt = make("message", ["a"], prefix=True)
    beats = R.timeline(utt, "six_actuator", DEFAULT_PACE)
    last_mark = [b for b in beats if b.label.startswith("prefix:")][-1]
    first_tail = next(b for b in beats if b.label == R.LABEL_TAIL)
    assert first_tail.t_ms - last_mark.end_ms == T.PREFIX_BREATH_MS
    last_cell = cells_of(beats)[-1]
    first_close = next(b for b in beats if b.label == R.LABEL_CLOSE)
    assert first_close.t_ms - last_cell.end_ms == T.TAIL_GAP_MS


def test_body_pending_adds_exactly_one_processing_play():
    plain = make("message", ["ok"])
    pending = make("message", [], pending=True)
    for profile in Profile:
        d_pending = R.duration_ms(pending, profile, DEFAULT_PACE)
        header_only = R.duration_ms(make("message", ["a"]), profile, DEFAULT_PACE)
        # pending = cue + processing + close; a one-cell utterance = cue + cell + tail gap + close
        cell = R.cell_duration_ms(profile, "a")
        assert d_pending - (header_only - cell - T.TAIL_GAP_MS) == T.pattern_ms(R.WORKING_PATTERN)
        assert sum(b.label == R.LABEL_WORKING for b in R.timeline(plain, profile, DEFAULT_PACE)) == 0
    # a pending utterance whose words already arrived plays them, not the working pattern
    arrived = make("message", ["ok"], pending=True)
    assert R.timeline(arrived, "six_actuator", DEFAULT_PACE) == R.timeline(plain, "six_actuator", DEFAULT_PACE)


@pytest.mark.parametrize("profile", list(Profile))
def test_pace_is_clamped_into_the_spec_envelope(profile):
    utt = make("message", ["abc", "de"], prefix=True)
    slow = R.timeline(utt, profile, T.CELL_GAP_MAX_MS)
    fast = R.timeline(utt, profile, T.CELL_GAP_MIN_MS)
    assert R.timeline(utt, profile, T.CELL_GAP_MAX_MS * 10) == slow
    assert R.timeline(utt, profile, T.CELL_GAP_MIN_MS - 1) == fast
    assert R.timeline(utt, profile, 0) == fast
    assert slow != fast
    mid = (T.CELL_GAP_MIN_MS + T.CELL_GAP_MAX_MS) // 2
    assert fast != R.timeline(utt, profile, mid) != slow
    # the pace only moves cells: pattern beats before the first cell are unaffected
    n_lead = next(i for i, b in enumerate(fast) if b.label.startswith("cell:"))
    assert fast[:1] == slow[:1]
    assert n_lead > 0


def test_duration_grows_with_words_and_the_phone_is_slower():
    one = make("message", ["cat"])
    two = make("message", ["cat", "nap"])
    for profile in Profile:
        assert R.duration_ms(two, profile, DEFAULT_PACE) > R.duration_ms(one, profile, DEFAULT_PACE)
    assert (R.duration_ms(two, Profile.single_actuator, DEFAULT_PACE)
            > R.duration_ms(two, Profile.six_actuator, DEFAULT_PACE))


def test_prefix_tail_must_agree_with_the_kind():
    # the pattern id or the kind name both spell the same tail
    by_pattern = make("reminder", ["a"], prefix=True, tail=T.KINDS["reminder"]["tail"])
    by_kind = make("reminder", ["a"], prefix=True, tail="reminder")
    assert R.timeline(by_pattern, "six_actuator", DEFAULT_PACE) == R.timeline(by_kind, "six_actuator", DEFAULT_PACE)
    # another kind's tail is a contradiction the oracle refuses
    with pytest.raises(ValueError, match="disagrees"):
        R.timeline(make("reminder", ["a"], prefix=True, tail=T.KINDS["message"]["tail"]), "six_actuator", DEFAULT_PACE)
    with pytest.raises(ValueError, match="unknown profile"):
        R.timeline(make("message", ["a"]), "four_actuator", DEFAULT_PACE)


# --- the interchange format and the differ ------------------------------------


def test_jsonl_round_trip_and_format():
    beats = R.timeline(make("reminder", ["ab", "c"], prefix=True), "single_actuator", DEFAULT_PACE)
    text = R.to_jsonl(beats)
    assert text.splitlines()[0] == '{"t_ms":0,"dot_mask":1,"buzz_ms":50,"label":"prefix:z"}'
    assert text.endswith("\n") and text.count("\n") == len(beats)
    assert R.from_jsonl(text) == beats
    assert R.from_jsonl("\n" + text + "\n\n") == beats
    assert R.to_jsonl([]) == "" and R.from_jsonl("") == []


@pytest.mark.parametrize("bad, message", [
    ("not json", "not JSON"),
    ("[1,2,3]", "expected an object"),
    ('{"t_ms":"0","dot_mask":0,"buzz_ms":70,"label":"cue"}', "t_ms must be an integer"),
    ('{"t_ms":0,"dot_mask":true,"buzz_ms":70,"label":"cue"}', "dot_mask must be an integer"),
    ('{"t_ms":0,"dot_mask":0,"label":"cue"}', "buzz_ms must be an integer"),
    ('{"t_ms":0,"dot_mask":0,"buzz_ms":70,"label":7}', "label must be a string"),
])
def test_from_jsonl_refuses_garbage(bad, message):
    with pytest.raises(ValueError, match=message):
        R.from_jsonl('{"t_ms":0,"dot_mask":0,"buzz_ms":70,"label":"cue"}\n' + bad + "\n")


def test_diff_is_empty_only_for_a_conformant_timeline():
    tol = T.CONFORMANCE_TOLERANCE_MS
    expected = R.timeline(make("message", ["hi", "there"], prefix=True), "six_actuator", DEFAULT_PACE)
    assert R.diff(expected, list(expected), tolerance_ms=tol) == []

    def shifted(i, dt):
        out = list(expected)
        b = out[i]
        out[i] = Beat(b.t_ms + dt, b.dot_mask, b.buzz_ms, "whatever the player calls it")
        return out

    # labels are the player's own; drift inside the tolerance is fine, one beyond is not
    assert R.diff(expected, shifted(5, tol), tolerance_ms=tol) == []
    assert R.diff(expected, shifted(5, -tol), tolerance_ms=tol) == []
    problems = R.diff(expected, shifted(5, tol + 1), tolerance_ms=tol)
    assert len(problems) == 1 and "t_ms" in problems[0] and expected[5].label in problems[0]

    # the mask and the buzz are exact
    b = expected[6]
    wrong_mask = list(expected)
    wrong_mask[6] = Beat(b.t_ms, b.dot_mask ^ 0x01, b.buzz_ms, b.label)
    assert any("dot_mask" in p for p in R.diff(expected, wrong_mask, tolerance_ms=tol))
    wrong_buzz = list(expected)
    wrong_buzz[6] = Beat(b.t_ms, b.dot_mask, b.buzz_ms + 1, b.label)
    assert any("buzz_ms" in p for p in R.diff(expected, wrong_buzz, tolerance_ms=tol))

    # a missing or an extra beat is a count problem that names the beat
    short = R.diff(expected, expected[:-1], tolerance_ms=tol)
    assert short[0].startswith("beat count") and any("missing" in p for p in short)
    extra = R.diff(expected, expected + [Beat(expected[-1].end_ms + 1, 0, 1, "x")], tolerance_ms=tol)
    assert extra[0].startswith("beat count") and any("extra" in p for p in extra)
