"""ziv.core.spec — the relay's view of the timing spec.

Everything here is read from ``ziv.haptics.tables.SPEC`` at call time, never
copied, so a regenerated table changes the relay's behaviour without a code
change. When the spec carries a ``kinds`` section (v4) it is the source of the
kind → cue/tail mapping; until then the v3 ``prefix.tails`` table and the
reference renderer's ``CUE_FOR_KIND`` stand in.
"""
from __future__ import annotations

from ziv.haptics import reference as R
from ziv.haptics import tables as T
from ziv.wire import Kind, Prefix, Profile, Utterance


def spec() -> dict:
    return T.SPEC


def spec_version() -> int:
    return int(T.SPEC.get("version", T.SPEC_VERSION))


def pace_envelope() -> tuple[int, int, int]:
    """``(min_ms, max_ms, default_ms)`` for the cell gap the wearer may choose."""
    c = T.SPEC.get("constants", {})
    lo = int(c.get("cell_gap_min_ms", T.CELL_GAP_MIN_MS))
    hi = int(c.get("cell_gap_max_ms", T.CELL_GAP_MAX_MS))
    default = int(c.get("cell_gap_default_ms", T.CELL_GAP_DEFAULT_MS))
    return lo, hi, max(lo, min(hi, default))


def clamp_pace(pace_ms: int) -> int:
    lo, hi, _ = pace_envelope()
    return max(lo, min(hi, int(pace_ms)))


def prefix_mark() -> str:
    return str(T.SPEC.get("prefix", {}).get("mark", T.PREFIX_MARK))


def _kind_section(kind: Kind) -> dict | None:
    kinds = T.SPEC.get("kinds")
    if isinstance(kinds, dict):
        entry = kinds.get(str(kind))
        if isinstance(entry, dict):
            return entry
    return None

def cue_for(kind: Kind) -> str:
    section = _kind_section(kind)
    if section and section.get("cue"):
        return str(section["cue"])
    return R.CUE_FOR_KIND[Kind(kind)]


def tail_for(kind: Kind) -> str:
    section = _kind_section(kind)
    if section and section.get("tail"):
        return str(section["tail"])
    tails = T.SPEC.get("prefix", {}).get("tails", T.PREFIX_TAILS)
    tail = tails.get(str(kind))
    return str(tail) if tail else cue_for(kind)


def prefix_for(kind: Kind) -> Prefix:
    """The name mark and the kind's tail, for an unsolicited utterance."""
    return Prefix(mark=prefix_mark(), tail=tail_for(kind))


def duration_ms(utt: Utterance, profile: Profile, pace_ms: int) -> int:
    """The time budget function. Always the reference renderer's, never a copy."""
    return R.duration_ms(utt, profile, pace_ms)
