"""ziv.core.outbox — the per-wearer outbox state machine (docs/ARCHITECTURE.md §4.1).

    pending ──assign──▶ sent ──progress──▶ playing ──played──▶ played
       ▲                 │  ╲                 │  ╲
       │   failover /    │   nack             │   nack ──▶ failed
       └── device_gone ──┘                    │
                                   device_gone┘
    pending|sent ──expiry──▶ expired      pending|sent|playing ──cancel──▶ cancelled

Every function is pure: it takes entries, an event and ``now`` and returns the
new entries plus effects. An illegal transition raises ``IllegalTransition``;
a refusal is a value with a ``Reason``. The adapters decide what to do with
both. Entries are never dropped from the slice: a caller gets back exactly
the ids it passed in.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Union

from ziv.wire import Late, Phase, Reason, Source, State, Utterance

from .model import ACTIVE_STATES, OutboxEntry, Refusal

# --- effects ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SendOpen:
    device: str
    utterance: Utterance


@dataclass(frozen=True, slots=True)
class SendBody:
    device: str
    id: str
    words: tuple[str, ...]
    source: Source
    error: Reason | None = None


@dataclass(frozen=True, slots=True)
class SendCancel:
    device: str
    id: str
    reason: Reason


@dataclass(frozen=True, slots=True)
class NotifySender:
    """The entry reached a state the sender should learn about."""

    id: str
    state: State
    reason: Reason | None = None


@dataclass(frozen=True, slots=True)
class LogEvent:
    """Content-free: a kind, an optional reason and counts. Never words."""

    kind: str
    wearer: str
    reason: Reason | None = None
    counts: Mapping[str, int] = field(default_factory=dict)


Effect = Union[SendOpen, SendBody, SendCancel, NotifySender, LogEvent]


class IllegalTransition(Exception):
    """An event that the entry's state does not accept."""

    def __init__(self, entry_id: str, state: State, event: str) -> None:
        super().__init__(f"{event} is not legal in state {state}")
        self.entry_id = entry_id
        self.state = state
        self.event = event


@dataclass(frozen=True, slots=True)
class DeviceSlot:
    """What assignment needs to know about an enrolled device."""

    id: str
    connected: bool
    capacity: int
    primary: bool = False
    order: int = 0


# --- helpers ----------------------------------------------------------------


def active_count(entries: Iterable[OutboxEntry]) -> int:
    return sum(1 for e in entries if e.state in ACTIVE_STATES)


def counts(entries: Iterable[OutboxEntry]) -> dict[str, int]:
    out = {str(s): 0 for s in State}
    for e in entries:
        out[str(e.state)] += 1
    return out


def _replace_in(entries: Sequence[OutboxEntry], changed: Mapping[str, OutboxEntry]) -> list[OutboxEntry]:
    return [changed.get(e.id, e) for e in entries]


def _require(entry: OutboxEntry, event: str, *states: State) -> None:
    if entry.state not in states:
        raise IllegalTransition(entry.id, entry.state, event)


# --- transitions ------------------------------------------------------------


def check_cap(entries: Iterable[OutboxEntry], cap: int) -> Refusal | None:
    n = active_count(entries)
    if n >= cap:
        return Refusal(
            Reason.queue_full,
            f"{n} utterances are waiting or playing; the cap is {cap}",
            {"active": n, "cap": cap},
        )
    return None


def admit(
    entries: Sequence[OutboxEntry], entry: OutboxEntry, cap: int
) -> Refusal | tuple[OutboxEntry, list[Effect]]:
    """Admit ``entry`` as pending unless the wearer's active cap is reached."""
    if any(e.id == entry.id for e in entries):
        return Refusal(Reason.conflict, "an utterance with this id already exists", {"id": 1})
    refusal = check_cap(entries, cap)
    if refusal is not None:
        return refusal
    admitted = entry.with_(state=State.pending, device=None)
    return admitted, [
        LogEvent("admitted", entry.wearer, counts={"words": len(entry.utterance.words),
                                                   "duration_ms": entry.duration_ms,
                                                   "budget_ms": entry.budget_ms}),
    ]


