"""agent/relay_compose.py - the SkillForge compose scaffold (SkillForge-owned).

This module owns the generic turn-adapter shapes the SkillForge compose path
uses: RelayResult (the event vocabulary), RelayConfig (tunable retry
parameters), the RelayAdapter structural protocol, and relay_run_turn (the
wrapper that drives one turn through an adapter with shared retry +
telemetry accounting).

This is *not* the Ziv relay's seam. The Ziv relay's real contract -
MessageGate + TurnTimeline + the lifecycle constants - lives in
agent/ziv_relay.py; a Ziv relay builds against that seam and its own
TurnEvent vocabulary, never against this scaffold. The two tracks are
deliberately independent: SkillForge may import ports and this module,
Ziv may import ports and ziv_relay, and neither imports the other's
contract.

It imports only ports (the shared retry/telemetry primitives) - never
robot-track modules (skill_registry / robot_registry / pipeline_store /
ros2_package) - so it stays as importable as the shared layer itself.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ports import RetryConfig, TelemetryRing


@dataclass
class RelayResult:
    """One relay turn's output, in the shared event vocabulary."""
    # The shared SSE event types the frontend already knows how to render.
    # A relay may emit its own subtypes, but the shared layer keeps the
    # common ones stable so a generic reader can still drive a UI.
    event_type: str
    payload: dict[str, Any]
    # Relays that compose/wait on a provider should report how long the turn
    # took and whether it healed via retry.
    seconds: float = 0.0
    retries: int = 0


class RelayConfig:
    """Parameters a relay author can tune without touching the shared core."""

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        backoff_base_seconds: float = 0.8,
        retry_on_empty: bool = True,
        retry_on_truncated: bool = True,
    ) -> None:
        self.max_attempts = max_attempts
        self.backoff_base_seconds = backoff_base_seconds
        self.retry_on_empty = retry_on_empty
        self.retry_on_truncated = retry_on_truncated

    def retry_config(self) -> RetryConfig:
        return RetryConfig(
            max_attempts=self.max_attempts,
            backoff_base_seconds=self.backoff_base_seconds,
        )


# A RelayAdapter is the part that is *not* shared: it owns the model
# (real or fake), the input path (mic / chord input / whatever), and the
# output path (DRV2605L timeline / whatever). The wrapper only knows that it
# can call adapter.run_turn(...) and get back a RelayResult.
#
# This is the SkillForge compose surface, not the Ziv relay contract. A Ziv
# relay does *not* implement this - its real seam is agent/ziv_relay.py
# (MessageGate + TurnTimeline).
RelayAdapter = Any  # structural protocol; see the contract comment below

# Minimal contract a RelayAdapter should satisfy so the wrapper can drive
# it generically (this is the SkillForge compose surface):
#
#   adapter.run_turn(input_event, *, config, on_retry, telemetry) -> RelayResult
#
#   where:
#     input_event  - whatever the adapter's input path produces; the wrapper
#                    passes it through opaquely.
#     config       - a RelayConfig (or RetryConfig) the adapter honors.
#     on_retry     - the shared on_retry(attempt, error) hook.
#     telemetry    - a TelemetryRing instance the adapter may record to.
#
# The return is a RelayResult so the wrapper (and any generic SSE reader)
# can render it without knowing the adapter's internal event vocabulary. Note:
# this is *not* the Ziv relay contract - see agent/ziv_relay.py for the
# real seam (MessageGate + TurnTimeline + the lifecycle constants).


def relay_run_turn(
    adapter: RelayAdapter,
    input_event: Any,
    *,
    config: Optional[RelayConfig] = None,
    on_retry: Optional[Callable[[int, BaseException], None]] = None,
    telemetry: Optional[TelemetryRing] = None,
) -> RelayResult:
    """Drive one turn through a RelayAdapter, using the shared primitives.

    This is the SkillForge compose wrapper: it times the call, counts healed
    retries, records the outcome into a TelemetryRing if given one, and
    returns a RelayResult so a generic reader can render the turn without
    knowing the adapter's internal vocabulary.

    It is *not* the Ziv relay's server loop. The Ziv relay's real seam - the
    gate, the timeline, and the lifecycle ordering - lives in
    agent/ziv_relay.py (MessageGate + TurnTimeline); the Ziv server drives
    turns through that seam directly rather than through this wrapper.
    """
    cfg = config or RelayConfig()
    t0 = time.monotonic()
    retries = 0

    def _count_retry(attempt: int, error: BaseException) -> None:
        nonlocal retries
        retries += 1
        if on_retry is not None:
            on_retry(attempt, error)

    # A real relay would call into its model/pipeline here and translate the
    # result back into the shared RelayResult event vocabulary. For now
    # we just delegate to the adapter and wrap the outcome so the shared
    # layer can render it generically.
    result = adapter.run_turn(
        input_event,
        config=cfg,
        on_retry=_count_retry,
        telemetry=telemetry,
    )
    seconds = round(time.monotonic() - t0, 1)

    # Record into the shared telemetry ring if the relay gave us one.
    if telemetry is not None:
        telemetry.record(
            label=result.event_type,
            seconds=seconds,
            retries=retries,
            relay_event=result.event_type,
        )

    # Merge shared-level retry accounting into the result so a generic reader
    # sees the same retry count the telemetry ring saw.
    out = RelayResult(
        event_type=result.event_type,
        payload=result.payload,
        seconds=seconds,
        retries=retries,
    )
    return out
