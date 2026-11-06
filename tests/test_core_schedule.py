"""Due selection, leases, and the utterance a fired row becomes."""
from __future__ import annotations

from ziv.core import schedule, spec
from ziv.core.model import Refusal, ScheduleEntry, WearerPrefs
from ziv.haptics import reference, tables
from ziv.wire import Kind, Prefs, Reason, Source


def row(i, fire_at, **kw):
    base = dict(id=i, wearer="w", fire_at=fire_at, kind=Kind.reminder, text="meds", intent=None,
                expires_after_s=3600, created=0.0)
    base.update(kw)
    return ScheduleEntry(**base)


def test_due_and_lease():
    rows = [row(1, 100.0), row(2, 50.0), row(3, 200.0), row(4, 10.0, lease_until=150.0)]
    assert [r.id for r in schedule.due(rows, 100.0)] == [2, 1]
    leased = schedule.lease(rows[1], 100.0, 30.0)
    assert leased.lease_until == 130.0 and schedule.is_leased(leased, 129.9) and not schedule.is_leased(leased, 130.0)
    assert [r.id for r in schedule.due(rows, 150.0)] == [4, 2, 1]


def test_cap_refuses_never_evicts():
    assert schedule.check_cap(63, 64) is None
    r = schedule.check_cap(64, 64)
    assert isinstance(r, Refusal) and r.reason == Reason.queue_full and r.detail == {"scheduled": 64, "cap": 64}


def test_build_utterance_takes_prefix_and_windows_from_the_row_and_spec():
    r = row(7, 1_000.0, label="pills")
    u = schedule.build_utterance(r, id="sched-0000007", words=["meds", "nine"], body_pending=False,
                                 source=Source.sender, sender="schedule")
    assert u.kind == Kind.reminder and u.words == ["meds", "nine"] and u.from_.label == "pills"
    assert u.prefix is not None and u.prefix.mark == tables.SPEC["prefix"]["mark"]
    assert u.prefix.tail == spec.tail_for(Kind.reminder)
    assert u.not_before.timestamp() == 1_000.0 and u.expires.timestamp() == 4_600.0
    assert u.spec_version == tables.SPEC["version"]
    pending = schedule.build_utterance(r.with_(text=None, intent="take pills"), id="sched-0000008", words=[],
                                       body_pending=True, source=Source.live, sender="schedule")
    assert pending.body_pending and pending.words == []


def test_spec_view_reads_the_tables_not_copies():
    kinds = tables.SPEC.get("kinds")
    for kind in Kind:
        if kinds and str(kind) in kinds:
            assert spec.tail_for(kind) == kinds[str(kind)]["tail"]
            assert spec.cue_for(kind) == kinds[str(kind)]["cue"]
        else:
            assert spec.cue_for(kind) == reference.CUE_FOR_KIND[kind]
            tails = tables.SPEC["prefix"]["tails"]
            assert spec.tail_for(kind) == tails.get(str(kind), reference.CUE_FOR_KIND[kind])
    lo, hi, default = spec.pace_envelope()
    assert lo == tables.SPEC["constants"]["cell_gap_min_ms"] and hi == tables.SPEC["constants"]["cell_gap_max_ms"]
    assert lo <= default <= hi


def test_prefs_clamp_into_envelope():
    lo, hi, default = spec.pace_envelope()
    p = WearerPrefs.defaults()
    assert p.pace_ms == default
    assert p.merged(Prefs(pace_ms=100)).pace_ms == lo
    assert p.merged(Prefs(pace_ms=2000)).pace_ms == hi
    assert p.merged(Prefs(advance="tap")).advance == "tap" and p.merged(Prefs()).pace_ms == default
