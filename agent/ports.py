"""agent/ports.py — small shared transport/retry/telemetry/mock primitives.

This is the layer both tracks can depend on without coupling to either
track's ontology (no skill_registry / robot_registry / pipeline_store /
ros2_package imports here, and no relay contract either). It owns:

* bounded retry with jittered backoff + an ``on_retry(attempt, error)`` hook
  (``RetryConfig`` + ``retry_with_backoff`` / ``retry_with_backoff_async`` /
  the public ``sleep_with_backoff``),
* a tiny SSE wire helper (event serialization + standard headers) so both
  servers can emit the same ``data: {json}`` + blank-line wire shape,
* a thread-safe capped telemetry ring for "label, seconds, retries" style
  events, surfaced as a small stats dict,
* a mock-mode switch + a ``FakeModel`` protocol so tests and demo modes can
  stand in for a real provider without touching it,
* small provider-reply helpers (``is_json_content``, ``parse_json_fenced``).

Track-owned contracts live with their tracks, not in this file: the
SkillForge compose scaffold (``RelayResult`` / ``RelayConfig`` /
``RelayAdapter`` / ``relay_run_turn``) is ``agent/relay_compose.py``; the
Ziv relay seam (``MessageGate`` + ``TurnTimeline`` + the lifecycle
constants) is ``agent/ziv_relay.py``. Both tracks import this module;
neither imports the other's contract module.
"""

from __future__ import annotations

import asyncio
import json
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# 1. Bounded retry with backoff
# ---------------------------------------------------------------------------

@dataclass
class RetryConfig:
    """How many times to retry a stateless provider call on transient failure.

    The live provider occasionally returns empty content or truncated JSON.
    Retrying the *same* prompt is cheap and usually lands; after
    ``max_attempts`` failures the last error is raised so callers can surface
    a clean failure.
    """

    max_attempts: int = 3
    backoff_base_seconds: float = 0.8
    # Each attempt n (1-based) sleeps base * n, with a little jitter so a
    # thundering herd of identical retries does not line up.
    jitter_ratio: float = 0.25
    # When True (default), ``on_retry`` is called with the 1-based attempt
    # number of every *healed* failure (i.e. every failure except the last).
    # The last failure raises without calling ``on_retry``, because there is
    # nothing left to heal.
    call_on_retry_on_healed_only: bool = True


def sleep_with_backoff(attempt: int, cfg: RetryConfig) -> None:
    """Sleep base * attempt with bounded jitter. ``attempt`` is 1-based."""
    base = cfg.backoff_base_seconds * attempt
    jitter = base * cfg.jitter_ratio * (2.0 * random.random() - 1.0)
    time.sleep(max(0.0, base + jitter))


def retry_with_backoff(
    fn: Callable[[], Any],
    *,
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[int, BaseException], None]] = None,
) -> Any:
    """Call ``fn()`` up to ``config.max_attempts`` times on transient failure.

    Returns the first non-exception result.

    ``on_retry`` (optional) is invoked as ``on_retry(attempt, error)`` after
    each failed attempt that will be retried (attempt is 1-based: 1 = the
    first call failed and a second call is being made). When
    ``call_on_retry_on_healed_only`` is True (the default), the final
    failure raises without calling ``on_retry``, because there is nothing
    left to heal.
    """
    cfg = config or RetryConfig()
    last_error: Optional[BaseException] = None

    for attempt in range(cfg.max_attempts):
        try:
            return fn()
        except BaseException as e:
            last_error = e
            if attempt < cfg.max_attempts - 1:
                if on_retry is not None:
                    on_retry(attempt + 1, e)
                sleep_with_backoff(attempt + 1, cfg)
            # else: last attempt failed — fall through to raise below
    # We exhausted attempts; re-raise the last error we saw.
    assert last_error is not None
    raise last_error


# Async analogue for async LLM calls. Same semantics as ``retry_with_backoff``,
# but uses ``asyncio.sleep`` and awaits ``fn``.

async def retry_with_backoff_async(
    fn: Callable[[], Any],
    *,
    config: Optional[RetryConfig] = None,
    on_retry: Optional[Callable[[int, BaseException], None]] = None,
) -> Any:
    cfg = config or RetryConfig()
    last_error: Optional[BaseException] = None

    for attempt in range(cfg.max_attempts):
        try:
            return await fn()
        except BaseException as e:
            last_error = e
            if attempt < cfg.max_attempts - 1:
                if on_retry is not None:
                    on_retry(attempt + 1, e)
                await asyncio.sleep(max(0.0, cfg.backoff_base_seconds * (attempt + 1)))
            # else: last attempt failed — fall through to raise below
    assert last_error is not None
    raise last_error


# ---------------------------------------------------------------------------
# 2. SSE wire helper
# ---------------------------------------------------------------------------

SSE_EVENT_PREFIX = "data: "
SSE_EVENT_SUFFIX = "\n\n"

