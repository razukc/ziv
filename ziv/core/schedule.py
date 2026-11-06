"""ziv.core.schedule — which promises are due, and the lease that guards firing.

A due row is claimed under a lease (``lease_until = now + window``) so a
crash between the claim and the outbox insert lets the lease expire and the
row fire again: redelivery, never loss (docs/ARCHITECTURE.md §4.4).
"""
from __future__ import annotations

from collections.abc import Iterable

from ziv.wire import Kind, Reason, Source, Utterance

from . import spec
from .model import Refusal, ScheduleEntry, to_datetime


def is_leased(entry: ScheduleEntry, now: float) -> bool:
    return entry.lease_until is not None and entry.lease_until > now


def is_due(entry: ScheduleEntry, now: float) -> bool:
    return entry.fire_at <= now and not is_leased(entry, now)


def due(entries: Iterable[ScheduleEntry], now: float) -> list[ScheduleEntry]:
    return sorted((e for e in entries if is_due(e, now)), key=lambda e: (e.fire_at, e.id or 0))


def lease(entry: ScheduleEntry, now: float, window_s: float) -> ScheduleEntry:
    return entry.with_(lease_until=now + window_s)


def check_cap(count: int, cap: int) -> Refusal | None:
    """The schedule cap refuses new rows; it never evicts the soonest."""
    if count >= cap:
        return Refusal(Reason.queue_full, f"{count} scheduled; the cap is {cap}", {"scheduled": count, "cap": cap})
    return None


def build_utterance(
    entry: ScheduleEntry,
    *,
    id: str,
    words: Iterable[str],
    body_pending: bool,
    source: Source,
    sender: str,
) -> Utterance:
    """The utterance a fired schedule row becomes: the kind's prefix from the
    spec, ``not_before`` at the fire time and ``expires`` after the row's window."""
    return Utterance(
        id=id,
        wearer=entry.wearer,
        kind=Kind(entry.kind),
        **{"from": {"sender": sender, "label": entry.label}},
        prefix=spec.prefix_for(Kind(entry.kind)),
        words=list(words),
        body_pending=body_pending,
        source=source,
        not_before=to_datetime(entry.fire_at),
        expires=to_datetime(entry.expires_at()),
        spec_version=spec.spec_version(),
    )
