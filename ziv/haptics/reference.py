"""ziv.haptics.reference — the reference renderer.

``timeline(utterance, profile, pace_ms)`` is the definition of correct
playback: the list of buzzes, each with its start offset, dot mask and
duration, that a faithful device produces for one utterance. Admission uses
``duration_ms`` as the time budget; the conformance harness
(``conformance/run.py``) diffs the C sequencer's and the phone client's
timelines against this one with ``diff``.

Every number here comes from ``ziv.haptics.tables`` (generated from
``docs/haptic-timing.json`` by ``tools/haptic_timing.py --write``) and is read
at call time; this module adds structure, never constants.

Shape of a turn (docs/HAPTIC_COMPANION_PLAN.md §4, docs/ARCHITECTURE.md §5):

    [prefix: mark cells … breath … the kind's tail pattern]   only when present
    the kind's cue pattern
    [one `processing` play]                                  only while body_pending
    the words: the pace between cells, the word gap between words
    tail gap, then the close (`end-of-message`)

Profiles (docs/ARCHITECTURE.md §5.2):

* ``six_actuator`` — a cell is one beat: the letter's dots driven together for
  ``cell_ms``.
* ``single_actuator`` — a cell is six time slots in the spec's ``order``; a
  raised dot is one beat of ``slot_ms`` in its slot (``dot_mask`` = that dot's
  bit), an absent dot is ``slot_ms`` of silence; ``slot_gap_ms`` follows every
  slot but the last and ``column_gap_ms`` more follows the third. The cell's
  duration is fixed whatever the letter.

Patterns (cue, tail, working, close) are whole-device beats: ``dot_mask`` 0.

Labels, for diffs and logs: ``prefix:z``, ``tail``, ``cue``, ``working``,
``cell:t``, ``close``. The slot beats of one cell share the cell's label.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

from ziv.wire import Kind, Profile, Utterance

from . import tables as T

CLOSE_PATTERN = "end-of-message"
WORKING_PATTERN = "processing"

LABEL_PREFIX = "prefix"
LABEL_TAIL = "tail"
LABEL_CUE = "cue"
LABEL_WORKING = "working"
LABEL_CELL = "cell"
LABEL_CLOSE = "close"

JSONL_FIELDS = ("t_ms", "dot_mask", "buzz_ms", "label")


@dataclass(frozen=True)
class Beat:
    """One buzz on the actuator(s). Silence is the difference between beats."""

    t_ms: int        # start offset from the utterance's first buzz
    dot_mask: int    # bit n = dot n+1 raised; 0 for whole-device patterns
    buzz_ms: int
    label: str       # "prefix:z", "tail", "cue", "working", "cell:t", "close"

    @property
    def end_ms(self) -> int:
        return self.t_ms + self.buzz_ms


# --- vocabulary lookups (read from the tables module at call time) ----------


def clamp_pace(pace_ms: int) -> int:
    """The spec's cell-gap envelope: a device never plays outside it."""
    return max(T.CELL_GAP_MIN_MS, min(T.CELL_GAP_MAX_MS, int(pace_ms)))


def kind_id(kind: Kind | str) -> str:
    kid = kind.value if isinstance(kind, Kind) else str(kind)
    if kid not in T.KINDS:
        raise ValueError(f"unknown kind {kid!r}; the spec knows {sorted(T.KINDS)}")
    return kid


def profile_id(profile: Profile | str) -> str:
    pid = profile.value if isinstance(profile, Profile) else str(profile)
    if pid not in T.PROFILES:
        raise ValueError(f"unknown profile {pid!r}; the spec knows {sorted(T.PROFILES)}")
    return pid


def cue_pattern(kind: Kind | str) -> str:
    return T.KINDS[kind_id(kind)]["cue"]


def tail_pattern(kind: Kind | str) -> str:
    return T.KINDS[kind_id(kind)]["tail"]


def prefix_tail_pattern(utt: Utterance) -> str:
    """The tail after the name mark is the kind's. ``prefix.tail`` on the wire
    may spell it as the pattern id or as the kind name; either way it must
    agree, because an oracle refuses inconsistent input rather than guessing."""
    kid = kind_id(utt.kind)
    tail = T.KINDS[kid]["tail"]
    declared = utt.prefix.tail
    if declared not in (tail, kid):
        raise ValueError(
            f"prefix.tail {declared!r} disagrees with kind {kid!r}, whose tail is {tail!r}")
    return tail


def cell_duration_ms(profile: Profile | str, letter: str) -> int:
    """How long one cell occupies on a profile: the chord's ``cell_ms`` on the
    band, the fixed slot-cell duration on a single actuator."""
    prof = T.PROFILES[profile_id(profile)]
    if prof["encoding"] == "chord":
        return T.cell_ms(letter)
    return T.slot_cell_ms(profile_id(profile))


# --- the renderer -----------------------------------------------------------


class _Render:
    """A cursor over one utterance's timeline: appends beats, advances time."""

    def __init__(self, profile: str, pace_ms: int) -> None:
        self.profile = T.PROFILES[profile]
        self.profile_name = profile
        self.pace = pace_ms
        self.beats: list[Beat] = []
        self.t = 0

    def pattern(self, label: str, pattern_name: str) -> None:
        for buzz, gap in T.pattern_beats(pattern_name):
            self.beats.append(Beat(self.t, 0, buzz, label))
            self.t += buzz + gap

    def cell(self, letter: str, label: str) -> None:
        mask = T.LETTER_MASKS[letter]
        if self.profile["encoding"] == "chord":
            buzz = T.cell_ms(letter)
            self.beats.append(Beat(self.t, mask, buzz, label))
            self.t += buzz
            return
        # slots: one beat per raised dot, in the profile's order; silence otherwise
        slot, slot_gap, column_gap = (
            self.profile["slot_ms"], self.profile["slot_gap_ms"], self.profile["column_gap_ms"])
        order = self.profile["order"]
        last = len(order) - 1
        column_break = len(order) // 2 - 1   # after the third of six slots
        for i, dot in enumerate(order):
            bit = 1 << (dot - 1)
            if mask & bit:
                self.beats.append(Beat(self.t, bit, slot, label))
            self.t += slot
            if i < last:
                self.t += slot_gap
            if i == column_break:
                self.t += column_gap

    def silence(self, ms: int) -> None:
        self.t += ms