# Standard headers that keep proxies from buffering SSE down the wire.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_event(payload: object) -> str:
    """Serialize one SSE event as ``data: {json}\\n\\n``."""
    return f"{SSE_EVENT_PREFIX}{json.dumps(payload, ensure_ascii=False)}{SSE_EVENT_SUFFIX}"


def sse_ok_headers(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Standard SSE response headers, with optional extra overrides."""
    out = dict(SSE_HEADERS)
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------
# 3. Telemetry ring
# ---------------------------------------------------------------------------

@dataclass
class TelemetryEntry:
    label: str
    seconds: float
    retries: int
    at: str
    extra: dict[str, Any] = field(default_factory=dict)


class TelemetryRing:
    """Thread-safe capped ring of recent labeled events.

    Typical shape: one per logical workflow (e.g. "compose"), reported from a
    health endpoint without standing up external metrics.
    """

    def __init__(self, maxlen: int = 20, recent_tail: int = 10) -> None:
        self._maxlen = maxlen
        self._recent_tail = recent_tail
        self._ring: deque[TelemetryEntry] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(self, label: str, seconds: float, retries: int, **extra: Any) -> None:
        entry = TelemetryEntry(
            label=label,
            seconds=round(seconds, 1),
            retries=retries,
            at=_utc_iso(),
            extra=extra,
        )
        with self._lock:
            self._ring.append(entry)

    def stats(self) -> dict[str, Any]:
        """Summary + the tail of the ring, suitable for a health payload."""
        with self._lock:
            entries = list(self._ring)
        if not entries:
            return {"samples": 0, "recent": []}
        secs = [e.seconds for e in entries]
        ordered = sorted(secs)
        p95_idx = min(len(ordered) - 1, int(0.95 * len(ordered)))
        return {
            "samples": len(entries),
            "avg_seconds": round(sum(secs) / len(secs), 1),
            "p95_seconds": round(ordered[p95_idx], 1),
            "avg_retries": round(
                sum(e.retries for e in entries) / len(entries), 2
            ),
            "retried_events": sum(1 for e in entries if e.retries > 0),
            "recent": [
                {
                    "label": e.label,
                    "seconds": e.seconds,
                    "retries": e.retries,
                    "at": e.at,
                    **e.extra,
                }
                for e in entries[-self._recent_tail:]
            ],
        }

    @property
    def maxlen(self) -> int:
        return self._maxlen


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# 4. Mock-mode switch + fake-model protocol
# ---------------------------------------------------------------------------

@dataclass
class MockModeFlag:
    """A process/shared mock-mode switch.

    Real providers are expensive and non-deterministic; tests and demo paths
    want a stable ``FakeModel`` instead. This is deliberately a thin flag
    object so a relay can back it with anything (in-memory bool, env var,
    feature flag, etc.) without the rest of the layer knowing.
    """

    live: bool = True

    def is_live(self) -> bool:
        return self.live

    def enter_mock(self) -> None:
        self.live = False

    def enter_live(self) -> None:
        self.live = True


# A ``FakeModel`` is any object that can stand in for a real provider in the
# places the rest of the layer cares about: it exposes ``calls`` (an ordered
# log of every LLM-facing method invoked) and the method signatures the
# backing code expects. The protocol is deliberately informal (structural) so
# it does not force a base class on relay authors; the tests just check
# ``hasattr`` / call signatures.
#
# Right now that surface is:
#   fake.calls: list[str]            # every method invoked, by name
#   fake.decompose_task(task, robot, ...): -> dict  (or whatever shape the
#                                                 caller expects)
#   fake.explain_pipeline(pipeline, ...): -> str
#   fake.suggest_improvements(pipeline, ...): -> list
#
# Future relays may want a different surface; that is fine — this protocol is
# the SkillForge compose surface, documented here so the fake and the real
# agent stay compatible.

FakeModel = Any  # structural protocol; see docstring above


def fake_calls(fake: FakeModel) -> list:
    """Ordered log of every LLM-facing method the fake was invoked with."""
    return list(getattr(fake, "calls", []) or [])


def fake_last_seed(fake: FakeModel) -> Any:
    """Last seed pipeline the fake received, if the fake records one."""
    return getattr(fake, "last_seed", None)


# ---------------------------------------------------------------------------
# 5. Small helpers used by the shared layer's own tests / consumers
# ---------------------------------------------------------------------------

def is_json_content(value: Any) -> bool:
    """Heuristic used by callers that need to decide whether a provider reply
    is 'content' vs 'tool_calls / empty / truncated'."""
    if value is None:
        return False
    if isinstance(value, str):
        text = value.strip()
        return bool(text)
    return True


def parse_json_fenced(content: str) -> Any:
    """Strip markdown code fences if present, then parse JSON.

    Mirrors the existing ``ReasoningAgent._extract_pipeline_json`` behavior so
    callers that reuse that parsing logic do not need to re-import the agent
    module.
    """
    if "```json" in content:
        content = content.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in content:
        content = content.split("```", 1)[1].split("```", 1)[0]
    return json.loads(content)
