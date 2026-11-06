"""ziv.relay.clock — the injected clock. Tests drive ``FakeClock``; nothing sleeps."""
from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Epoch seconds."""

    def monotonic(self) -> float:
        """Seconds from an arbitrary origin, never going backwards."""


class SystemClock:
    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


class FakeClock:
    """A clock that moves only when told to."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self._now = float(start)
        self._origin = float(start)

    def now(self) -> float:
        return self._now

    def monotonic(self) -> float:
        return self._now - self._origin

    def advance(self, seconds: float) -> float:
        if seconds < 0:
            raise ValueError("a clock does not go backwards")
        self._now += float(seconds)
        return self._now

    def set(self, now: float) -> None:
        if now < self._now:
            raise ValueError("a clock does not go backwards")
        self._now = float(now)
