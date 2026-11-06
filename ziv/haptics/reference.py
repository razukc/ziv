"""ziv.haptics.reference — the reference renderer.

``timeline(utterance, profile, pace_ms)`` is the definition of correct
playback: the list of buzzes, each with its start offset, dot mask and
duration, that a faithful device produces for one utterance. Admission uses
``duration_ms`` as the time budget; the conformance harness diffs the C
sequencer's and the web client's timelines against this one.

Every number here comes from ``ziv.haptics.tables`` (generated from the spec);
this module adds structure, never constants.

Shape of a turn (docs/HAPTIC_COMPANION_PLAN.md §4):

    [prefix: mark cells … breath … tail pattern]   only when present
    kind cue pattern
    [working pattern]                             only while body_pending
    cells, with cell gaps inside a word and the word gap between words
    close pattern (end-of-message)

STATUS: this is the Phase-0 skeleton. It implements the six-actuator profile
from the current spec and treats the single-actuator profile as identical,
pending the spec's renderer-profile section and word gap (owned by the
spec/renderer workstream, which replaces this file).
"""
from __future__ import annotations

from dataclasses import dataclass

from ziv.wire import Kind, Profile, Utterance

from . import tables as T


@dataclass(frozen=True)
class Beat:
    """One buzz on the actuator(s). Silence is the difference between beats."""

    t_ms: int        # start offset from the utterance's first buzz
    dot_mask: int    # bit n = dot n+1 raised; 0 for whole-device patterns
    buzz_ms: int
    label: str       # "prefix:z", "cue", "cell:t", "close" … for diffs and logs


# Kind -> arrival-cue pattern id. The spec will own this table; until it does,
# the mapping mirrors the relay's current constants.
CUE_FOR_KIND: dict[Kind, str] = {
    Kind.message: "double-tap",
    Kind.reminder: "triple-pulse",
    Kind.error: "long-buzz",
    Kind.system: "heartbeat",
}
CLOSE_PATTERN = "end-of-message"
WORKING_PATTERN = "processing"


def _pattern(label: str, pattern_id: str, t: int, out: list[Beat]) -> int:
    for buzz, gap in T.pattern_beats(pattern_id):
        out.append(Beat(t, 0, buzz, label))
        t += buzz + gap
    return t


def _cells(letters: str, t: int, pace_ms: int, out: list[Beat], tag: str) -> int:
    for ch in letters:
        out.append(Beat(t, T.LETTER_MASKS[ch], T.cell_ms(ch), f"{tag}:{ch}"))
        t += T.cell_ms(ch) + pace_ms
    return t


def timeline(utt: Utterance, profile: Profile, pace_ms: int) -> list[Beat]:
    """The expected buzzes for ``utt`` on ``profile`` at ``pace_ms`` between cells."""
    pace_ms = max(T.CELL_GAP_MIN_MS, min(T.CELL_GAP_MAX_MS, int(pace_ms)))
    out: list[Beat] = []
    t = 0
    if utt.prefix is not None:
        t = _cells(utt.prefix.mark, t, pace_ms, out, "prefix")
        # the last cell gap is replaced by the breath before the tail
        t += T.PREFIX_BREATH_MS - pace_ms
        t = _pattern("tail", utt.prefix.tail, t, out)
    t = _pattern("cue", CUE_FOR_KIND[utt.kind], t, out)
    if utt.body_pending and not utt.words:
        t = _pattern("working", WORKING_PATTERN, t, out)
    for i, word in enumerate(utt.words):
        if i:
            # Phase-0: the word gap is one extra cell gap; the spec will define it.
            t += pace_ms
        t = _cells(word, t, pace_ms, out, "cell")
    if utt.words:
        # the close follows the last cell after a tail gap, not a cell gap
        t += T.TAIL_GAP_MS - pace_ms
    _pattern("close", CLOSE_PATTERN, t, out)
    return out


def duration_ms(utt: Utterance, profile: Profile, pace_ms: int) -> int:
    """Total time from the first buzz to the end of the close, including its tail."""
    beats = timeline(utt, profile, pace_ms)
    if not beats:
        return 0
    last = beats[-1]
    close_beats = T.pattern_beats(CLOSE_PATTERN)
    tail_gap = close_beats[-1][1] if close_beats else 0
    return last.t_ms + last.buzz_ms + tail_gap