def assign(
    entries: Sequence[OutboxEntry], devices: Sequence[DeviceSlot], now: float
) -> tuple[list[OutboxEntry], list[Effect]]:
    """Hand pending entries to connected devices with capacity, oldest first,
    primary first. A device the entry already timed out on is skipped until it
    says hello again."""
    load: dict[str, int] = {d.id: 0 for d in devices}
    for e in entries:
        if e.device in load and e.state in (State.sent, State.playing):
            load[e.device] += 1
    changed: dict[str, OutboxEntry] = {}
    effects: list[Effect] = []
    for e in sorted(entries, key=lambda x: (x.created, x.id)):
        if e.state != State.pending:
            continue
        nb = e.not_before_at()
        if nb is not None and nb > now:
            continue
        candidates = [
            d for d in devices
            if d.connected and d.id not in e.tried and load[d.id] < d.capacity
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda d: (not d.primary, d.order, d.id))
        target = candidates[0]
        load[target.id] += 1
        changed[e.id] = e.with_(state=State.sent, device=target.id, sent_at=now, updated=now, reason=None)
        effects.append(SendOpen(target.id, e.utterance))
        effects.append(LogEvent("sent", e.wearer, counts={"attempt": len(e.tried) + 1}))
    return _replace_in(entries, changed), effects


def on_progress(entry: OutboxEntry, device: str, phase: Phase, now: float) -> tuple[OutboxEntry, list[Effect]]:
    _require(entry, "progress", State.sent, State.playing, State.pending)
    if entry.device != device:
        # a device we handed off from started it anyway: a duplicate, which the
        # rule prefers to a loss, and which the log records
        return entry, [LogEvent("duplicate_play", entry.wearer, counts={"phase_cue": int(phase == Phase.cue)})]
    if entry.state == State.sent:
        return entry.with_(state=State.playing, updated=now), [LogEvent("playing", entry.wearer)]
    return entry.with_(updated=now), []


def on_played(
    entry: OutboxEntry, device: str, now: float, played_ms: int | None = None
) -> tuple[OutboxEntry, list[Effect]]:
    _require(entry, "played", State.sent, State.playing, State.pending)
    if entry.device != device:
        return entry, [LogEvent("duplicate_play", entry.wearer, counts={"close": 1})]
    played = entry.with_(state=State.played, updated=now, played_at=now, played_ms=played_ms, reason=None)
    c = {"played_ms": played_ms} if played_ms is not None else {}
    return played, [LogEvent("played", entry.wearer, counts=c), NotifySender(entry.id, State.played)]


#: Nack reasons that say "not now, not here" rather than "never": the entry
#: returns to pending and the device that refused is skipped until its next hello.
REQUEUE_ON_NACK: frozenset[Reason] = frozenset({Reason.hidden, Reason.muted, Reason.queue_full})


def on_nack(entry: OutboxEntry, device: str, reason: Reason, now: float) -> tuple[OutboxEntry, list[Effect]]:
    """A device refused an entry it was handed. ``hidden``, ``muted`` and
    ``queue_full`` are conditions of that device at that moment: the entry goes
    back to pending with the reason recorded and the device in ``tried``, so
    the next assignment prefers another device or waits for this one's next
    hello (which forgives it). Every other reason (``body_timeout``,
    ``spec_mismatch``, ``expired``, ``cancelled_by_wearer`` ...) is final: the
    entry fails and the sender learns why."""
    _require(entry, "nack", State.sent, State.playing, State.pending)
    if entry.device != device:
        return entry, [LogEvent("stale_nack", entry.wearer, reason)]
    if reason in REQUEUE_ON_NACK:
        requeued = entry.with_(state=State.pending, device=None, sent_at=None, updated=now,
                               reason=reason, tried=entry.tried | {device})
        return requeued, [LogEvent("nack_requeued", entry.wearer, reason, {"tried": len(requeued.tried)})]
    failed = entry.with_(state=State.failed, updated=now, reason=reason)
    return failed, [LogEvent("failed", entry.wearer, reason), NotifySender(entry.id, State.failed, reason)]


def on_device_gone(entries: Sequence[OutboxEntry], device: str, now: float) -> tuple[list[OutboxEntry], list[Effect]]:
    """Everything the device held goes back to pending for the next device (or
    this one, when it returns and says hello)."""
    changed: dict[str, OutboxEntry] = {}
    for e in entries:
        if e.device == device and e.state in (State.sent, State.playing):
            changed[e.id] = e.with_(state=State.pending, device=None, sent_at=None,
                                    updated=now, reason=Reason.device_gone)
    effects: list[Effect] = []
    if changed:
        wearer = next(iter(changed.values())).wearer
        effects.append(LogEvent("device_gone", wearer, Reason.device_gone, {"requeued": len(changed)}))
    return _replace_in(entries, changed), effects


