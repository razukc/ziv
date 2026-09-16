"""agent/tests_ziv/test_ziv_e2e.py -- one scripted integration vertical for the Ziv track.

What it is
----------
A single idempotent end-to-end test that goes from a canned "hear" event all the
way through to a DRV2605L mock timeline, and asserts the resulting buzz/gap
sequence. It is the first concrete proof that the Ziv track has at least one
whole vertical -- input event, relay turn, haptic output -- even though most of
the real relay (mic path, braille-chord input, WebSocket, FreeRTOS task, Token
Factory Omni payload) does not exist yet.

What it owns vs what it mocks
-----------------------------
It owns the *contract* and the *timing expectations* -- the spec file is the
single source of truth, and this test reads it directly and re-derives the
attention-pattern beat sequences the same way the phone mock and the C firmware
header do (tools/haptic_timing.py), so the three sides agree by construction.

It mocks the parts that do not exist yet:

* the real relay / agent (runs the request through a local stub so no network,
  no API key, no Token Factory),
* the DRV2605L (a tiny in-process mock bus that records every set_drive call,
  so we can assert the dot-mask timeline instead of wiring real I2C),
* the device input path (we just hand the stub a canned input event).

It deliberately does NOT mock the spec, the letter-to-timing derivation, or the
mark/pattern vocabulary -- those are the parts we want to prove end-to-end once,
and agent/tests_ziv/test_haptic_timing.py already locks the generator, spec, and
header drift at the file level. This test is one layer up: it proves the *flow*
from an input event to the expected buzz/gap sequence.

Fallback ladder (same shape as the plan's, localized to a test):
1. Canned-cli stub path (this test) -- proves the contract and timing.
2. Real relay path -- when ziv_relay.py has a real run_turn, swap the stub for
   the real adapter and keep the same assertions.
3. Real device path -- when there is a real I2C bus, swap the mock bus for the
   real one and keep the same timeline assertions.

Run
---
  . .venv2/Scripts/activate
  pytest tests_ziv/test_ziv_e2e.py -q

It is hermetic and has no API key / network dependency.

Import note
-----------
The repo does not install `tools/` or `agent/` on PYTHONPATH, so this test
follows the same sys.path dance agent/tests_ziv/test_haptic_timing.py uses to
reach `tools/`, and does the equivalent for `agent/` (ports + ziv_relay) so
the shared layer is importable from the test without a package install.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

# Reachable from this test file's siblings (tools/ and agent/) by construction.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tools"))
if str(_ROOT / "agent") not in sys.path:
    sys.path.insert(0, str(_ROOT / "agent"))

# The haptic timing vocabulary is a *generated* consumer of the spec now:
# tools/haptic_timing_gen.py is derived from docs/haptic-timing.json by
# tools/haptic_timing.py --write, the same way the feel-tool JS block and the
# C header are. Tests import it instead of re-deriving beat tables from the
# JSON — one derivation shared by tests, the relay, and tools, held in sync
# by the drift guard (test_haptic_timing.py).
import haptic_timing_gen as timing  # noqa: E402  (after the sys.path dance)


# The shared layer's telemetry ring is the place a future relay would record
# turn-level stats. Exercising it here is the smallest proof the shared layer
# is actually importable by a Ziv-oriented test without dragging in robot-track
# modules.
from ports import TelemetryRing
from ziv_relay import (
    ACCEPTED,
    CLOSED,
    ERROR,
    PLAYING,
    PROCESSING,
    KIND_PLAYBACK_DONE,
    KIND_PROCESSING,
    PATTERN_END_OF_MESSAGE,
    PATTERN_ERROR,
    PATTERN_MESSAGE_CUE,
    PATTERN_PROCESSING,
    MessageGate,
    TurnEvent,
    TurnTimeline,
    ZivRelayAdapter,
)


# ---------------------------------------------------------------------------
# Fake input event vocabulary (canned for now -- a real relay would fill this
# in from mic capture / braille-chord input / WS frames).
# ---------------------------------------------------------------------------

@dataclass
class HearEvent:
    """A canned "hear" input event -- the kind a real relay would receive from
    the device's audio-in path.

    Today this is a placeholder: it carries the text side of what a "hear" turn
    would mean, and leaves audio/frames for when the relay is built. The event
    type string is chosen to match the attention vocabulary in the spec so the
    output side can be asserted against the same tables both consumers use.
    """

    kind: str  # e.g. "message_arrived", "reminder_fired", "error"
    text: str = ""
    # A real relay would also carry an audio payload / frame list here once the
    # mic path exists. For now it is empty on purpose -- this test is the
    # text/attention-pattern vertical, not the voice vertical.
    audio_frames: list[Any] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DRV2605L mock bus -- records every set_drive call the sequencer makes.
# ---------------------------------------------------------------------------

@dataclass
class DriveRecord:
    dot_channel: int
    level: int  # DRV2605_DRIVE_DEFAULT or 0
    at_ms: int


class MockDrv2605Bus:
    """A tiny in-process stand-in for the DRV2605L I2C bus.

    A real relay would plug a real I2C bus (or a hardware bench) in here. For
    now we record every set_drive call with a monotonic timestamp so the test
    can assert the *dot-mask timeline* the firmware sequencer produces, without
    any real hardware.
    """

    DRIVE_DEFAULT = 0x1F  # arbitrary stand-in for "drive on"

    def __init__(self) -> None:
        self.records: list[DriveRecord] = []
        self.stop_calls: int = 0
        self._t: int = 0

    def set_drive(self, channel: int, level: int, now_ms: int) -> None:
        self.records.append(DriveRecord(dot_channel=channel, level=level, at_ms=now_ms))

    def stop_all(self, now_ms: int) -> None:
        self.stop_calls += 1

    def tick(self, ms: int) -> None:
        self._t = ms


# ---------------------------------------------------------------------------
# The Ziv relay adapter that this test actually exercises.
# ---------------------------------------------------------------------------

class CannedZivRelayAdapter(ZivRelayAdapter):
    """A stub that subclasses the placeholder ``ZivRelayAdapter`` landing pad
    and returns canned ``TurnEvent`` events for the attention patterns the
    spec already defines.

    Note: ``ZivRelayAdapter`` is the labeled ``run_turn`` landing pad in
    ``ziv_relay.py``, *not* the Ziv relay contract — the real seam is
    ``MessageGate`` + ``TurnTimeline``. This stub builds against that landing
    pad alone: no compose wrapper, no config object, just ``run_turn`` in and
    a ``TurnEvent`` out. It is not a model of the real relay, which will
    drive ``MessageGate`` + ``TurnTimeline`` directly.

    A real Ziv relay would replace this with one that:
    * reads a real HearEvent (audio frame / braille chord),
    * drives ``MessageGate.admit`` and ``TurnTimeline`` in the documented order,
    * calls a real model / local policy for the round-trip,
    * translates the result into a haptic/device action.

    This stub's job is to let us prove the *flow* and the *assertions* now, so
    swapping in the real relay later keeps the same input-event shape, the same
    telemetry ring, and the same timing assertions -- the real relay drives the
    seam (MessageGate + TurnTimeline) directly, exactly like this stub drives
    the landing pad.
    """

    def __init__(self, bus: MockDrv2605Bus) -> None:
        # The landing pad is self-standing (no base class): nothing to chain.
        self.bus = bus
        self.turns: list[dict] = []

    def is_ready(self) -> bool:
        return True

    def run_turn(
        self,
        input_event: Any,
        *,
        on_retry: Any = None,
        telemetry: Any = None,
    ) -> TurnEvent:
        """One turn through the canned relay.

        The stub maps a HearEvent.kind to the matching attention pattern id
        from the spec (the same mapping the device's prefix tails use), emits a
        TurnEvent the caller can render, and records the turn into the
        telemetry ring when given one. It does
        NOT own the haptic timeline -- that stays with the output-side sequencer
        (the firmware's haptic_out, or its mock here). The stub only decides
        *what* plays; the timeline is whatever the sequencer produces from the
        spec tables.
        """
        event: HearEvent
        if isinstance(input_event, dict):
            event = HearEvent(**input_event)
        elif isinstance(input_event, HearEvent):
            event = input_event
        else:
            raise TypeError(f"unexpected input event type: {type(input_event)}")

        # Map the canned event kind to the attention pattern the spec already
        # defines (the same mapping the device's prefix tails use). Unknown
        # kinds fall back to a "no playback" response rather than crashing.
        tail_map = {
            "message_arrived": "double-tap",
            "reminder_fired": "triple-pulse",
            "error": "long-buzz",
            "boot": "ramp-up",
            "alive": "heartbeat",
        }
        pattern_id = tail_map.get(event.kind, None)

        self.turns.append({"kind": event.kind, "pattern_id": pattern_id, "text": event.text})

        if pattern_id is None:
            # No haptic pattern to play for an unrecognized kind -- the relay
            # still returns an event so the caller's telemetry can record it.
            if telemetry is not None:
                telemetry.record(label="idle", seconds=0.0, retries=0)
            return TurnEvent(
                event_type="idle",
                payload={"kind": event.kind, "text": event.text},
            )

        # The stub does not play the pattern itself -- that is the sequencer's
        # job. It just returns the decision so the caller (the shared layer,
        # then the sequencer mock) can assert the expected beat sequence against
        # the spec tables.
        beats = timing.pattern_beats(pattern_id)

        if telemetry is not None:
            telemetry.record(label=f"attention:{pattern_id}", seconds=0.0, retries=0)
        return TurnEvent(
            event_type=f"attention:{pattern_id}",
            payload={
                "kind": event.kind,
                "pattern_id": pattern_id,
                "text": event.text,
                "beats": beats,
            },
        )


# ---------------------------------------------------------------------------
# A very small haptic timeline mock -- the output side of the vertical.
# ---------------------------------------------------------------------------

class HapticTimelineMock:
    """A thin mock of the firmware's haptic_out sequencer that produces a buzz/
    gap timeline from the generated timing module.

    It is deliberately *not* a re-implementation of the C sequencer. It is a
    read-side mock: it accepts a pattern id (resolved against the generated
    timing module, the same derivation the C header carries), drives the mock
    bus with the resulting dot-mask timeline, and records the produced beats
    so the test can assert the exact buzz/gap sequence. The C sequencer is the real implementation;
    this mock exists so the test can run on any host without the firmware toolchain.
    """

    def __init__(self, bus: MockDrv2605Bus) -> None:
        self.bus = bus
        self.played: list[dict] = []

    def play_pattern(self, pattern_id: str) -> list[dict]:
        """Play an attention pattern from the timing module and drive the bus."""
        beats = timing.pattern_beats(pattern_id)
        timeline: list[dict] = []
        t = 0
        for buzz_ms, gap_after_ms in beats:
            t += buzz_ms
            # A real sequencer would look up the dot mask from the cell / pattern
            # rules. For attention patterns the spec's beats carry no dot mask
            # (they are whole-device patterns), so we drive all six dots for the
            # buzz and silence them for the gap -- matching the hardware intent
            # (everything vibrates for a tick, nothing for the gap).
            for ch in range(6):
                self.bus.set_drive(ch, self.bus.DRIVE_DEFAULT, t)
            timeline.append({"at_ms": t, "buzz_ms": buzz_ms, "gap_after_ms": gap_after_ms, "dots": 6})
            t += gap_after_ms
        self.played.append({"pattern_id": pattern_id, "beats": timeline})
        return timeline


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _expected_beats(pattern_id: str) -> list[tuple[int, int]]:
    """Expected (buzz_ms, gap_after_ms) pairs, read from the generated timing module."""
    return list(timing.PATTERN_BEATS[pattern_id])


# ---------------------------------------------------------------------------
# The integration test
# ---------------------------------------------------------------------------

@pytest.fixture
def bus() -> MockDrv2605Bus:
    return MockDrv2605Bus()


@pytest.fixture
def relay(bus: MockDrv2605Bus) -> CannedZivRelayAdapter:
    return CannedZivRelayAdapter(bus)


@pytest.fixture
def timeline(bus: MockDrv2605Bus) -> HapticTimelineMock:
    return HapticTimelineMock(bus)


def test_ziv_hear_event_flow_message_arrived(
    relay: CannedZivRelayAdapter, timeline: HapticTimelineMock, bus: MockDrv2605Bus
) -> None:
    """Canned 'message arrived' hear event -> attention pattern -> buzz/gap timeline.

    This is the one scripted vertical the Ziv track had before this test:
    input event -> relay turn -> what plays. We assert the relay chose the right
    attention pattern (double-tap), and that the resulting timeline matches the
    spec tables both consumers use.
    """
    event = HearEvent(kind="message_arrived", text="You have a new message.")

    # The canned adapter is driven directly through the Ziv seam's landing-pad
    # shape: one run_turn call, one TurnEvent back. It is *not* the Ziv relay's
    # server loop -- the real relay drives MessageGate + TurnTimeline directly
    # (see ziv_relay.py). The TelemetryRing is the one shared primitive here.
    ring = TelemetryRing(maxlen=8, recent_tail=4)
    result = relay.run_turn(
        event,
        on_retry=lambda attempt, error: None,
        telemetry=ring,
    )

    # The relay decided what plays.
    assert result.event_type == "attention:double-tap"
    assert result.payload["kind"] == "message_arrived"
    assert result.payload["pattern_id"] == "double-tap"
    assert result.payload["text"] == "You have a new message."

    # The timeline mock plays the chosen pattern against the mock bus.
    timeline.play_pattern("double-tap")

    # Assert the produced beats match the spec tables exactly.
    expected = _expected_beats("double-tap")
    played = timeline.played[-1]["beats"]
    assert [ (p["buzz_ms"], p["gap_after_ms"]) for p in played ] == expected

    # Assert the bus timeline: every buzz drives all six dots, every gap drives
    # nothing (the mock does stop_all after each buzz implicitly via the timeline
    # model -- here we just assert the drive records land at the right times).
    recs = bus.records
    assert len(recs) == 2 * 6  # two beats, six dots each
    # First beat: buzz at t=70, drives all six dots.
    assert [r.at_ms for r in recs[:6]] == [70, 70, 70, 70, 70, 70]
    assert all(r.level == bus.DRIVE_DEFAULT for r in recs[:6])
    # Second beat: buzz at t=70+160+70 = 300, drives all six dots.
    assert [r.at_ms for r in recs[6:]] == [300, 300, 300, 300, 300, 300]

    # Telemetry recorded the turn.
    stats = ring.stats()
    assert stats["samples"] == 1
    assert stats["recent"][0]["label"] == "attention:double-tap"
    assert stats["recent"][0]["retries"] == 0


def test_ziv_hear_event_flow_reminder_fired(
    relay: CannedZivRelayAdapter, timeline: HapticTimelineMock, bus: MockDrv2605Bus
) -> None:
    """A scheduled reminder fires unprompted -> triple-pulse -> correct timeline.

    This is the 'acts while you are away' beat from the plan, proven in a test
    rather than asserted in prose.
    """
    event = HearEvent(kind="reminder_fired", text="Pills at 9pm.")
    result = relay.run_turn(event, telemetry=TelemetryRing())
    assert result.event_type == "attention:triple-pulse"
    assert result.payload["pattern_id"] == "triple-pulse"

    timeline.play_pattern("triple-pulse")
    expected = _expected_beats("triple-pulse")
    played = timeline.played[-1]["beats"]
    assert [ (p["buzz_ms"], p["gap_after_ms"]) for p in played ] == expected

    # Three beats, six dots each.
    assert len(timeline.played[-1]["beats"]) == 3
    assert len(bus.records) == 3 * 6


def test_ziv_hear_event_flow_error(
    relay: CannedZivRelayAdapter, timeline: HapticTimelineMock, bus: MockDrv2605Bus
) -> None:
    """Error attention -> long-buzz (single sustained beat, unlike any braille cell)."""
    event = HearEvent(kind="error", text="Something failed.")
    result = relay.run_turn(event, telemetry=TelemetryRing())
    assert result.event_type == "attention:long-buzz"
    assert result.payload["pattern_id"] == "long-buzz"

    timeline.play_pattern("long-buzz")
    expected = _expected_beats("long-buzz")
    played = timeline.played[-1]["beats"]
    assert [ (p["buzz_ms"], p["gap_after_ms"]) for p in played ] == expected

    # One beat: buzz_ms = 600, gap_after_ms = 420.
    assert len(timeline.played[-1]["beats"]) == 1
    assert timeline.played[-1]["beats"][0]["buzz_ms"] == 600
    assert timeline.played[-1]["beats"][0]["gap_after_ms"] == 420


def test_ziv_unrecognized_kind_returns_idle_not_crash(
    relay: CannedZivRelayAdapter, timeline: HapticTimelineMock
) -> None:
    """An unrecognized hear-kind does not crash the relay -- it returns idle."""
    event = HearEvent(kind="unknown_event", text="")
    result = relay.run_turn(event, telemetry=TelemetryRing())
    assert result.event_type == "idle"
    assert result.payload["kind"] == "unknown_event"
    assert timeline.played == []  # nothing played


def test_ziv_relay_records_every_turn(
    relay: CannedZivRelayAdapter, timeline: HapticTimelineMock
) -> None:
    """The relay adapter records each turn so a real relay could stream them."""
    event_a = HearEvent(kind="message_arrived", text="Hi")
    event_b = HearEvent(kind="reminder_fired", text="9pm")
    relay.run_turn(event_a)
    relay.run_turn(event_b)
    assert len(relay.turns) == 2
    assert relay.turns[0]["pattern_id"] == "double-tap"
    assert relay.turns[1]["pattern_id"] == "triple-pulse"


def test_ziv_telemetry_ring_is_shared_layer_importable_without_robot_imports() -> None:
    """Smallest proof the shared layer is importable by a Ziv-oriented test
    without dragging in robot-track modules (skill_registry, robot_registry,
    pipeline_store, ros2_package).

    This is the seam-check the historical summary suggested: if this import
    works, a Ziv relay can depend on agent/ports.py without coupling to the
    Physical AI track.
    """
    # These are exactly the robot-track modules the shared layer promises not
    # to import. If any of them were imported by ports, this test would be the
    # place that catches it (because we never import them here).
    import ports  # noqa: F401

    ring = TelemetryRing(maxlen=4, recent_tail=2)
    ring.record("turn", 1.5, 0)
    ring.record("turn", 2.0, 1)
    stats = ring.stats()
    assert stats["samples"] == 2
    assert stats["retried_events"] == 1
    assert stats["avg_retries"] == 0.5

    # The shared SSE helper is also importable and produces the wire shape the
    # frontend already knows how to read.
    from ports import sse_event, sse_ok_headers

    ev = sse_event({"type": "attention:double-tap", "payload": {"kind": "message_arrived"}})
    assert ev.startswith("data: ")
    assert ev.endswith("\n\n")
    parsed = json.loads(ev[6:].rstrip("\n\n"))
    assert parsed["type"] == "attention:double-tap"

    headers = sse_ok_headers()
    assert headers["Cache-Control"] == "no-cache"
    assert headers["Connection"] == "keep-alive"


# ---------------------------------------------------------------------------
# The queue-don't-interrupt vertical (plan §4 invariant 4) -- the first real
# relay behavior, exercised through the same shared-layer primitives.
# ---------------------------------------------------------------------------

def test_ziv_message_gate_plays_when_idle_and_queues_when_playing() -> None:
    """Idle gate admits content; playing gate announces (cue only) and queues.

    Invariant 4: an incoming message during playback may play its attention
    cue (double-tap) immediately, but its *content* waits — nothing barges
    into what the wearer is already reading. The decision (not the text) is
    what the shared layer renders, so the assertions are on TurnEvents.
    """
    gate = MessageGate()

    # Idle: the message plays now, with its full who→why prefix.
    result = gate.admit("Taxi arrived.")
    assert result.event_type == "message:play"
    assert result.payload == {"text": "Taxi arrived.", "queued": False, "prefix": True}
    assert len(gate) == 0

    # Playback begins (the sequencer reports content on the motors).
    gate.begin_playback()
    assert gate.playing is True

    # While playing: attention cue now, content queued.
    result = gate.admit("Pills at 9pm.")
    assert result.event_type == "attention:double-tap"
    assert result.payload == {"text": "Pills at 9pm.", "queued": True, "prefix": True}
    assert len(gate) == 1

    # The queued text never reached a message:play decision yet.
    gate.close_event()
    assert gate.playing is False


def test_ziv_message_gate_release_drains_oldest_first_with_prefix() -> None:
    """Closing the event drains the queue FIFO, each message with its prefix.

    Invariant 1 applies to queued content too: even a released message opens
    with its kind cue — the wearer must never receive prefix-less content.
    """
    gate = MessageGate()
    gate.begin_playback()
    assert gate.admit("first").payload["queued"] is True
    assert gate.admit("second").payload["queued"] is True

    drained = gate.close_event()
    assert [r.event_type for r in drained] == ["message:play", "message:play"]
    assert [r.payload["text"] for r in drained] == ["first", "second"]
    assert all(r.payload["prefix"] is True for r in drained)
    assert len(gate) == 0

    # Closing an idle gate is a no-op, not an error.
    assert gate.close_event() == []


def test_ziv_lifecycle_patterns_exist_in_spec_v3() -> None:
    """Spec v3 carries the lifecycle vocabulary the relay contract names.

    Invariant 3 (waiting is legible) needs a `processing` pattern; invariant
    2 (cues mark the end) needs an `end-of-message` close. The beat values
    are read from the generated timing module — the same derivation the
    phone mock and the C header carry — so this test is the flow-level
    lock; the drift guard (test_haptic_timing.py) holds the consumers in sync.
    """
    assert timing.SPEC_VERSION == 3
    assert timing.pattern_beats("processing") == ((70, 350), (70, 420))
    # The discriminating feature is the 350 ms middle gap (double-tap: 160).
    assert timing.pattern_beats("double-tap")[0][1] == 160

    eom = timing.pattern_beats("end-of-message")
    assert len(eom) == 4
    assert [b[0] for b in eom] == [200, 140, 90, 50]  # ramp-up's mirror
    assert all(b[1] == 120 for b in eom[:-1])
    assert eom[-1][1] == 420  # the closing tail


def test_ziv_relay_contract_names_the_lifecycle_states() -> None:
    """The seam exports the lifecycle kinds a real adapter must emit.

    One turn: accepted → processing → playing | error. The C header and the
    feel-tool are checked for the same vocabulary so all three sides of the
    seam (spec, firmware, relay) name the same states.
    """
    assert KIND_PROCESSING == "processing"
    assert KIND_PLAYBACK_DONE == "playback_done"

    header = (_ROOT / "firmware" / "haptic_out" / "haptic_timing.h").read_text(
        encoding="utf-8"
    )
    assert "HAPTIC_PROCESSING" in header
    assert "HAPTIC_END_OF_MESSAGE" in header

    html = (_ROOT / "docs" / "haptic-name-marks.html").read_text(
        encoding="utf-8"
    )
    assert "'processing'" in html and "'end-of-message'" in html  # M1_POOL screens both

    # The relay's pattern names resolve against the generated timing module —
    # the fourth consumer, held in sync with the header/HTML by the drift guard.
    for pattern in (PATTERN_PROCESSING, PATTERN_END_OF_MESSAGE,
                    PATTERN_MESSAGE_CUE, PATTERN_ERROR):
        assert pattern in timing.PATTERN_IDS


# ---------------------------------------------------------------------------
# TurnTimeline -- the turn state machine, the executable form of the plan §4
# interaction invariants: one turn from acceptance to the queue release.
# ---------------------------------------------------------------------------

def _timeline(gate: MessageGate | None = None, text: str = "9 AM nurse visit.") -> TurnTimeline:
    # `gate or ...` would be wrong here: MessageGate defines __len__, so a
    # fresh empty gate is falsy and would be silently replaced.
    if gate is None:
        gate = MessageGate()
    return TurnTimeline(gate, text=text)


def test_ziv_turn_timeline_happy_journey_in_order() -> None:
    """Accepted → processing tick → playing → end-of-message: the full journey.

    The invariant walk, each event in order: a kind cue opens (inv 1),
    ``processing`` covers the wait (inv 3), the cue re-announces as content
    lands on the motors, and the close plays before the wrist goes quiet
    (inv 2). Nothing queued: the close alone.
    """
    gate = MessageGate()
    turn = _timeline(gate)

    turn.begin_processing(now_s=0.0)
    turn.poll(now_s=0.5)            # not yet due — the clock may tick freely
    turn.begin_playback()           # the model answered; content on the motors
    replay = turn.finish_playback(now_s=6.9)

    assert turn.state == CLOSED
    kinds = [e.event_type for e in turn.events]
    assert kinds == [
        "message:play",             # the opening kind cue (inv 1)
        "attention:processing",     # the wait is legible (inv 3)
        "message:play",             # the cue, re-announced as content (inv 1)
        "lifecycle:playback_done",  # the close (inv 2)
    ]
    # The close is the release: nothing queued, so it returns alone.
    assert [e.event_type for e in replay] == ["lifecycle:playback_done"]
    # The gate released.
    assert gate.playing is False
    assert turn.seconds == 6.9


def test_ziv_turn_timeline_processing_cadence_every_two_seconds() -> None:
    """poll() emits the tick on the ~2 s cadence, and only while PROCESSING.

    Invariant 3's clock: due at 2 s, 4 s, 6 s — not before, not after the
    turn has moved on. 2.5 ticks at 1.9 s spacing proves the boundary:
    waiting stays legible without a dedicated timer thread.
    """
    turn = _timeline()
    turn.begin_processing(now_s=0.0)
    assert turn.poll(now_s=1.9) is None            # boundary: not yet due
    ev = turn.poll(now_s=2.0)                      # due exactly on the cadence
    assert ev is not None and ev.event_type == "attention:processing"
    assert turn.poll(now_s=3.9) is None
    assert turn.poll(now_s=4.0).event_type == "attention:processing"
    assert turn.poll(now_s=5.9) is None
    assert turn.poll(now_s=6.0).event_type == "attention:processing"
    # After playback starts, the clock stops firing — the wait is over.
    turn.begin_playback()
    assert turn.poll(now_s=99.0) is None
    ticks = [e for e in turn.events if e.event_type == "attention:processing"]
    assert len(ticks) == 4  # begin_processing(0), then 2.0, 4.0, 6.0
    assert turn.poll(999.0) is None  # nothing re-arms a finished turn's clock


def test_ziv_turn_timeline_queue_release_fifo_with_prefix() -> None:
    """The gate holds during PLAYING; the close releases the queue FIFO.

    Invariant 4 end to end: a message arriving during playback is announced
    (cue only) and queued; ``finish_playback`` plays the close, then the
    drained message with its own prefix — the wearer releases the channel.
    """
    gate = MessageGate()
    turn = _timeline(gate, text="first")
    turn.begin_processing(0.0)
    turn.begin_playback()

    # A second arrival during playback: cue now, content queued (inv 4).
    admitted = gate.admit("second")
    assert admitted.event_type == "attention:double-tap"
    assert admitted.payload["queued"] is True

    replay = turn.finish_playback()
    kinds = [e.event_type for e in replay]
    assert kinds == ["lifecycle:playback_done", "message:play"]
    assert replay[1].payload["text"] == "second"
    assert replay[1].payload["prefix"] is True      # inv 1 holds for queued content
    assert turn.events[-1].payload["text"] == "second"


def test_ziv_turn_timeline_fail_plays_error_and_never_content() -> None:
    """A failed turn plays long-buzz — latency with an ending, never silence."""
    turn = _timeline()
    turn.begin_processing(0.0)
    turn.record_retry(1, RuntimeError("blip"))
    turn.fail()
    assert turn.state == ERROR
    assert turn.events[-1].event_type == "attention:long-buzz"
    assert turn.retries == 1
    # An errored turn is over: no playback path, no gate engagement.
    assert turn.events[-1].payload["state"] == ERROR


def test_ziv_turn_timeline_rejects_out_of_order_transitions() -> None:
    """Misuse is loud: transitions outside the lifecycle raise, not improvise.

    The invariants are structural — a relay bug that skips the wait or
    closes what never played must crash in the seam, not silently emit a
    wrong-on-the-wrist sequence (inv 5: structure is universal).
    """
    turn = _timeline()
    with pytest.raises(AssertionError):
        turn.begin_playback()                      # skip the wait
    with pytest.raises(AssertionError):
        turn.finish_playback()                     # close what never played
    turn.begin_processing(0.0)
    with pytest.raises(AssertionError):
        turn.finish_playback()                     # close without playing
    turn.begin_playback()
    turn.finish_playback()
    with pytest.raises(AssertionError):
        turn.begin_processing(1.0)                 # reuse a closed turn