def _render(utt: Utterance, profile: Profile | str, pace_ms: int) -> _Render:
    pace = clamp_pace(pace_ms)
    r = _Render(profile_id(profile), pace)
    kid = kind_id(utt.kind)

    if utt.prefix is not None:
        mark = utt.prefix.mark
        for i, ch in enumerate(mark):
            r.cell(ch, f"{LABEL_PREFIX}:{ch}")
            r.silence(T.PREFIX_BREATH_MS if i == len(mark) - 1 else pace)
        r.pattern(LABEL_TAIL, prefix_tail_pattern(utt))

    r.pattern(LABEL_CUE, T.KINDS[kid]["cue"])

    if utt.body_pending and not utt.words:
        # The header part only: the device repeats this every WORKING_EVERY_MS
        # on its own clock until the body arrives; that is device time.
        r.pattern(LABEL_WORKING, WORKING_PATTERN)

    for wi, word in enumerate(utt.words):
        if wi:
            r.silence(T.WORD_GAP_MS)
        for ci, ch in enumerate(word):
            if ci:
                r.silence(pace)
            r.cell(ch, f"{LABEL_CELL}:{ch}")

    if utt.words:
        r.silence(T.TAIL_GAP_MS)
    r.pattern(LABEL_CLOSE, CLOSE_PATTERN)
    return r


def timeline(utt: Utterance, profile: Profile | str, pace_ms: int) -> list[Beat]:
    """The expected buzzes for ``utt`` on ``profile`` at ``pace_ms`` between cells."""
    return _render(utt, profile, pace_ms).beats


def duration_ms(utt: Utterance, profile: Profile | str, pace_ms: int) -> int:
    """Total time from the first buzz to the end of the close, its tail gap
    included — the time budget admission charges for the utterance."""
    return _render(utt, profile, pace_ms).t


# --- the interchange format and the differ ----------------------------------


def to_jsonl(beats: Iterable[Beat]) -> str:
    """One beat per line: ``{"t_ms":int,"dot_mask":int,"buzz_ms":int,"label":str}``."""
    lines = [
        json.dumps({"t_ms": b.t_ms, "dot_mask": b.dot_mask, "buzz_ms": b.buzz_ms, "label": b.label},
                   separators=(",", ":"), ensure_ascii=True)
        for b in beats
    ]
    return "".join(line + "\n" for line in lines)


def from_jsonl(text: str) -> list[Beat]:
    """Parse a timeline a player printed. Blank lines are skipped; anything
    else that is not a beat object with integer fields is a ``ValueError``
    naming the line, so a broken player fails loudly instead of conforming
    by accident."""
    beats: list[Beat] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {n}: not JSON ({exc.msg})") from None
        if not isinstance(obj, dict):
            raise ValueError(f"line {n}: expected an object, got {type(obj).__name__}")
        values = []
        for field in ("t_ms", "dot_mask", "buzz_ms"):
            v = obj.get(field)
            if not isinstance(v, int) or isinstance(v, bool):
                raise ValueError(f"line {n}: {field} must be an integer, got {v!r}")
            values.append(v)
        label = obj.get("label", "")
        if not isinstance(label, str):
            raise ValueError(f"line {n}: label must be a string, got {label!r}")
        beats.append(Beat(values[0], values[1], values[2], label))
    return beats


def diff(expected: list[Beat], actual: list[Beat], *, tolerance_ms: int) -> list[str]:
    """Every way ``actual`` departs from ``expected``; an empty list means
    conformant. Beat count must match; ``dot_mask`` and ``buzz_ms`` must match
    exactly; ``t_ms`` may differ by at most ``tolerance_ms``. Labels are the
    player's own and are not compared — the expected label names the beat."""
    out: list[str] = []
    if len(expected) != len(actual):
        out.append(f"beat count: expected {len(expected)}, got {len(actual)}")
    for i, (e, a) in enumerate(zip(expected, actual)):
        where = f"beat {i} ({e.label})"
        dt = a.t_ms - e.t_ms
        if abs(dt) > tolerance_ms:
            out.append(f"{where}: t_ms expected {e.t_ms}, got {a.t_ms} "
                       f"(Δ {dt:+d} ms, tolerance ±{tolerance_ms})")
        if e.dot_mask != a.dot_mask:
            out.append(f"{where}: dot_mask expected 0x{e.dot_mask:02X}, got 0x{a.dot_mask:02X}")
        if e.buzz_ms != a.buzz_ms:
            out.append(f"{where}: buzz_ms expected {e.buzz_ms}, got {a.buzz_ms}")
    if len(actual) > len(expected):
        extra = actual[len(expected)]
        out.append(f"beat {len(expected)}: unexpected extra beat at {extra.t_ms} ms "
                   f"(0x{extra.dot_mask:02X}, {extra.buzz_ms} ms, {extra.label!r})")
    elif len(actual) < len(expected):
        missing = expected[len(actual)]
        out.append(f"beat {len(actual)} ({missing.label}): missing (expected at {missing.t_ms} ms)")
    return out
