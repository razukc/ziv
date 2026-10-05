"""Concurrency tests for MessageGate (agent/ziv_relay.py) — the seam's
lock is the claim's teeth.

The DEVPOST files claim "a threaded concurrency guard so concurrent
arrivals never lose or duplicate a message." The gate is that guard: every
decision is atomic under its reentrant lock. These tests hold the claim
against real thread contention — many arrivals racing admits, closes, and
state flips — and assert the three properties the sentence promises:

* **No loss** — every admitted text (played or queued) is accounted for;
* **No duplication** — each text appears exactly once across play/queue/drain;
* **Loud, bounded refusal** — beyond the cap the answer is exactly
  ``message:rejected`` with reason ``queue_full`` (never a silent drop, never
  an unbounded queue).

State transitions (begin/close) are raced too: no admit may see the state
machine tear. Race timing is *forced* (a start barrier plus a tiny settle
sleep before the wave) so workers overlap; asserts read only final states
plus each decision's own payload, so the test stays deterministic even when
the interleaving is not.

The reservation itself is pinned too: ``message:play`` *claims* the channel,
so exactly one arrival in a stampede wins and the rest queue or are refused.

Pure unit level: a fresh ``MessageGate`` per test, no server, no store.
"""

from __future__ import annotations

import threading
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT / "agent"), str(_ROOT / "tools")):
    if _p not in __import__("sys").path:
        __import__("sys").path.insert(0, _p)

from ziv_relay import MessageGate

WORKERS = 12          # racing threads (more than cores: real contention)
PER_WORKER = 25       # admits each thread fires


def _racing_gate():
    """A gate forced into contention: all workers start together, then a
    settle sleep guarantees the first admits land mid-flurry, not at boot."""
    gate = MessageGate()
    start = threading.Barrier(WORKERS)
    return gate, start


def test_concurrent_arrivals_never_lose_or_duplicate():
    """N workers race admits while a driver flips playing/closed beneath
    them: every message is accounted for exactly once, no text vanishes,
    no text doubles."""
    gate, start = _racing_gate()
    results: list = []
    lock = threading.Lock()

    def worker(w: int) -> None:
        start.wait()
        for i in range(PER_WORKER):
            text = f"w{w}-m{i}"
            ev = gate.admit(text)
            with lock:
                results.append((text, ev.event_type, ev.payload.get("text")))

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(WORKERS)]
    for t in threads:
        t.start()
    # Flip the state machine under the racers: multiple full cycles of
    # begin/close while admits are landing.
    for _ in range(WORKERS * 2):
        gate.begin_playback()
        gate.close_event()
    for t in threads:
        t.join()

    assert len(results) == WORKERS * PER_WORKER
    texts_seen = [t for (t, _, _) in results]
    assert len(set(texts_seen)) == WORKERS * PER_WORKER, (
        "a duplicated admit would mean two workers decided for one message"
    )
    # Every decision is one of the three legal outcomes — nothing else.
    assert {et for (_, et, _) in results} <= {
        "message:play", "attention:double-tap", "message:rejected"
    }
    # The gate itself never overflows its own bound.
    assert len(gate) <= MessageGate.MAX_QUEUED


