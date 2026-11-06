"""Property tests for the outbox state machine (docs/ARCHITECTURE.md §10, tier 1).

No loss, no duplication, bounded depth, every refusal has a reason, every
transition legal, failover never leaves an entry without an owner or a reason.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from ziv.core import outbox
from ziv.core.model import OutboxEntry, Refusal, to_datetime
from ziv.core.outbox import DeviceSlot, IllegalTransition, LogEvent, SendBody, SendCancel, SendOpen
from ziv.wire import Kind, Late, Phase, Reason, Source, State, Utterance

WORDS = st.lists(st.from_regex(r"^[a-z]{1,5}$", fullmatch=True), min_size=1, max_size=3)


def make_entry(i: int, now: float, words=("hi",), *, expires_in: float | None = None,
               body_pending: bool = False, wearer: str = "w") -> OutboxEntry:
    utt = Utterance(
        id=f"u{i:08d}", wearer=wearer, kind=Kind.message, **{"from": {"sender": "t"}},
        words=[] if body_pending else list(words), body_pending=body_pending,
        expires=to_datetime(now + expires_in) if expires_in is not None else None, spec_version=3,
    )
    return OutboxEntry(utterance=utt, state=State.pending, created=now, updated=now, duration_ms=1000, budget_ms=15000)


# --- explicit sequences -----------------------------------------------------


def test_happy_path_pending_sent_playing_played():
    now = 100.0
    e = make_entry(1, now)
    admitted, fx = outbox.admit([], e, cap=5)
    assert admitted.state == State.pending and any(isinstance(f, LogEvent) for f in fx)
    entries, fx = outbox.assign([admitted], [DeviceSlot("d1", True, 2, True)], now)
    assert entries[0].state == State.sent and entries[0].device == "d1" and entries[0].sent_at == now
    assert [type(f) for f in fx][0] is SendOpen
    e2, _ = outbox.on_progress(entries[0], "d1", Phase.cue, now + 1)
    assert e2.state == State.playing
    e3, fx = outbox.on_played(e2, "d1", now + 5, played_ms=4000)
    assert e3.state == State.played and e3.played_ms == 4000 and e3.reason is None


def test_cap_refuses_newest_with_reason():
    now = 0.0
    entries = []
    for i in range(3):
        r = outbox.admit(entries, make_entry(i, now), cap=3)
        assert not isinstance(r, Refusal)
        entries.append(r[0])
    r = outbox.admit(entries, make_entry(9, now), cap=3)
    assert isinstance(r, Refusal) and r.reason == Reason.queue_full
    assert r.detail == {"active": 3, "cap": 3}
    assert {e.id for e in entries} == {"u00000000", "u00000001", "u00000002"}  # the oldest were kept


def test_assign_prefers_primary_then_order_and_respects_capacity():
    now = 0.0
    entries = [make_entry(i, now + i) for i in range(4)]
    slots = [DeviceSlot("b", True, 1, False, 1), DeviceSlot("a", True, 2, True, 0), DeviceSlot("c", False, 9, False, 2)]
    after, fx = outbox.assign(entries, slots, now)
    assert [e.device for e in after] == ["a", "a", "b", None]
    assert after[3].state == State.pending
    assert sum(isinstance(f, SendOpen) for f in fx) == 3


def test_not_before_holds_assignment():
    now = 1000.0
    e = make_entry(1, now)
    e = e.with_(utterance=e.utterance.model_copy(update={"not_before": to_datetime(now + 60)}))
    after, _ = outbox.assign([e], [DeviceSlot("d", True, 1, True)], now)
    assert after[0].state == State.pending
    after, _ = outbox.assign([e], [DeviceSlot("d", True, 1, True)], now + 60)
    assert after[0].state == State.sent


def test_failover_returns_to_pending_with_reason_and_cancels_old_device():
    now = 0.0
    e = make_entry(1, now)
    after, _ = outbox.assign([e], [DeviceSlot("d1", True, 1, True)], now)
    unchanged, fx = outbox.failover(after, now + 7.9, 8.0)
    assert unchanged[0].state == State.sent and fx == []
    after2, fx = outbox.failover(after, now + 8.0, 8.0)
    e2 = after2[0]
    assert e2.state == State.pending and e2.device is None and e2.reason == Reason.failover and e2.tried == {"d1"}
    assert SendCancel("d1", e2.id, Reason.failover) in fx
    # d1 is skipped until it says hello again; d2 takes it
    after3, fx = outbox.assign(after2, [DeviceSlot("d1", True, 1, True), DeviceSlot("d2", True, 1, False, 1)], now + 8)
    assert after3[0].device == "d2"
    forgiven = outbox.forgive(after2, "d1")
    after4, _ = outbox.assign(forgiven, [DeviceSlot("d1", True, 1, True)], now + 8)
    assert after4[0].device == "d1"


def test_device_gone_requeues_and_progress_from_old_owner_is_a_logged_duplicate():
    now = 0.0
    e = make_entry(1, now)
    after, _ = outbox.assign([e], [DeviceSlot("d1", True, 1, True)], now)
    after, fx = outbox.on_device_gone(after, "d1", now + 1)
    assert after[0].state == State.pending and after[0].reason == Reason.device_gone
    assert fx and fx[0].kind == "device_gone" and fx[0].counts == {"requeued": 1}
    same, fx = outbox.on_progress(after[0], "d1", Phase.cue, now + 2)
    assert same == after[0] and fx[0].kind == "duplicate_play"


def test_expiry_drop_and_play():
    now = 0.0
    e = make_entry(1, now, expires_in=10)
    sent, _ = outbox.assign([e], [DeviceSlot("d1", True, 1, True)], now)
    kept, fx = outbox.on_expiry(sent, now + 9, Late.drop)
    assert kept[0].state == State.sent and fx == []
    dropped, fx = outbox.on_expiry(sent, now + 10, Late.drop)
    assert dropped[0].state == State.expired and dropped[0].reason == Reason.expired
    assert SendCancel("d1", e.id, Reason.expired) in fx
    played_late, fx = outbox.on_expiry(sent, now + 10, Late.play)
    assert played_late[0].state == State.sent and played_late[0].late is True
    assert [f.kind for f in fx if isinstance(f, LogEvent)] == ["late_play"]
    again, fx = outbox.on_expiry(played_late, now + 11, Late.play)
    assert fx == []  # counted once


def test_body_and_compose_failed():
    now = 0.0
    e = make_entry(1, now, body_pending=True)
    sent, _ = outbox.assign([e], [DeviceSlot("d1", True, 1, True)], now)
    filled, fx = outbox.on_body(sent[0], ["meds", "nine"], Source.live, 5000, now + 2)
    assert filled.utterance.words == ["meds", "nine"] and not filled.body_pending and filled.duration_ms == 5000
    assert fx[0] == SendBody("d1", e.id, ("meds", "nine"), Source.live)
    with pytest.raises(IllegalTransition):
        outbox.on_body(filled, ["x"], Source.live, 1, now + 3)
    failed, fx = outbox.on_compose_failed(sent[0], Reason.compose_failed, now + 2)
    assert failed.state == State.failed and failed.reason == Reason.compose_failed
    assert fx[0] == SendBody("d1", e.id, (), Source.sender, Reason.compose_failed)


def test_terminal_states_refuse_every_event():
    now = 0.0
    e = make_entry(1, now)
    cancelled, fx = outbox.cancel(e, Reason.cancelled_by_sender, now)
    assert cancelled.state == State.cancelled and fx[-1].state == State.cancelled
    for fn in (
        lambda: outbox.on_progress(cancelled, "d", Phase.cue, now),
        lambda: outbox.on_played(cancelled, "d", now),
        lambda: outbox.on_nack(cancelled, "d", Reason.hidden, now),
        lambda: outbox.cancel(cancelled, Reason.cancelled_by_wearer, now),
        lambda: outbox.on_body(cancelled, ["a"], Source.live, 1, now),
        lambda: outbox.on_compose_failed(cancelled, Reason.compose_failed, now),
    ):
        with pytest.raises(IllegalTransition):
            fn()


# --- the state machine ------------------------------------------------------


class OutboxMachine(RuleBasedStateMachine):
    CAP = 4
    WINDOW = 8.0

    @initialize()
    def setup(self):
        self.now = 1_000.0
        self.entries: list[OutboxEntry] = []
        self.devices = {"d1": DeviceSlot("d1", False, 2, True, 0), "d2": DeviceSlot("d2", False, 2, False, 1)}
        self.admitted: set[str] = set()
        self.counter = 0
        self.refusals: list[Refusal] = []
        self.late = Late.drop

    def _slots(self):
        return list(self.devices.values())

    @rule(words=WORDS, expires_in=st.one_of(st.none(), st.floats(1, 60)), pending=st.booleans())
    def submit(self, words, expires_in, pending):
        self.counter += 1
        e = make_entry(self.counter, self.now, words, expires_in=expires_in, body_pending=pending)
        r = outbox.admit(self.entries, e, self.CAP)
        if isinstance(r, Refusal):
            assert r.reason == Reason.queue_full
            assert outbox.active_count(self.entries) >= self.CAP
            self.refusals.append(r)
        else:
            self.entries.append(r[0])
            self.admitted.add(e.id)

    @rule(device=st.sampled_from(["d1", "d2"]), connected=st.booleans())
    def toggle_device(self, device, connected):
        self.devices[device] = replace(self.devices[device], connected=connected)
        if connected:
            self.entries = outbox.forgive(self.entries, device)
        else:
            self.entries, fx = outbox.on_device_gone(self.entries, device, self.now)

    @rule()
    def assign(self):
        self.entries, fx = outbox.assign(self.entries, self._slots(), self.now)
        for f in fx:
            if isinstance(f, SendOpen):
                assert self.devices[f.device].connected

    @rule(data=st.data(), phase=st.sampled_from(list(Phase)))
    def progress(self, data, phase):
        if not self.entries:
            return
        e = data.draw(st.sampled_from(self.entries))
        d = data.draw(st.sampled_from(["d1", "d2"]))
        self._apply(e, "progress", lambda: outbox.on_progress(e, d, phase, self.now))

    @rule(data=st.data())
    def played(self, data):
        if not self.entries:
            return
        e = data.draw(st.sampled_from(self.entries))
        d = data.draw(st.sampled_from(["d1", "d2"]))
        self._apply(e, "played", lambda: outbox.on_played(e, d, self.now, 100))

    @rule(data=st.data(), reason=st.sampled_from([Reason.hidden, Reason.muted, Reason.spec_mismatch, Reason.body_timeout]))
    def nack(self, data, reason):
        if not self.entries:
            return
        e = data.draw(st.sampled_from(self.entries))
        d = data.draw(st.sampled_from(["d1", "d2"]))
        self._apply(e, "nack", lambda: outbox.on_nack(e, d, reason, self.now))

    @rule(data=st.data())
    def cancel(self, data):
        if not self.entries:
            return
        e = data.draw(st.sampled_from(self.entries))
        self._apply(e, "cancel", lambda: outbox.cancel(e, Reason.cancelled_by_sender, self.now))

    @rule(data=st.data())
    def body(self, data):
        pending = [e for e in self.entries if e.body_pending and e.active]
        if not pending:
            return
        e = data.draw(st.sampled_from(pending))
        self._apply(e, "body", lambda: outbox.on_body(e, ["ok"], Source.live, 900, self.now))

    @rule(dt=st.floats(0.5, 20.0), late=st.sampled_from(list(Late)))
    def advance(self, dt, late):
        self.now += dt
        self.late = late
        before = list(self.entries)
        self.entries, fx = outbox.failover(self.entries, self.now, self.WINDOW)
        cancelled_ids = {f.id for f in fx if isinstance(f, SendCancel)}
        for b, a in zip(before, self.entries):
            if b != a:
                assert b.state == State.sent and a.state == State.pending
                assert a.device is None and a.reason == Reason.failover and b.device in a.tried
                assert a.id in cancelled_ids
        self.entries, fx = outbox.on_expiry(self.entries, self.now, late)

    def _apply(self, e, event, fn):
        try:
            ne, fx = fn()
        except IllegalTransition as exc:
            assert e.terminal, f"{event} raised on an active entry in {e.state}"
            assert exc.state == e.state
            return
        assert not e.terminal, f"{event} was accepted on a terminal entry"
        self.entries = [ne if x.id == e.id else x for x in self.entries]

    @invariant()
    def no_loss_no_duplication(self):
        ids = [e.id for e in self.entries]
        assert len(ids) == len(set(ids))
        assert set(ids) == self.admitted

    @invariant()
    def bounded(self):
        assert outbox.active_count(self.entries) <= self.CAP
        load = {d: 0 for d in self.devices}
        for e in self.entries:
            if e.state in (State.sent, State.playing):
                load[e.device] += 1
        for d, n in load.items():
            assert n <= self.devices[d].capacity

    @invariant()
    def states_are_consistent(self):
        for e in self.entries:
            if e.state == State.pending:
                assert e.device is None and e.sent_at is None
            elif e.state in (State.sent, State.playing):
                assert e.device is not None and e.sent_at is not None
                assert self.devices[e.device].connected, "an entry is held by a device that is gone"
            elif e.state in (State.failed, State.expired, State.cancelled):
                assert e.reason is not None, f"{e.state} without a reason"
            elif e.state == State.played:
                assert e.reason is None and e.played_at is not None

    @invariant()
    def every_refusal_has_a_reason(self):
        assert all(isinstance(r.reason, Reason) and r.message for r in self.refusals)


TestOutboxMachine = OutboxMachine.TestCase
TestOutboxMachine.settings = settings(max_examples=60, stateful_step_count=30, deadline=None,
                                      suppress_health_check=[HealthCheck.too_slow])


@given(st.integers(0, 12), st.integers(1, 6))
def test_counts_sum_to_entries(n, cap):
    entries = []
    for i in range(n):
        r = outbox.admit(entries, make_entry(i, 0.0), cap)
        if not isinstance(r, Refusal):
            entries.append(r[0])
    assert sum(outbox.counts(entries).values()) == len(entries) == min(n, cap)
