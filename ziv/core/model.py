"""ziv.core.model — the relay's domain types.

Plain frozen dataclasses. The wire ``Utterance`` is embedded whole in an
``OutboxEntry`` because the device must receive exactly what admission echoed
to the sender; everything else here is relay-side bookkeeping that never
crosses the wire.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from ziv.wire import Advance, Kind, Late, Prefs, Profile, Reason, State, Utterance

from . import spec

SCOPE_SEND = "send"
SCOPE_READ = "read"
SCOPE_ADMIN = "admin"
SCOPES = frozenset({SCOPE_SEND, SCOPE_READ, SCOPE_ADMIN})

ACTIVE_STATES = frozenset({State.pending, State.sent, State.playing})
TERMINAL_STATES = frozenset({State.played, State.failed, State.expired, State.cancelled})


def to_epoch(dt: datetime | None) -> float | None:
    """A wire datetime as epoch seconds. Naive datetimes are taken as UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def to_datetime(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


@dataclass(frozen=True, slots=True)
class Refusal:
    """Why something was not accepted. ``detail`` carries numbers and codes;
    ``message`` is a short sentence for the sender. Neither is ever logged."""

    reason: Reason
    message: str = ""
    detail: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"reason": str(self.reason), "message": self.message}
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass(frozen=True, slots=True)
class Wearer:
    id: str
    name: str
    created: float


@dataclass(frozen=True, slots=True)
class Device:
    id: str
    wearer: str
    name: str
    profile: Profile
    primary: bool
    order: int
    key_hash: str
    created: float
    last_seen: float | None = None


@dataclass(frozen=True, slots=True)
class Sender:
    id: str
    wearer: str
    label: str
    token_hash: str
    scopes: frozenset[str]
    rate_per_min: int
    created: float

    def allows(self, scope: str) -> bool:
        return scope in self.scopes or SCOPE_ADMIN in self.scopes


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    """One row of the per-wearer outbox (docs/ARCHITECTURE.md §4.1)."""

    utterance: Utterance
    state: State
    created: float
    updated: float
    duration_ms: int
    budget_ms: int
    device: str | None = None
    reason: Reason | None = None
    sent_at: float | None = None
    played_at: float | None = None
    played_ms: int | None = None
    tried: frozenset[str] = frozenset()   # devices that held it and never started it
    late: bool = False                     # passed ``expires`` and is being played late
    lossy: bool = False                    # normalisation dropped characters

    @property
    def id(self) -> str:
        return self.utterance.id

    @property
    def wearer(self) -> str:
        return self.utterance.wearer

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def body_pending(self) -> bool:
        return self.utterance.body_pending

    def expires_at(self) -> float | None:
        return to_epoch(self.utterance.expires)

    def not_before_at(self) -> float | None:
        return to_epoch(self.utterance.not_before)

    def with_(self, **changes: Any) -> "OutboxEntry":
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    """A promise to fire later: a finished text, or an intent composed at fire time."""

    id: int | None
    wearer: str
    fire_at: float
    kind: Kind
    text: str | None
    intent: str | None
    expires_after_s: int
    created: float
    label: str | None = None
    lease_until: float | None = None

    @property
    def composed(self) -> bool:
        return self.intent is not None

    def expires_at(self) -> float:
        return self.fire_at + self.expires_after_s

    def with_(self, **changes: Any) -> "ScheduleEntry":
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class WearerPrefs:
    """The wearer's preferences as the relay holds them: always complete, always
    inside the spec's envelope. ``wire.Prefs`` is the partial form on the wire."""

    pace_ms: int
    advance: Advance = Advance.auto
    late: Late = Late.drop
    history: bool = False

    @classmethod
    def defaults(cls) -> "WearerPrefs":
        return cls(pace_ms=spec.pace_envelope()[2])

    def merged(self, update: Prefs) -> "WearerPrefs":
        """Apply a partial wire update and clamp the pace into the spec envelope."""
        return WearerPrefs(
            pace_ms=spec.clamp_pace(update.pace_ms if update.pace_ms is not None else self.pace_ms),
            advance=update.advance if update.advance is not None else self.advance,
            late=update.late if update.late is not None else self.late,
            history=update.history if update.history is not None else self.history,
        )

    def to_wire(self) -> Prefs:
        return Prefs(pace_ms=self.pace_ms, advance=self.advance, late=self.late, history=self.history)