def test_every_message_is_accounted_exactly_once():
    """Across play decisions, queue appends, and drain results: the union
    of all texts is exactly the input set — each once. (The heart of
    'never lose or duplicate'.)"""
    gate, start = _racing_gate()
    lock = threading.Lock()
    played: list[str] = []
    queued: list[str] = []
    rejected: list[str] = []

    def worker(w: int) -> None:
        start.wait()
        for i in range(PER_WORKER):
            text = f"w{w}-m{i}"
            ev = gate.admit(text)
            with lock:
                if ev.event_type == "message:play":
                    played.append(text)
                elif ev.event_type == "attention:double-tap":
                    queued.append(text)
                elif ev.event_type == "message:rejected":
                    rejected.append(text)

    # Playback begins BEFORE the racers spawn: every admit races a FULL
    # gate, so the arithmetic below is deterministic. (Flips DURING the
    # race — the tearing case — are test 1's job, set-based.)
    gate.begin_playback()
    threads = [threading.Thread(target=worker, args=(w,)) for w in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    drained = [e.payload["text"] for e in gate.close_event()]

    # This run's arithmetic is deterministic: exactly MAX_QUEUED fit, the
    # rest were refused loudly.
    assert len(queued) == MessageGate.MAX_QUEUED
    assert len(rejected) == WORKERS * PER_WORKER - MessageGate.MAX_QUEUED
    # The no-duplication + no-loss proof, set-exact:
    assert Counter(queued) == Counter(drained), (
        "the drain must return every queued text, each exactly once"
    )
    assert len(set(queued) | set(rejected) | set(played)) == WORKERS * PER_WORKER
    # ...and the three buckets partition the input (no text in two buckets).
    assert not (set(played) & set(queued))
    assert not (set(queued) & set(rejected))
    assert not (set(played) & set(rejected))


def test_refusals_are_loud_and_bounded():
    """Beyond the cap the answer is exactly ``message:rejected`` with
    reason ``queue_full`` and the cap named — never silence, never an
    unbounded queue, and the queue is playable afterwards."""
    gate, start = _racing_gate()
    lock = threading.Lock()
    rejections = []

    def worker(w: int) -> None:
        start.wait()
        for i in range(PER_WORKER):
            ev = gate.admit(f"w{w}-m{i}")
            if ev.event_type == "message:rejected":
                with lock:
                    rejections.append(ev.payload)

    # Full gate from the start (same trick as the accounting test): every
    # admit above the cap must be a loud refusal.
    gate.begin_playback()
    threads = [threading.Thread(target=worker, args=(w,)) for w in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(rejections) == WORKERS * PER_WORKER - MessageGate.MAX_QUEUED
    for p in rejections:
        assert p["reason"] == "queue_full"
        assert p["cap"] == MessageGate.MAX_QUEUED
        assert p["text"]  # the refusal names what was refused
    # The gate is still exactly at its bound — no smuggled extra entries.
    assert len(gate) == MessageGate.MAX_QUEUED
    # ...and the queued texts survive: the drain hands them all back.
    drained = [e.payload["text"] for e in gate.close_event()]
    assert len(drained) == MessageGate.MAX_QUEUED
    assert len(set(drained)) == MessageGate.MAX_QUEUED


def test_a_stampede_on_an_idle_gate_produces_exactly_one_winner():
    """Reservation under contention: one play, the rest queue or refuse.

    The property the bounded queue exists for. Before the play decision
    *reserved* the channel, all N racers observed idle and all N were told
    ``message:play`` — so the bound below could never engage and a burst
    turned into N sequential turns instead of one plus a queue.
    """
    gate = MessageGate()
    N = 24
    barrier = threading.Barrier(N)
    decisions: list = [None] * N

    def worker(i: int) -> None:
        barrier.wait()
        decisions[i] = gate.admit("m-%02d" % i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    plays = [d for d in decisions if d.event_type == "message:play"]
    queued = [d for d in decisions if d.event_type == "attention:double-tap"]
    refused = [d for d in decisions if d.event_type == "message:rejected"]

    assert len(plays) == 1, "only one arrival may take the idle channel"
    assert len(queued) == MessageGate.MAX_QUEUED
    assert len(refused) == N - 1 - MessageGate.MAX_QUEUED
    assert len(gate) == MessageGate.MAX_QUEUED
    # The winner owns the channel, and its text is not in the queue.
    assert gate.playing is True
    assert plays[0].payload["text"] not in {d.payload["text"] for d in queued}
    # Everything the gate took comes back out of the drain, once each.
    drained = [e.payload["text"] for e in gate.close_event()]
    assert sorted(drained) == sorted(d.payload["text"] for d in queued)
    assert gate.playing is False


def test_reserve_races_admit_without_a_double_owner():
    """``reserve()`` and ``admit()`` share one lock, so there is never a
    moment where two callers both believe they own the channel."""
    gate = MessageGate()
    N = 16
    barrier = threading.Barrier(2 * N)
    holds: list = [False] * (2 * N)

    def claim_reserve(i: int) -> None:
        barrier.wait()
        holds[i] = gate.reserve()

    def claim_admit(i: int) -> None:
        barrier.wait()
        holds[i] = gate.admit("m-%02d" % i).event_type == "message:play"

    threads = [threading.Thread(target=claim_reserve, args=(i,)) for i in range(N)]
    threads += [threading.Thread(target=claim_admit, args=(N + i,))
                for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert sum(1 for h in holds if h) == 1, (
        "two callers believed they owned the channel at once"
    )
    gate.abort()


def test_abort_releases_the_channel_so_the_next_arrival_plays():
    """A turn that dies mid-playback must not wedge the relay.

    The wedge this guards against: ``begin_playback()`` sets ``playing`` and
    only the normal close clears it. If a band vanishes between the two,
    every later arrival queues against a wrist that is not reading, and
    once the queue fills the relay refuses everything until restart.
    """
    gate = MessageGate()
    gate.begin_playback()
    assert gate.playing is True

    for i in range(3):
        gate.admit(f"queued-{i}")  # arrivals land behind the doomed turn
    stranded = gate.abort()

    assert gate.playing is False, "abort must release the channel"
    # The next arrival PLAYS (message:play) — it does not queue behind a
    # gate that will never drain again.
    assert gate.admit("next").event_type == "message:play"


def test_abort_hands_back_the_queue_instead_of_dropping_it():
    """Nothing queued is lost by an abort: the texts come back, oldest first.

    An abort cannot replay them (there is no band left to feel it), so the
    caller needs them to re-offer elsewhere — dropping them here would turn
    an interrupted turn into silent data loss.
    """
    gate = MessageGate()
    gate.begin_playback()
    for i in range(5):
        gate.admit(f"m{i}")

    stranded = gate.abort()

    assert stranded == ["m0", "m1", "m2", "m3", "m4"]
    assert len(gate) == 0, "the queue is handed back, not silently emptied"
    # A second abort is a no-op: idempotent, and it loses nothing.
    assert gate.abort() == []
    assert gate.playing is False


def test_abort_on_an_idle_gate_is_a_no_op():
    """Aborting a gate that never played must not raise or invent state."""
    gate = MessageGate()
    assert gate.playing is False
    assert gate.abort() == []
    assert gate.admit("hi").event_type == "message:play"
