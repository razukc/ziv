"""agent/tests/test_relay_compose.py -- the SkillForge compose scaffold's contract.

Since the track separation, the generic turn-adapter shapes live in
agent/relay_compose.py (SkillForge-owned), not in ports.py. This suite
proves the scaffold still works as a wrapper: retry accounting, telemetry
recording, and result wrapping -- so a week-3 compose implementer builds
against a proven surface, not a description of one.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ports import TelemetryRing
from relay_compose import RelayConfig, RelayResult, relay_run_turn


class _FakeAdapter:
    """A minimal RelayAdapter: canned result, retry accounting, call log."""

    def __init__(self, *, attempts_before_success: int = 0, event_type: str = "attention:double-tap") -> None:
        self.attempts_before_success = attempts_before_success
        self.event_type = event_type
        self.attempts = 0
        self.run_calls: list[dict] = []

    def run_turn(self, input_event, *, config, on_retry, telemetry):
        self.run_calls.append({"event": input_event, "config": config, "telemetry": telemetry})
        # The adapter owns its retry loop and reports healed failures through
        # on_retry (the wrapper counts them); it returns the final outcome.
        while self.attempts < self.attempts_before_success:
            self.attempts += 1
            if on_retry is not None:
                on_retry(self.attempts, RuntimeError("transient"))
        self.attempts += 1
        return RelayResult(event_type=self.event_type, payload={"text": "hello"})


def test_relay_run_turn_wraps_the_adapter_result():
    adapter = _FakeAdapter()
    result = relay_run_turn(adapter, {"kind": "message_arrived"})

    assert isinstance(result, RelayResult)
    assert result.event_type == "attention:double-tap"
    assert result.payload == {"text": "hello"}
    assert result.retries == 0
    assert adapter.run_calls[0]["event"] == {"kind": "message_arrived"}
    # The wrapper hands the adapter a RelayConfig (its own default or the caller's).
    assert isinstance(adapter.run_calls[0]["config"], RelayConfig)


def test_relay_run_turn_counts_healed_retries_and_reports_them():
    adapter = _FakeAdapter(attempts_before_success=2)
    retries: list[int] = []
    result = relay_run_turn(adapter, "evt", on_retry=lambda a, e: retries.append(a))

    assert result.event_type == "attention:double-tap"
    assert result.retries == 2
    assert retries == [1, 2]


def test_relay_run_turn_records_into_the_telemetry_ring():
    adapter = _FakeAdapter()
    ring = TelemetryRing(maxlen=4, recent_tail=2)
    relay_run_turn(adapter, "evt", telemetry=ring)

    stats = ring.stats()
    assert stats["samples"] == 1
    assert stats["recent"][0]["label"] == "attention:double-tap"
    assert stats["recent"][0]["relay_event"] == "attention:double-tap"


def test_relay_config_translates_into_a_retry_config():
    cfg = RelayConfig(max_attempts=5, backoff_base_seconds=0.2)
    rc = cfg.retry_config()
    assert rc.max_attempts == 5
    assert rc.backoff_base_seconds == 0.2


def test_relay_compose_is_importable_without_the_ziv_track():
    """The scaffold imports neither the Ziv seam nor any robot-track module."""
    import ast

    import relay_compose

    src = Path(relay_compose.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    allowed = {"__future__", "time", "dataclasses", "typing", "ports"}
    assert imported <= allowed, f"relay_compose.py imports outside the scaffold: {imported - allowed}"
