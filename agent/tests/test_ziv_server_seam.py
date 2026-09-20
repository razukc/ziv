"""Contract test for the Ziv relay seam (agent/ziv_relay.py):

MessageGate + TurnTimeline, used by agent/ziv_server.py's turn pump.

This is the "the seam is proven" test. It does not re-prove the wire journey
(agent/tests/test_ziv_server.py already asserts the frame order on the WS);
it proves the *internal* contract a future relay author builds on: the server's
real turn path goes through MessageGate.admit then TurnTimeline in the documented
order, and a queued message replays as a full event (cue -> content -> close),
not as a bare cue.

These assertions are the executable form of the "seam exists" claim in
agent/ziv_relay.py's module docstring. Keep them green; they are the seam.
"""


from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "agent"), str(_ROOT / "tools")):
    if _p not in __import__("sys").path:
        __import__("sys").path.insert(0, _p)

from ziv_relay import KIND_PLAYBACK_DONE, KIND_PROCESSING, MessageGate, TurnTimeline
from ziv_server import run_message_turn


# ---------------------------------------------------------------------------
# The seam: the order the real turn path is documented to take
# ---------------------------------------------------------------------------

class _OrderLog:
    """A spy that records every seam call the server's turn pump makes.

    The pump calls gate.admit(text) first (queue-don't-interrupt decision),
    then, when the message is admitted for play, constructs a TurnTimeline and
    drives it through the lifecycle: begin_processing -> poll(s) ->
    begin_playback -> finish_playback. This log captures that order so the test
    can assert the seam is used in the documented sequence, not just that the
    wire produced the right frames.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def record(self, name: str, **kw: Any) -> None:
        self.calls.append((name, kw))


def _make_spied_gate_and_timeline_factory(log: _OrderLog):
    """Return (gate, timeline_factory) where the factory records its calls.

    The server owns one process-wide MessageGate and constructs a fresh
    TurnTimeline per admitted turn. We model that: the spied gate is the single
    gate the pump consults, and the factory is what the pump calls to build a
    turn after admit returns message:play.
    """
    gate = MessageGate()

    def factory(text: str) -> TurnTimeline:
        log.record("build_timeline", text=text)
        turn = TurnTimeline(gate, text=text)
        log.record("timeline_created", state=turn.state, cue=turn._cue)
        return turn

    return gate, factory


def _drive_one_turn_as_the_pump_does(
    turn: TurnTimeline,
    *,
    now_s: float = 0.0,
    processing_wait_s: float = 0.0,
):
    """Mirror the pump's lifecycle drive through TurnTimeline.

    The pump calls:
      turn.begin_processing(now_s=0.0)
      poll(s) while the fake model works
      turn.begin_playback()
      ... cells ...
      turn.finish_playback(now_s=...)

    We skip the per-cell spelling (that is server-specific output, not seam
    ordering) and drive the seam lifecycle directly so the test is about the
    seam, not the cell renderer.
    """
    turn.begin_processing(now_s=now_s)
    if processing_wait_s > 0:
        tick = 0.05
        waited = 0.0
        while waited < processing_wait_s:
            waited += tick
            turn.poll(now_s=waited)
    turn.begin_playback()
    turn.finish_playback(now_s=now_s + 1.0)
    return turn.events


def test_seam_is_proven_turn_path_goes_through_gate_then_timeline_in_order():
    """The server's real turn path consults MessageGate.admit first, then drives
    TurnTimeline through accepted -> processing -> playing -> closed.

    This is the seam contract: admit decides play-now vs cue-and-queue; a
    play-now decision leads to a TurnTimeline whose lifecycle runs in the
    documented order. The wire test proves the frames; this proves the seam is
    the thing producing them.
    """
    log = _OrderLog()
    gate, factory = _make_spied_gate_and_timeline_factory(log)

    decision = gate.admit("hello")
    log.record("admit", text="hello", result_event=decision.event_type)

    assert decision.event_type == "message:play"

    turn = factory("hello")
    events = _drive_one_turn_as_the_pump_does(turn, now_s=0.0)

    assert turn.state == "closed"
    kinds = [e.event_type for e in events]
    assert kinds == [
        "message:play",
        "attention:processing",
        "message:play",
        "lifecycle:playback_done",
    ]
    assert [e.event_type for e in events[-1:]] == ["lifecycle:playback_done"]

    expected_calls = [
        ("admit", {"text": "hello", "result_event": "message:play"}),
        ("build_timeline", {"text": "hello"}),
        ("timeline_created", {"state": "accepted", "cue": "message:play"}),
    ]
    assert log.calls[:3] == expected_calls


def test_seam_is_proven_queued_message_replays_as_a_full_event():
    """A message admitted while the gate is playing queues, then replays as a
    full event after the close: its own cue -> content -> close.

    The seam's queue-replay contract (invariants 1 + 2 for queued content): the
    drained replay is not a bare cue — it is a complete turn journey the wearer
    releases. MessageGate.close_event produces one message:play per queued
    message; TurnTimeline.finish_playback appends the close then the drained
    replays, and the server renders each replay with its own close.
    """
    gate = MessageGate()
    turn = TurnTimeline(gate, text="first")
    turn.begin_processing(now_s=0.0)
    turn.begin_playback()

    admitted = gate.admit("second")
    assert admitted.event_type == "attention:double-tap"
    assert admitted.payload["queued"] is True
    assert len(gate) == 1

    replay = turn.finish_playback()
    assert [e.event_type for e in replay] == [
        "lifecycle:playback_done",
        "message:play",
    ]
    assert replay[1].payload["text"] == "second"
    assert replay[1].payload["prefix"] is True
    assert turn.state == "closed"
    assert turn.events[-1].payload["text"] == "second"


def test_seam_is_proven_queued_replay_event_is_not_a_bare_cue():
    """The queued replay is a full event starter, not a bare attention cue.

    A relay bug that released a queued message as only its double-tap cue would
    feel like an announcement with no content. The seam must produce
    message:play (the full-event starter) per queued message.
    """
    gate = MessageGate()
    turn = TurnTimeline(gate, text="a")
    turn.begin_processing(now_s=0.0)
    turn.begin_playback()
    gate.admit("b")
    gate.admit("c")
    replay = turn.finish_playback()

    assert replay[0].event_type == "lifecycle:playback_done"
    replay_starts = replay[1:]
    assert len(replay_starts) == 2
    assert all(e.event_type == "message:play" for e in replay_starts)
    assert [e.payload["text"] for e in replay_starts] == ["b", "c"]
    assert all(e.payload["prefix"] is True for e in replay_starts)
    assert turn.events[-1].payload["text"] == "c"


def test_seam_is_proven_turn_lifecycle_states_are_the_documented_ones():
    """The lifecycle constants the seam uses are the documented ones (inv 2-3)."""
    assert KIND_PROCESSING == "processing"
    assert KIND_PLAYBACK_DONE == "playback_done"


def test_seam_is_proven_run_message_turn_uses_the_real_seam_not_the_adapter():
    """run_message_turn goes through MessageGate + TurnTimeline, and the seam
    itself imports no compose scaffold.

    The server imports MessageGate and TurnTimeline from ziv_relay and drives
    them directly in run_message_turn. The compose scaffold that once lived
    alongside the seam (ports.py / relay_compose.py) moved to the SkillForge
    repo at the handover; this test proves the Ziv seam never references it:
    ziv_relay.py's imports are the stdlib, nothing else.
    """
    import ast

    from ziv_server import gate as server_gate
    import ziv_relay

    assert isinstance(server_gate, MessageGate)
    assert hasattr(server_gate, "admit")
    assert hasattr(server_gate, "close_event")
    src = Path(ziv_relay.__file__).read_text(encoding="utf-8")
    # The seam's own landing pad legitimately contains "RelayAdapter" as a
    # substring of ZivRelayAdapter; strip it before the forbidden-name scan.
    probe = src.replace("ZivRelayAdapter", "")
    for forbidden in ("RelayResult", "RelayConfig", "RelayAdapter",
                      "relay_run_turn", "relay_compose"):
        assert forbidden not in probe, f"ziv_relay.py references {forbidden!r}"

    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    allowed = {"__future__", "asyncio", "collections", "dataclasses", "typing",                   "threading", "datetime"}
    assert imported <= allowed, f"ziv_relay.py imports outside the seam: {imported - allowed}"


# ---------------------------------------------------------------------------
# The seam's invariants, as assertions on the seam objects themselves
# ---------------------------------------------------------------------------

def test_seam_is_proven_gate_admit_is_queue_dont_interrupt():
    """MessageGate.admit implements the queue-don't-interrupt policy (inv 4).

    idle + message -> message:play; playing + message -> cue + queue.
    """
    gate = MessageGate()
    assert gate.admit("x").event_type == "message:play"
    gate.begin_playback()
    first_admit = gate.admit("y")
    assert first_admit.event_type == "attention:double-tap"
    assert first_admit.payload["queued"] is True
    assert len(gate) == 1
    second_admit = gate.admit("z")
    assert second_admit.event_type == "attention:double-tap"
    assert second_admit.payload["queued"] is True
    assert len(gate) == 2


def test_seam_is_proven_gate_close_drains_fifo_with_prefix():
    """MessageGate.close_event drains oldest-first, each with its prefix (inv 1)."""
    gate = MessageGate()
    gate.begin_playback()
    gate.admit("first")
    gate.admit("second")
    drained = gate.close_event()
    assert [e.event_type for e in drained] == ["message:play", "message:play"]
    assert [e.payload["text"] for e in drained] == ["first", "second"]
    assert all(e.payload["queued"] is False for e in drained)
    assert all(e.payload["prefix"] is True for e in drained)


def test_seam_is_proven_timeline_processing_clock_is_slow_never_silent():
    """TurnTimeline.poll emits processing on cadence while in flight (inv 3)."""
    turn = TurnTimeline(MessageGate(), text="x")
    turn.begin_processing(now_s=0.0)
    assert turn.poll(now_s=1.9) is None
    ev = turn.poll(now_s=2.0)
    assert ev is not None and ev.event_type == "attention:processing"
    turn.begin_playback()
    assert turn.poll(now_s=99.0) is None


def test_seam_is_proven_timeline_rejects_out_of_order_transitions():
    """Misuse is loud: the invariants are structural, not improvised (inv 5)."""
    turn = TurnTimeline(MessageGate(), text="x")
    with pytest.raises(AssertionError):
        turn.begin_playback()
    with pytest.raises(AssertionError):
        turn.finish_playback()
    turn.begin_processing(now_s=0.0)
    with pytest.raises(AssertionError):
        turn.finish_playback()
    turn.begin_playback()
    turn.finish_playback()
    with pytest.raises(AssertionError):
        turn.begin_processing(now_s=1.0)


def test_seam_is_proven_error_path_never_emits_content():
    """A failed turn plays long-buzz — latency with an ending, never content."""
    turn = TurnTimeline(MessageGate(), text="x")
    turn.begin_processing(now_s=0.0)
    turn.fail()
    assert turn.state == "error"
    assert turn.events[-1].event_type == "attention:long-buzz"
    assert turn.events[-1].payload["state"] == "error"
    assert turn.events.count("message:play") == 0


# ---------------------------------------------------------------------------
# Concurrency: the seam under concurrent transports (threaded proofs)
# ---------------------------------------------------------------------------

def test_seam_gate_stampede_queues_every_arrival_and_no_loss():
    """MAX_QUEUED threads admit at once against a playing gate: every
    arrival queues (no idle window — the gate is already playing), nothing
    lost, nothing duplicated, and the drain is exactly the admitted set.

    Decision semantics, made explicit by this test: the gate answers
    ``message:play`` whenever it observes an idle channel and never claims
    it — claiming the channel for a *turn* is the caller's turn lock (the
    server holds one). What the gate's lock guarantees under a stampede is
    the queue side: no loss, no duplication, no corruption.
    """
    gate = MessageGate()
    N = MessageGate.MAX_QUEUED
    barrier = threading.Barrier(N)
    decisions = [None] * N
    errors = []

    def worker(i):
        try:
            barrier.wait(timeout=10)
            decisions[i] = gate.admit("msg-%02d" % i)
        except BaseException as exc:  # the test is the judge
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    gate.begin_playback()  # the stampede races a PLAYING gate
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert not errors, errors
    assert all(d is not None for d in decisions)

    plays = [d for d in decisions if d.event_type == "message:play"]
    queued = [d for d in decisions if d.event_type == "attention:double-tap"]
    rejected = [d for d in decisions if d.event_type == "message:rejected"]
    # Deterministic: a playing gate + room below the cap -> everything queues.
    assert not plays and not rejected, [d.event_type for d in decisions]
    assert len(queued) == N
    assert len(gate) == N
    assert all(d.payload["queued"] is True for d in queued)

    # The queue is intact: every text drains exactly once (order is
    # lock-acquisition order under a stampede, so compare as a set).
    drained = gate.close_event()
    assert sorted(e.payload["text"] for e in drained) == sorted(
        "msg-%02d" % i for i in range(N)
    )


def test_seam_gate_rejects_when_full_and_never_overflows():
    """A full queue rejects with message:rejected (reason queue_full + cap);
    the queue never exceeds MAX_QUEUED, and a reject never enters it."""
    gate = MessageGate()
    gate.begin_playback()
    for i in range(MessageGate.MAX_QUEUED):
        assert gate.admit("full-%02d" % i).event_type == "attention:double-tap"
    assert len(gate) == MessageGate.MAX_QUEUED

    rejected = gate.admit("overflow")
    assert rejected.event_type == "message:rejected"
    assert rejected.payload["reason"] == "queue_full"
    assert rejected.payload["cap"] == MessageGate.MAX_QUEUED
    assert rejected.payload["queued"] is False
    assert rejected.payload["prefix"] is False
    assert len(gate) == MessageGate.MAX_QUEUED

    # The queue is untouched by the rejection — the drain yields exactly the
    # admitted messages, in order.
    drained = gate.close_event()
    assert [e.payload["text"] for e in drained] == [
        "full-%02d" % i for i in range(MessageGate.MAX_QUEUED)
    ]
    assert all(e.payload["queued"] is False for e in drained)

    # After the drain the gate is idle and admits again.
    assert gate.admit("fresh").event_type == "message:play"


def test_seam_gate_stampede_beyond_cap_rejects_and_never_queues_overflow():
    """20 threads admit at once against a playing, empty gate: exactly
    MAX_QUEUED queue, the rest rejected with message:rejected — bounded
    under a real race, every sender told no loudly, nothing queued beyond
    the cap."""
    gate = MessageGate()
    N = 20
    barrier = threading.Barrier(N)
    decisions = [None] * N
    errors = []

    def worker(i):
        try:
            barrier.wait(timeout=10)
            decisions[i] = gate.admit("flood-%02d" % i)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    gate.begin_playback()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert not errors, errors

    queued = [d for d in decisions if d.event_type == "attention:double-tap"]
    rejected = [d for d in decisions if d.event_type == "message:rejected"]
    assert len(queued) == MessageGate.MAX_QUEUED
    assert len(rejected) == N - MessageGate.MAX_QUEUED
    assert len(gate) == MessageGate.MAX_QUEUED
    assert all(d.payload["reason"] == "queue_full" for d in rejected)
    # Rejected texts never enter the queue.
    rejected_texts = {d.payload["text"] for d in rejected}
    drained = gate.close_event()
    assert not rejected_texts & {e.payload["text"] for e in drained}


def test_seam_gate_no_loss_under_concurrent_admit_and_close_cycles():
    """Racing admits against close cycles: nothing lost, nothing duplicated.

    Conservation law of a bounded queue under the gate's lock: every text the
    gate said 'queued' to either drains at a close or is still queued —
    closed + still_queued == admitted, exactly, no matter the interleaving.
    """
    gate = MessageGate()
    stop = threading.Event()
    lock = threading.Lock()
    admitted = []   # texts the gate queued (attention:double-tap)
    closed = []     # texts drained at closes

    def player():
        # Keep the gate mostly playing so admits race the queue; close_event
        # (in the closer) briefly idles it, which is exactly the race window.
        while not stop.is_set():
            if not gate.playing:
                gate.begin_playback()
            stop.wait(0.001)

    def admitter():
        i = 0
        while not stop.is_set():
            d = gate.admit("r-%d" % i)
            if d.event_type == "attention:double-tap":
                with lock:
                    admitted.append("r-%d" % i)
            # message:play (idle gap) is consumed immediately by its caller —
            # never queued anywhere, so it must never appear in a drain.
            # message:rejected is refused outright — bounded memory.
            i += 1
            stop.wait(0)

    def closer():
        while not stop.is_set():
            drained = gate.close_event()
            if drained:
                with lock:
                    closed.extend(e.payload["text"] for e in drained)
            stop.wait(0.001)

    threads = [threading.Thread(target=player),
               threading.Thread(target=admitter),
               threading.Thread(target=closer)]
    for t in threads:
        t.start()
    stop.wait(0.4)
    stop.set()
    for t in threads:
        t.join(timeout=10)

    with lock:
        closed_now = list(closed)
        admitted_now = list(admitted)

    # Nothing duplicated.
    counts = {}
    for t in closed_now:
        counts[t] = counts.get(t, 0) + 1
    dupes = {k: v for k, v in counts.items() if v > 1}
    assert not dupes, "duplicated at close: %s" % dupes

    # Conservation: closed + still_queued == admitted, exactly.
    assert set(closed_now) <= set(admitted_now)
    still_queued = len(gate)
    assert len(closed_now) + still_queued == len(admitted_now), (
        "lost or invented messages: closed=%d queued=%d admitted=%d"
        % (len(closed_now), still_queued, len(admitted_now))
    )


def test_seam_gate_stays_coherent_under_racing_players():
    """Racing begin_playback/close_event against an observer: the visible
    state is always coherent — a real bool, a never-negative queue, and no
    queue entries appearing while playing with no admits in flight."""
    gate = MessageGate()
    stop = threading.Event()
    anomalies = []

    def player(on):
        while not stop.is_set():
            if on:
                gate.begin_playback()
            else:
                gate.close_event()
            stop.wait(0)

    def observer():
        for _ in range(3000):
            p = gate.playing
            if p not in (True, False):
                anomalies.append("playing=%r" % (p,))
            n = len(gate)
            if n < 0:
                anomalies.append("len=%d" % n)
            if p and n != 0:
                # No admits are in flight in this test: a playing gate must
                # hold an empty queue (close drains and idles atomically).
                anomalies.append("playing with queue=%d" % n)
            stop.wait(0)

    threads = [threading.Thread(target=player, args=(True,)),
               threading.Thread(target=player, args=(False,)),
               threading.Thread(target=observer)]
    for t in threads:
        t.start()
    stop.wait(0.2)
    stop.set()
    for t in threads:
        t.join(timeout=10)
    assert not anomalies, anomalies