def on_expiry(entries: Sequence[OutboxEntry], now: float, late_policy: Late) -> tuple[list[OutboxEntry], list[Effect]]:
    """Apply ``expires`` to entries that have not started playing. ``drop``
    expires them (and recalls them from a device); ``play`` marks them late
    once and lets them play with the late tail."""
    changed: dict[str, OutboxEntry] = {}
    effects: list[Effect] = []
    for e in entries:
        if e.state not in (State.pending, State.sent):
            continue
        exp = e.expires_at()
        if exp is None or exp > now:
            continue
        if late_policy == Late.play:
            if not e.late:
                changed[e.id] = e.with_(late=True, updated=now)
                effects.append(LogEvent("late_play", e.wearer, Reason.expired))
            continue
        if e.device is not None:
            effects.append(SendCancel(e.device, e.id, Reason.expired))
        changed[e.id] = e.with_(state=State.expired, device=None, updated=now, reason=Reason.expired)
        effects.append(LogEvent("expired", e.wearer, Reason.expired))
        effects.append(NotifySender(e.id, State.expired, Reason.expired))
    return _replace_in(entries, changed), effects


def on_body(
    entry: OutboxEntry, words: Sequence[str], source: Source, duration_ms: int, now: float
) -> tuple[OutboxEntry, list[Effect]]:
    """The composer finished: fill the words of a ``body_pending`` utterance."""
    _require(entry, "body", State.pending, State.sent, State.playing)
    if not entry.utterance.body_pending:
        raise IllegalTransition(entry.id, entry.state, "body (not pending)")
    utt = entry.utterance.model_copy(update={"words": list(words), "body_pending": False, "source": source})
    filled = entry.with_(utterance=utt, duration_ms=duration_ms, updated=now)
    effects: list[Effect] = [LogEvent("body", entry.wearer, counts={"words": len(words), "duration_ms": duration_ms})]
    if entry.device is not None:
        effects.insert(0, SendBody(entry.device, entry.id, tuple(words), source))
    return filled, effects


def on_compose_failed(entry: OutboxEntry, reason: Reason, now: float) -> tuple[OutboxEntry, list[Effect]]:
    """The body never came: the entry fails and a device holding it plays the error."""
    _require(entry, "compose_failed", State.pending, State.sent, State.playing)
    failed = entry.with_(state=State.failed, updated=now, reason=reason)
    effects: list[Effect] = [LogEvent("failed", entry.wearer, reason), NotifySender(entry.id, State.failed, reason)]
    if entry.device is not None:
        effects.insert(0, SendBody(entry.device, entry.id, (), entry.utterance.source, reason))
    return failed, effects


def cancel(entry: OutboxEntry, reason: Reason, now: float) -> tuple[OutboxEntry, list[Effect]]:
    _require(entry, "cancel", State.pending, State.sent, State.playing)
    effects: list[Effect] = []
    if entry.device is not None:
        effects.append(SendCancel(entry.device, entry.id, reason))
    cancelled = entry.with_(state=State.cancelled, updated=now, reason=reason)
    effects.append(LogEvent("cancelled", entry.wearer, reason))
    effects.append(NotifySender(entry.id, State.cancelled, reason))
    return cancelled, effects


def failover(
    entries: Sequence[OutboxEntry], now: float, handoff_window_s: float
) -> tuple[list[OutboxEntry], list[Effect]]:
    """A device that was handed an entry and never reported its cue within the
    window loses it: the entry returns to pending with a reason, the device is
    told to cancel, and assignment will skip that device until it says hello."""
    changed: dict[str, OutboxEntry] = {}
    effects: list[Effect] = []
    for e in entries:
        if e.state != State.sent or e.sent_at is None or e.device is None:
            continue
        if e.sent_at + handoff_window_s > now:
            continue
        effects.append(SendCancel(e.device, e.id, Reason.failover))
        changed[e.id] = e.with_(state=State.pending, device=None, sent_at=None, updated=now,
                                reason=Reason.failover, tried=e.tried | {e.device})
        effects.append(LogEvent("failover", e.wearer, Reason.failover, {"tried": len(e.tried) + 1}))
    return _replace_in(entries, changed), effects


def forgive(entries: Sequence[OutboxEntry], device: str) -> list[OutboxEntry]:
    """A device said hello again: it may be offered what it once timed out on."""
    changed = {e.id: e.with_(tried=e.tried - {device}) for e in entries if device in e.tried}
    return _replace_in(entries, changed)


def acknowledge_hello(
    entries: Sequence[OutboxEntry], device: str, last_acked: str | None, now: float
) -> tuple[list[OutboxEntry], list[Effect]]:
    """Reconcile on hello: the id the device reports as its last acknowledged
    one was played while the socket was down. It closes an entry this device
    still holds, or one that went back to pending when the device vanished;
    an entry another device holds now is left to that device."""
    if last_acked is None:
        return list(entries), []
    changed: dict[str, OutboxEntry] = {}
    effects: list[Effect] = []
    for e in entries:
        if e.id != last_acked or not e.active:
            continue
        if e.device == device or e.state == State.pending:
            owned = e.with_(device=device) if e.device is None else e
            played, fx = on_played(owned, device, now)
            changed[e.id] = played
            effects.extend(fx)
    return _replace_in(entries, changed), effects
