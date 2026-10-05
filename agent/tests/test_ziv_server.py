"""Tests for agent/ziv_server.py — the phone-as-dev-band relay (relay v0).

Hermetic, like the rest of the Ziv suite: no real phone, no network beyond
the in-process ASGI/WS test transport. What is proven:

* the full turn journey arrives on the wire in the wearer-visible order —
  cue → processing ticks → cue-as-content → cells → close (TurnTimeline's
  ordering, rendered as vibrate patterns);
* the queue-don't-interrupt invariant holds across HTTP calls: a second
  message during a turn gets the cue-only path and replays after the close
  with its own full journey;
* the vibrate patterns are the generated module's beats inverted — the same
  numbers the firmware header plays (zero hand-copied timing);
* /api/ziv/timing exposes the generated module verbatim;
* the agent path: a reminder scheduled as an *intent* is composed into a line
  by a live NVIDIA open model on Nebius Token Factory (HTTP mocked; the wire
  request asserted) and the model's own words are what the turn spells; with no
  key the promise still fires verbatim, labelled ``text_echo`` so the log never
  claims a model ran when none did;
* /inject/audio (the audio seam, held as asset): ``audio_b64`` goes out as an
  OpenAI ``input_audio`` content part — raw base64 in ``data``, the container
  named in ``format`` — and the transcript takes the same turn; it answers 503
  without a key or without an audio-capable endpoint configured, 502 with the
  provider's own words otherwise, and the ``simulate`` stub keeps it keyless;
* auth: when ZIV_RELAY_TOKEN is set, bad/missing bearer tokens and WS tokens
  are rejected (monkeypatched — no env mutation).
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT / "agent"), str(_ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import haptic_timing_gen as timing  # noqa: E402
import ziv_server as zs  # noqa: E402
from fastapi import HTTPException  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A fresh server per test: empty hub, empty gate, fast fake model —
    and a fresh store in a temp dir, so no test ever touches the real
    wearer files under ``agent/ziv_data/`` (hermetic end to end).

    The TestClient runs as a context manager — its portal is what the
    websocket test sessions run on.
    """
    import ziv_store as zstore
    d = tmp_path / "ziv_data"
    d.mkdir()
    monkeypatch.setattr(zstore, "DATA_DIR", d)
    monkeypatch.setattr(zs, "inbox", zs.MessageInbox())
    monkeypatch.setattr(zs, "memory", zs.WearerMemory())
    # The durable schedule is store-backed now: swap in a fresh one over the
    # same temp DATA_DIR, so tests never touch the real wearer files.
    monkeypatch.setattr(zs, "scheduled", zs.ScheduledReminders())
    zs.hub.devices.clear()
    zs.gate = zs.MessageGate()
    zs.queue_rejections.reset()
    prev = zs.FAKE_MODEL_SECONDS
    zs.FAKE_MODEL_SECONDS = 0.3
    with TestClient(zs.app) as c:
        yield c
    zs.FAKE_MODEL_SECONDS = prev
    zs.hub.devices.clear()
    zs.gate = zs.MessageGate()
    zs.queue_rejections.reset()


@contextmanager
def _attach(client: TestClient):
    """Attach one dev band and consume the hello frame.

    The session must be entered before any receive — its portal is set in
    ``__enter__`` — so this is a context manager, not a helper that returns
    a bare session.
    """
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["spec_version"] == timing.SPEC_VERSION
        yield ws


def _vibrate_ms(pattern_id: str) -> list[int]:
    """Expected vibrate pattern, derived the same way the server derives it."""
    out = []
    for buzz, gap in timing.pattern_beats(pattern_id):
        out.append(buzz)
        out.append(gap)
    return out


# ---------------------------------------------------------------------------
# The wearer's pace, made observable
#
# Every dwell the relay owes the wrist goes through ``ziv_server._dwell``.
# Real dwells make the suite read wall-clock minutes, so tests that are about
# *ordering* rather than pacing shorten them here — and ``test_pump_uses_the_
# wearer_pace`` below reads the same seam to assert the real numbers.
# ---------------------------------------------------------------------------

def _instant_dwells(monkeypatch) -> None:
    """Make every dwell instant — for tests about ordering, not timing."""

    async def fake(_seconds: float) -> None:
        return None

    monkeypatch.setattr(zs, "_dwell", fake)


def _yielding_dwells(monkeypatch) -> None:
    """Make dwells cost no wall-clock but still yield the event loop.

    ``asyncio.gather`` only interleaves its tasks where one of them actually
    awaits something that suspends. With every dwell a plain ``return`` the
    first turn runs to completion before the second one is ever scheduled —
    which would make a concurrency test measure nothing at all (and is
    exactly how a bug like this hides: the bursts that break the bound are
    the ones where turns are genuinely in flight together).
    """
    real_sleep = asyncio.sleep

    async def fake(_seconds: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(zs, "_dwell", fake)


def _skip_cell_dwells(monkeypatch, *, keep: float = 0.06) -> None:
    """Keep the short processing tick real, drop the long cell/mark dwells.

    A test that has to land *inside* a multi-second model wait still needs
    that wait to pass in real time, but has no interest in replaying nine
    half-second cells while it does.
    """
    real = zs._dwell

    async def fake(seconds: float) -> None:
        if seconds <= keep:
            await real(seconds)

    monkeypatch.setattr(zs, "_dwell", fake)


def _record_dwells(monkeypatch) -> list[float]:
    """Replace the dwells with a recorder and return the list it fills."""
    seen: list[float] = []

    async def fake(seconds: float) -> None:
        seen.append(seconds)

    monkeypatch.setattr(zs, "_dwell", fake)
    return seen


def _detach(device) -> None:
    """Drop a test band from the hub — the hub may have dropped it first.

    ``DeviceHub.broadcast`` detaches a socket that raises on send, so a
    band that dies mid-turn removes itself; removing it again would be an
    error rather than a cleanup.
    """
    if device in zs.hub.devices:
        zs.hub.devices.remove(device)


# ---------------------------------------------------------------------------
# The turn journey, over the wire
# ---------------------------------------------------------------------------

def test_turn_journey_reaches_the_wire_in_order(client):
    """cue → processing → cue-as-content → cells → close, in that order."""
    with _attach(client) as ws:
        resp = client.post("/api/ziv/message", json={"text": "Taxi here"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["event"] == "turn_complete"
        assert body["drained"] == 0

        # "Taxi here" spells 8 letters: cue, tick, cue, text, 8 cells, close
        # — 13 frames total.
        frames = [ws.receive_json() for _ in range(13)]
        kinds = [(f["type"], f.get("pattern")) for f in frames]

        assert kinds == [
            ("haptic", "double-tap"),      # opening kind cue (inv 1)
            ("haptic", "processing"),      # the wait is legible (inv 3)
            ("haptic", "double-tap"),      # cue re-announced as content
            ("text", None),                # narration + cell list
            *[("cell", None)] * 8,         # t,a,x,i,h,e,r,e
            ("haptic", "end-of-message"),  # the close (inv 2)
        ]

        # The vibrate patterns are the module's beats, inverted — the
        # firmware's numbers, not hand-copied ones.
        assert frames[0]["ms"] == _vibrate_ms("double-tap")
        assert frames[1]["ms"] == _vibrate_ms("processing")
        assert frames[1]["ms"] == [70, 350, 70, 420]
        assert frames[-1]["ms"] == _vibrate_ms("end-of-message")
        assert frames[-1]["why"] == "close"


def test_processing_ticks_repeat_on_the_wire(client):
    """With a visible fake-model wait, the phone feels the ellipsis repeat."""
    zs.FAKE_MODEL_SECONDS = 2.5  # one cadence tick lands at ~2.0 s
    with _attach(client) as ws:
        client.post("/api/ziv/message", json={"text": "hi"})
        # Read until the close marker — never a fixed frame count, which
        # blocks forever when the wait boundary lands one tick short.
        haptics: list[str] = []
        while True:
            f = ws.receive_json()
            if f["type"] == "haptic":
                haptics.append(f["pattern"])
                if f["pattern"] == "end-of-message":
                    break
        # The begin tick, at least one cadence tick while waiting, the cue
        # re-announced as content, then the close. Waiting was legible.
        assert haptics[0] == "double-tap"
        assert haptics.count("processing") >= 2  # begin + cadence repeat
        assert haptics[-2] == "double-tap"
        assert haptics[-1] == "end-of-message"


def test_second_message_during_turn_queues_and_replays_full_journey(client):
    """Invariant 4 across HTTP calls: mid-playback arrival queues, then replays.

    The first POST runs in a worker thread so the second can fire while the
    first turn is spelling its cells (the gate holds during PLAYING). The
    second POST returns the queue decision (cue only); after the first
    turn's close, the replay plays its own cue → cells → close — a full
    event, not a bare cue (invariants 1 + 2 hold for queued content).
    """
    zs.FAKE_MODEL_SECONDS = 0.05  # reach PLAYING fast; the cells dwell is the window
    with _attach(client) as ws:
        results = {}

        def _first() -> None:
            results["first"] = client.post("/api/ziv/message", json={"text": "first"})

        worker = threading.Thread(target=_first, daemon=True)
        worker.start()
        time.sleep(0.6)  # the first turn is now spelling "first" (≈3 s of cells)

        second = client.post("/api/ziv/message", json={"text": "second"})
        assert second.status_code == 200
        assert second.json()["queued"] is True
        assert second.json()["queue_len"] == 1

        worker.join(timeout=30)
        assert results["first"].json()["drained"] == 1

        # The first turn's frames, then the replay (cue, text+cells, close).
        # receive_json() has no timeout in this starlette; the loop is bounded
        # by counting the two closes (first turn's, then the replay's — the
        # replay is the last event the turn emits).
        saw = []
        closes = 0
        while closes < 2:
            f = ws.receive_json()
            saw.append((f["type"], f.get("pattern"), f.get("text")))
            if f["type"] == "haptic" and f["pattern"] == "end-of-message":
                closes += 1

        assert ("haptic", "double-tap", None) in saw  # the queued message's cue
        assert ("text", None, "queued: second") in saw
        # The replay ended with its own close — the event marker.
        assert saw[-1][1] == "end-of-message"


# ---------------------------------------------------------------------------
# The timing bootstrap: one derivation everywhere
# ---------------------------------------------------------------------------

def test_timing_endpoint_serves_the_generated_module(client):
    r = client.get("/api/ziv/timing")
    assert r.status_code == 200
    body = r.json()
    assert body["spec_version"] == timing.SPEC_VERSION
    assert body["patterns"]["processing"] == [list(b) for b in timing.pattern_beats("processing")]
    assert body["patterns"]["end-of-message"] == [list(b) for b in timing.pattern_beats("end-of-message")]
    assert body["letters"]["z"] == timing.cell_ms("z")
    assert body["mark"] == timing.PREFIX_MARK
    assert body["mark_cells"] == list(timing.MARK_CELLS[timing.PREFIX_MARK])
    assert body["cell_gap_ms"] == timing.CELL_GAP_DEFAULT_MS
    assert body["spell_max_letters"] == timing.SPELL_MAX_LETTERS


def test_inject_audio_runs_the_same_turn_as_message(client):
    """The Omni spike seam produces the same wearer-visible journey."""
    with _attach(client) as ws:
        r = client.post("/inject/audio", json={"simulate": "Pills at nine"})
        assert r.status_code == 200
        assert r.json()["source"] == "audio_stub"
        assert r.json()["event"] == "turn_complete"

        frames = [ws.receive_json() for _ in range(6)]
        assert frames[0]["type"] == "haptic"
        assert frames[0]["pattern"] == "double-tap"


def test_message_requires_text(client):
    r = client.post("/api/ziv/message", json={})
    assert r.status_code == 422


def test_band_vanishing_mid_turn_conflicts(client, monkeypatch):
    """A band that detaches mid-turn: 409, not a silent half-turn.

    The turn starts with a device attached; the hub empties just before the
    first frame is pushed — ``_push`` raises, the POST answers 409.
    """
    real_push = zs._push

    async def push_then_vanish(frame):
        zs.hub.devices.clear()  # the band leaves right before delivery
        return await real_push(frame)

    monkeypatch.setattr(zs, "_push", push_then_vanish)
    with _attach(client):
        r = client.post("/api/ziv/message", json={"text": "x"})
    assert r.status_code == 409
    assert "no dev band" in r.json()["detail"]


class _ArrivingMidDelivery:
    """A band that lets a live message arrive while a stored one is played.

    ``inject`` fires the moment the delivery starts spelling its content —
    before the close, which is where the gate's queue is decided — and
    ``die_after`` takes the band down right there, so the drain that follows
    has nobody to play it on.
    """

    def __init__(self, inject=None, die_after: bool = False) -> None:
        import json as _json

        self._json = _json
        self.frames: list[dict] = []
        self.inject = inject
        self.die_after = die_after
        self.arrived = False

    async def send_text(self, s: str) -> None:
        frame = self._json.loads(s)
        self.frames.append(frame)
        if (
            not self.arrived
            and frame.get("type") == "text"
            and frame.get("text", "").startswith("queued: ")
        ):
            self.arrived = True
            if self.inject is not None:
                self.inject()
            if self.die_after:
                raise ConnectionResetError("band vanished")


def test_inbox_delivery_drains_what_arrived_behind_it(client, fresh_store, monkeypatch):
    """A stored backlog does not strand the messages that cue behind it.

    ``deliver_inbox_one`` owns the channel, so it also owns whatever queued
    during it. Before this, a text that arrived mid-delivery cued on the
    wearer's wrist and then sat in the gate until the *next* inbound message
    arrived to drain it — a "something arrived" cue with no content behind
    it, which is the loud-not-silent rule broken quietly.
    """
    _instant_dwells(monkeypatch)
    zs.inbox.offer("stored one")

    band = _ArrivingMidDelivery(inject=lambda: zs.gate.admit("arrived mid delivery"))
    zs.hub.devices.append(band)
    try:
        entry = asyncio.run(zs.deliver_inbox_one())
    finally:
        _detach(band)

    assert entry is not None and entry["text"] == "stored one"
    texts = [f.get("text", "") for f in band.frames if f["type"] == "text"]
    assert any(t.startswith("queued: stored one") for t in texts)
    assert any(t.startswith("queued: arrived mid delivery") for t in texts), (
        "the text that cued during the delivery never got its content"
    )
    assert len(zs.gate) == 0, "the drain left the queue occupied"
    assert zs.gate.playing is False


def test_inbox_delivery_strands_what_it_could_not_play(client, fresh_store, monkeypatch):
    """The band dies mid-drain: the queued text goes to the inbox, not limbo.

    The gate is a *minutes*-long buffer. When the band that was going to
    play a drained text vanishes, nobody is left who ever will, so the text
    has to leave the gate — otherwise it occupies one of MAX_QUEUED's slots
    until the process restarts, pushing real senders into 429s for a message
    nobody is going to deliver. The inbox is where undelivered content goes.
    """
    _instant_dwells(monkeypatch)
    zs.inbox.offer("stored one")

    band = _ArrivingMidDelivery(
        inject=lambda: zs.gate.admit("arrived mid delivery"), die_after=True
    )
    zs.hub.devices.append(band)
    try:
        with pytest.raises(zs._NoDevices):
            asyncio.run(zs.deliver_inbox_one())
    finally:
        _detach(band)

    assert zs.gate.playing is False, "a dead delivery must release the channel"
    assert len(zs.gate) == 0, "the gate kept a text nobody will ever play"
    pending = [e["text"] for e in zs.inbox.pending()]
    # The entry was never marked delivered (its close never landed) and the
    # arrival was handed on — both still owed to the wearer, neither lost.
    assert "stored one" in pending
    assert "arrived mid delivery" in pending


def test_inbox_delivery_declines_while_a_turn_holds_the_channel(
    client, fresh_store, monkeypatch
):
    """A delivery never interleaves into a turn in flight.

    The entry stays pending (it is durable, so declining costs a delay and
    nothing else) and the next attach offers it again.
    """
    _instant_dwells(monkeypatch)
    zs.inbox.offer("stored one")
    zs.gate.begin_playback()  # a turn owns the channel
    try:
        assert asyncio.run(zs.deliver_inbox_one()) is None
        assert zs.inbox.count() == 1, "a declined delivery must stay pending"
    finally:
        zs.gate.close_event()  # the turn ends and frees the channel

    # ...and with the channel free again the same entry plays.
    band = _RecordingDevice()
    zs.hub.devices.append(band)
    try:
        assert asyncio.run(zs.deliver_inbox_one()) is not None
    finally:
        _detach(band)
    assert zs.inbox.count() == 0


def test_inbox_delivery_drains_even_when_nothing_is_stored(client, fresh_store, monkeypatch):
    """The last delivery of a backlog still plays what cued behind it.

    The attach loop drains until the inbox is empty and then stops asking.
    If the final call released the channel by throwing away whatever it
    drained, a message that arrived during the last delivery would cue on
    the wrist and then vanish — silently, which is the one outcome the
    queue-don't-interrupt contract forbids.
    """
    _instant_dwells(monkeypatch)
    zs.inbox.offer("stored one")

    band = _ArrivingMidDelivery(inject=lambda: zs.gate.admit("arrived mid delivery"))
    zs.hub.devices.append(band)
    try:
        assert asyncio.run(zs.deliver_inbox_one()) is not None
        # The inbox is empty now; the final call reports "nothing left"...
        assert asyncio.run(zs.deliver_inbox_one()) is None
    finally:
        _detach(band)

    texts = [f.get("text", "") for f in band.frames if f["type"] == "text"]
    assert any(t.startswith("queued: arrived mid delivery") for t in texts), (
        "the drain was discarded when the inbox ran dry"
    )
    assert len(zs.gate) == 0
    assert zs.inbox.count() == 0


class _SucceedingThenDying:
    """A band that queues a text mid-content, then dies at the drain.

    It models the exact race a reservation must survive: the turn pushes its
    close (releasing the channel), starts replaying what it drained, and an
    arrival takes the channel over *while that replay is still in flight*.
    """

    def __init__(self) -> None:
        self.queued = False
        self.handover = False

    async def send_text(self, s: str) -> None:
        frame = json.loads(s)
        if not self.queued and frame.get("type") == "cell":
            self.queued = True
            zs.gate.admit("queued behind the doomed turn")
        if frame.get("why") == "queued replay cue" and not self.handover:
            # The gate is idle again the instant finish_playback() released
            # it. This is exactly what an arriving run_message_turn does
            # when it finds the channel idle: reserve it, then wait on the
            # turn lock this turn is still holding.
            self.handover = True
            self.decision = zs.gate.admit("arrived after the close")
            zs.gate.admit("waiting behind the new arrival")
            raise ConnectionResetError("band vanished")


def test_an_aborting_turn_does_not_release_the_next_arrival_s_channel(
    client, fresh_store, monkeypatch
):
    """A turn that dies during its replays must not touch what isn't its.

    The channel is released at the close, but the turn keeps replaying
    drained texts long afterwards. If its failure path calls ``abort()``
    unconditionally it releases the channel an arrival has *already*
    legitimately reserved — and drains that arrival's queue into this turn's
    inbox. Observed on the code this test guards: ``gate.playing`` went
    False while the new arrival owned it, and its queued text was silently
    relocated to the inbox, where it waits for a phone attach instead of
    playing after the next close.
    """
    _instant_dwells(monkeypatch)
    zs.FAKE_MODEL_SECONDS = 0.0

    band = _SucceedingThenDying()
    zs.hub.devices.append(band)
    try:
        with pytest.raises(zs._NoDevices):
            asyncio.run(zs.run_message_turn("the doomed turn"))
    finally:
        _detach(band)

    assert band.decision.event_type == "message:play", (
        "the handover must be a real reservation for this test to mean anything"
    )
    assert zs.gate.playing is True, (
        "the aborting turn released a channel it no longer owned"
    )
    assert len(zs.gate) == 1, "and it drained the new arrival's queue"
    # Only the dying turn's OWN undelivered text was stored.
    assert [e["text"] for e in zs.inbox.pending()] == [
        "queued behind the doomed turn"
    ]


class _VanishingDevice:
    """A hub device that dies after ``alive_frames`` sends — a phone locking,
    the tab closing, the network dropping mid-message."""

    def __init__(self, alive_frames: int) -> None:
        self.alive_frames = alive_frames
        self.sent = 0

    async def send_text(self, s: str) -> None:
        self.sent += 1
        if self.sent > self.alive_frames:
            raise ConnectionResetError("band vanished")


# ---------------------------------------------------------------------------
# The channel is held for the WHOLE turn — the reservation IS the decision
#
# The bug these guard is that ``gate.admit`` used to *suggest* a play and the
# channel only went busy at ``turn.begin_playback()`` — after the model
# round-trip. Every window before that first cell (3 s of fake model by
# default, up to the 30 s provider timeout in production) was an idle gate,
# and 20 simultaneous arrivals got 20 × ``message:play``: all of them
# blocked on the turn lock and all of them played, so MAX_QUEUED was
# unreachable exactly when it was most needed.
# ---------------------------------------------------------------------------

def test_burst_of_arrivals_plays_one_and_bounds_the_rest(client, monkeypatch):
    """20 simultaneous arrivals against an idle gate: ONE plays, the queue
    fills to MAX_QUEUED, everything past it is refused loudly.

    Before the reservation, this returned 20 ``turn_complete``s with an
    empty queue — the bound was decorative.
    """
    _yielding_dwells(monkeypatch)
    zs.FAKE_MODEL_SECONDS = 0.05
    rec = _RecordingDevice()
    zs.hub.devices.append(rec)
    n = 20
    try:
        results = asyncio.run(_gather_turns(n))
    finally:
        _detach(rec)

    played = [r for r in results if isinstance(r, dict) and r.get("event") == "turn_complete"]
    queued = [r for r in results if isinstance(r, dict) and r.get("queued")]
    refused = [r for r in results if isinstance(r, HTTPException)]

    assert len(played) == 1, f"only one turn may hold the channel, got {len(played)}"
    assert len(queued) == zs.MessageGate.MAX_QUEUED
    assert len(refused) == n - 1 - zs.MessageGate.MAX_QUEUED
    assert all(e.status_code == 429 for e in refused)
    # Every text is accounted for exactly once: played, queued, or refused.
    assert len(played) + len(queued) + len(refused) == n
    # ...and the gate ends the turn empty and idle — nothing leaked.
    assert len(zs.gate) == 0
    assert zs.gate.playing is False
    # Every queued text was actually replayed, not just counted.
    spells = [f["text"] for f in rec.frames
              if f["type"] == "text" and f["text"].startswith("queued: ")]
    assert len(spells) == zs.MessageGate.MAX_QUEUED


async def _gather_turns(n: int) -> list[object]:
    """Fire n turns at once and report each one's outcome.

    ``run_message_turn`` raises HTTPException(429) rather than returning a
    refusal, so the gather collects them instead of stopping at the first.
    """
    async def one(i: int) -> object:
        try:
            return await zs.run_message_turn(f"burst-{i}")
        except HTTPException as exc:
            return exc

    return list(await asyncio.gather(*(one(i) for i in range(n))))


def test_arrival_during_the_model_wait_queues_instead_of_barging(client, monkeypatch):
    """The gate is NOT idle while the model thinks.

    The window between ``admit`` and the first cell is the whole model
    round-trip — ``FAKE_MODEL_SECONDS`` here, up to the 30 s provider
    timeout in production. Before the fix the gate was still idle for all
    of it, so a message arriving mid-wait was answered ``message:play`` and
    merely waited behind the turn lock: it jumped the queue it should have
    joined. Now it cues (the wearer learns something arrived) and its
    content waits for the close.
    """
    _skip_cell_dwells(monkeypatch)  # keep the processing tick, drop the cells'
    zs.FAKE_MODEL_SECONDS = 1.2  # a real, observable processing window
    rec = _RecordingDevice()
    zs.hub.devices.append(rec)
    try:
        outcome, held_during_wait = asyncio.run(_arrive_during_the_wait())
    finally:
        _detach(rec)

    assert outcome["event"] == "attention:double-tap"
    assert outcome["queued"] is True
    assert held_during_wait, (
        "the gate was idle while the model was still thinking — the arrival "
        "barged into the turn instead of queueing behind it"
    )
    # ...and the turn it queued behind went on to finish normally, draining it.
    patterns = [f.get("pattern") for f in rec.frames if f["type"] == "haptic"]
    assert patterns[-1] == "end-of-message"
    assert len(zs.gate) == 0
    assert any(t.startswith("queued: second") for t in
               (f.get("text", "") for f in rec.frames if f["type"] == "text"))


async def _arrive_during_the_wait() -> tuple[dict[str, object], bool]:
    """Post one message while a first turn is inside its model wait."""
    first = asyncio.ensure_future(zs.run_message_turn("first"))
    while not zs.gate.playing and not first.done():
        # The gate flips to held the moment admit answers message:play —
        # which is *before* the wait we are trying to land inside.
        await asyncio.sleep(0.01)
    await asyncio.sleep(zs.FAKE_MODEL_SECONDS / 2)
    assert not first.done(), "the first turn finished before the arrival"
    held = zs.gate.playing
    second = await zs.run_message_turn("second")
    await first
    return second, held


def test_band_vanishing_mid_turn_releases_the_gate(client):
    """The wedge: a band dying mid-playback must not brick the relay.

    Regression for a real bug. ``turn.begin_playback()`` sets the gate
    playing and only ``finish_playback()`` clears it — so a turn that raised
    between the two (here: the phone locks while cells are being spelled)
    left ``playing`` True forever. Every later arrival then queued against a
    wrist that was not reading, and after MAX_QUEUED the relay refused
    everything until restart. This is the sequence that did it: cue,
    processing, cue-as-content, then the band dies during the cells.
    """
    zs.FAKE_MODEL_SECONDS = 0.05  # reach PLAYING fast; the dwell is the window
    dying = _VanishingDevice(alive_frames=3)  # dies just after begin_playback
    zs.hub.devices.append(dying)  # attach() is async; the list is its state
    try:
        with pytest.raises(zs._NoDevices):
            asyncio.run(zs.run_message_turn("hello"))
    finally:
        zs.hub.devices.clear()

    # THE FIX: the channel is released, so the relay is usable again.
    assert zs.gate.playing is False, (
        "the gate is wedged playing — every later arrival would queue "
        "against a wrist that is not reading, and the relay would refuse "
        "everything after the cap until restart"
    )
    # ...and the next arrival PLAYS instead of queueing.
    assert zs.gate.admit("after the crash").event_type == "message:play"


def test_band_vanishing_mid_turn_stores_the_in_flight_text(client, fresh_store):
    """The other half of the same bug: the undelivered text is not lost.

    The abandoned turn's text was in NEITHER the queue (the gate had already
    taken it) NOR the inbox — it was simply gone, which contradicts the
    relay's "never a silent drop" contract. It must now be stored, so the
    next attach delivers it as a full event.
    """
    zs.FAKE_MODEL_SECONDS = 0.05
    dying = _VanishingDevice(alive_frames=3)
    zs.hub.devices.append(dying)
    try:
        with pytest.raises(zs._NoDevices):
            asyncio.run(zs.run_message_turn("call mum back"))
    finally:
        zs.hub.devices.clear()

    pending = [e["text"] for e in zs.inbox.pending()]
    assert "call mum back" in pending, (
        "the in-flight text was silently dropped — it was admitted by the "
        "gate and never played, so nothing else would ever deliver it"
    )
    # Stored once, not once per layer that noticed the failure.
    assert pending.count("call mum back") == 1


def test_band_vanishing_mid_turn_strands_queued_messages_not_drops_them(client, fresh_store):
    """Texts queued behind the doomed turn survive it too.

    They were queued (so the gate held them), but an abort drains the gate —
    the texts must come back to the caller for re-offering rather than
    vanishing with the queue. The arrivals land while the doomed turn is
    spelling cells, which is exactly the window that used to strand them.
    """
    zs.FAKE_MODEL_SECONDS = 0.05
    # Survives cue + processing + cue-as-content + text + the first cell;
    # dies on the next push, so the gate is already playing.
    dying = _VanishingDevice(alive_frames=5)
    zs.hub.devices.append(dying)

    async def scenario() -> None:
        task = asyncio.ensure_future(zs.run_message_turn("in flight"))
        # Let the turn reach PLAYING, then queue arrivals behind it.
        while not zs.gate.playing:
            await asyncio.sleep(0.01)
        for text in ("queued one", "queued two"):
            assert zs.gate.admit(text).event_type == "attention:double-tap"
        assert len(zs.gate) == 2, "both arrivals are queued behind the turn"
        with pytest.raises(zs._NoDevices):
            await task

    try:
        asyncio.run(scenario())
    finally:
        zs.hub.devices.clear()
        zs.gate = zs.MessageGate()

    pending = [e["text"] for e in zs.inbox.pending()]
    # The in-flight text AND both queued texts all came back: three stored,
    # none dropped, none stored twice.
    assert set(pending) == {"in flight", "queued one", "queued two"}
    assert len(pending) == 3, "a stranded text was stored twice"


def test_health_counts_devices_and_gate(client):
    assert client.get("/api/ziv/health").json()["devices"] == 0
    with _attach(client):
        h = client.get("/api/ziv/health").json()
        assert h["devices"] == 1
        assert h["spec_version"] == timing.SPEC_VERSION
        assert h["gate_queue"] == 0
        # The client's queue badge divides by this — the server owns the cap
        # (no client-side constant), like the timing bootstrap.
        assert h["gate_queue_cap"] == zs.MessageGate.MAX_QUEUED


# ---------------------------------------------------------------------------
# Auth (monkeypatched — the env is not touched)
# ---------------------------------------------------------------------------

def test_auth_rejects_missing_and_bad_bearer(client, monkeypatch):
    monkeypatch.setattr(zs, "ZIV_RELAY_TOKEN", "sekrit")
    r = client.post("/api/ziv/message", json={"text": "x"})
    assert r.status_code == 401
    r = client.post("/api/ziv/message", json={"text": "x"},
                    headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    r = client.post("/api/ziv/message", json={"text": "x"},
                    headers={"Authorization": "Bearer sekrit"})
    # Relay v1: auth passed, no band attached → stored, not dropped.
    assert r.status_code == 200
    assert r.json()["event"] == "inbox:stored"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/ziv/schedule", {"text": "meds", "fire_at": 4102444800.0}),
        ("GET", "/api/ziv/schedule", None),
        ("DELETE", "/api/ziv/schedule", None),
        ("GET", "/api/ziv/ready", None),
        ("GET", "/api/ziv/inbox", None),
        ("DELETE", "/api/ziv/inbox", None),
        ("GET", "/api/ziv/prefs", None),
        ("POST", "/api/ziv/prefs", {"cell_gap_ms": 500}),
    ],
)
def test_auth_covers_every_route_that_carries_or_reveals_content(
    client, monkeypatch, method, path, body
):
    """Every content route is behind the bearer token, not just the sender's.

    The gap this closes: with ``ZIV_RELAY_TOKEN`` set, ``/api/ziv/message``
    and ``/inject/audio`` were gated, but the *readers* were not — an
    unauthenticated caller could read a private reminder's line out of the
    schedule and the wearer's whole inbox, and could clear either one. Who
    may send a message is who may read it; the rest is nobody.
    """
    monkeypatch.setattr(zs, "ZIV_RELAY_TOKEN", "sekrit")

    def call(headers=None):
        return client.request(method, path, json=body, headers=headers or {})

    assert call().status_code == 401, f"{method} {path} is open to anyone"
    assert call({"Authorization": "Bearer wrong"}).status_code == 401
    assert call({"Authorization": "Bearer sekrit"}).status_code == 200


def test_auth_leaves_the_bootstrap_routes_open(client, monkeypatch):
    """What stays open, and why: the PWA has to boot before it can hold a
    credential.

    ``/api/ziv/timing`` is the generated spec the client renders from and
    ``/api/ziv/health`` is the queue badge it polls — neither carries any
    message text. ``health`` is pinned content-free here so widening it
    stays a deliberate act rather than a side effect of adding a field.
    """
    monkeypatch.setattr(zs, "ZIV_RELAY_TOKEN", "sekrit")
    assert client.get("/api/ziv/timing").status_code == 200
    assert client.get("/ziv_client/index.html").status_code == 200

    h = client.get("/api/ziv/health")
    assert h.status_code == 200
    # Store something private first, then prove health cannot report it.
    client.post("/api/ziv/message", json={"text": "secret taxi fare"},
                headers={"Authorization": "Bearer sekrit"})
    client.post("/api/ziv/schedule", json={"text": "private reminder",
                                           "fire_at": 4102444800.0},
                headers={"Authorization": "Bearer sekrit"})
    body = h.json()
    assert "secret taxi fare" not in json.dumps(body)
    assert "private reminder" not in json.dumps(body)


def test_auth_rejects_bad_ws_token(client, monkeypatch):
    monkeypatch.setattr(zs, "ZIV_RELAY_TOKEN", "sekrit")
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?token=wrong") as ws:
            ws.receive_json()


def test_auth_accepts_good_ws_token(client, monkeypatch):
    monkeypatch.setattr(zs, "ZIV_RELAY_TOKEN", "sekrit")
    with client.websocket_connect("/ws?token=sekrit") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"


def test_client_page_is_served(client):
    r = client.get("/ziv_client/index.html")
    assert r.status_code == 200
    assert "Ziv dev band" in r.text


# ---------------------------------------------------------------------------
# Relay v1: the wearer's durable state (inbox + memory)
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_store():
    """The (already reset) store dir — for tests that need the path itself.

    The ``client`` fixture owns the per-test reset; this only exposes the dir.
    """
    import ziv_store as zstore
    return zstore.DATA_DIR


def test_message_with_no_band_is_stored_not_dropped(client, fresh_store):
    """Relay v1: no device attached → the inbox stores the message."""
    r = client.post("/api/ziv/message", json={"text": "taxi is here"})
    assert r.status_code == 200
    body = r.json()
    assert body["event"] == "inbox:stored"
    assert body["stored"] is True
    assert body["inbox_pending"] == 1
    assert client.get("/api/ziv/inbox").json()["count"] == 1


def test_inbox_is_delivered_on_next_attach(client, fresh_store):
    """Stored messages are offered on attach as full events, then marked.

    Delivery happens after hello; each replay is a self-naming turn — the
    mark (Z-I-V cells + the entry's source tail) opens it, then the stored
    content plays and only then is the entry marked delivered — a vanished
    band means redelivery, never loss.
    """
    client.post("/api/ziv/message", json={"text": "first stored"})
    client.post("/inject/audio", json={"simulate": "second stored"})
    assert client.get("/api/ziv/inbox").json()["count"] == 2

    with _attach(client) as ws:
        # hello is consumed by _attach; both replays follow on the wire.
        frames: list[dict] = []
        closes = 0
        while closes < 2:
            f = ws.receive_json()
            frames.append(f)
            if f["type"] == "haptic" and f["pattern"] == "end-of-message":
                closes += 1

        def section(start: int) -> tuple[list[dict], int]:
            """One replay's frames: its narration through its close."""
            end = next(
                i for i in range(start, len(frames))
                if frames[i]["type"] == "haptic"
                and frames[i]["pattern"] == "end-of-message"
            )
            return frames[start:end + 1], end + 1

        mark_cells = list(timing.MARK_CELLS[timing.PREFIX_MARK])

        # Replay 1 — a plain message: mark cells, the double-tap tail, then
        # the stored content as a queued delivery.
        s1, nxt = section(0)
        assert s1[0]["type"] == "text"
        assert s1[0]["text"] == "message: first stored"
        assert s1[0]["chars"] == [{"ch": ch, "ms": timing.cell_ms(ch)}
                                  for ch in mark_cells]
        assert [f["ch"] for f in s1 if f["type"] == "cell"][:3] == mark_cells
        tails = [(f["pattern"], f.get("why")) for f in s1
                 if f["type"] == "haptic"]
        assert tails[0] == ("double-tap", "message mark")
        assert tails[-1][0] == "end-of-message"
        assert any(t["type"] == "text" and t["text"].startswith("queued: first stored")
                   for t in s1)

        # Replay 2 — an audio-stub entry: same mark and double-tap tail
        # (transcribed speech replays as a message, whatever its origin).
        s2, _ = section(nxt)
        assert s2[0]["type"] == "text"
        assert s2[0]["text"] == "message: second stored"
        tails2 = [(f["pattern"], f.get("why")) for f in s2
                  if f["type"] == "haptic"]
        assert tails2[0] == ("double-tap", "message mark")
        assert tails2[-1][0] == "end-of-message"

        assert client.get("/api/ziv/inbox").json()["count"] == 0


def test_inbox_clear_and_pending_endpoint(client, fresh_store):
    client.post("/api/ziv/message", json={"text": "a"})
    client.post("/api/ziv/message", json={"text": "b"})
    pending = client.get("/api/ziv/inbox").json()
    assert pending["count"] == 2
    assert [e["text"] for e in pending["pending"]] == ["a", "b"]
    assert client.request("DELETE", "/api/ziv/inbox").json() == {"cleared": 2}
    assert client.get("/api/ziv/inbox").json()["count"] == 0


def test_prefs_roundtrip_and_clamp(client, fresh_store):
    """Parameters personal, structure universal: the wearer's pace is stored
    and clamped into the spec's envelope (the generated module owns it)."""
    assert client.get("/api/ziv/prefs").json()["cell_gap_ms"] == timing.CELL_GAP_DEFAULT_MS
    r = client.post("/api/ziv/prefs", json={"cell_gap_ms": 600})
    assert r.json()["cell_gap_ms"] == 600
    # New server state reads the same file (persistence).
    assert client.get("/api/ziv/prefs").json()["cell_gap_ms"] == 600
    # Out-of-envelope values clamp, not reject.
    assert client.post("/api/ziv/prefs", json={"cell_gap_ms": 10}).json()["cell_gap_ms"] == timing.CELL_GAP_MIN_MS
    assert client.post("/api/ziv/prefs", json={"cell_gap_ms": 99999}).json()["cell_gap_ms"] == timing.CELL_GAP_MAX_MS
    r = client.post("/api/ziv/prefs", json={})
    assert r.status_code == 422


def test_pump_uses_the_wearer_pace(client, fresh_store):
    """The playback gap the pump sleeps is the wearer's, not the default."""
    import asyncio
    client.post("/api/ziv/prefs", json={"cell_gap_ms": timing.CELL_GAP_MIN_MS})
    with _attach(client) as ws:
        r = client.post("/api/ziv/message", json={"text": "ok"})
        assert r.status_code == 200
        # Drain the frames; the turn must complete using the fast gap.
        while True:
            f = ws.receive_json()
            if f["type"] == "haptic" and f["pattern"] == "end-of-message":
                break
        body = r.json()
        assert body["event"] == "turn_complete"
        # 3 s model wait + 2 fast cells: well under the 420 ms default pace.
        assert body["seconds"] < zs.FAKE_MODEL_SECONDS + 1.5


def test_the_wearer_pace_lands_on_the_wire_as_real_dwells(
    client, fresh_store, monkeypatch
):
    """The cell gap is not just *read* — it is the gap the relay waits.

    Every dwell goes through ``ziv_server._dwell``, so recording that seam
    turns the pacing from an intention into an assertion: for every letter
    spelled, the relay waited exactly ``cell_ms(letter) + the wearer's gap``,
    derived from the same generated table the firmware plays. Before this
    seam existed nothing in the suite could say that, and a pace that was
    read but never awaited would have passed every test here.
    """
    _instant_dwells(monkeypatch)  # the waits are the subject, not the runtime
    zs.FAKE_MODEL_SECONDS = 0.05
    text = "pacing"
    gap_s = timing.CELL_GAP_DEFAULT_MS / 1000.0

    seen = _record_dwells(monkeypatch)
    rec = _RecordingDevice()
    zs.hub.devices.append(rec)
    try:
        asyncio.run(zs.run_message_turn(text))
    finally:
        zs.hub.devices.remove(rec)

    letters = [c for c in text.lower() if "a" <= c <= "z"]
    # The first dwell is the fake model's poll tick; the rest are the cells.
    assert seen[0] == 0.05
    assert len(seen[1:]) == len(letters)
    for ch, dwell in zip(letters, seen[1:]):
        assert dwell == pytest.approx(timing.cell_ms(ch) / 1000.0 + gap_s), (
            f"cell {ch!r} did not wait cell_ms + the wearer's gap"
        )
    # The wire carries the same numbers the dwell was built from.
    assert [f["ms"] for f in rec.frames if f["type"] == "cell"] == [
        timing.cell_ms(c) for c in letters
    ]


def test_moving_the_pace_moves_every_dwell_by_exactly_that_much(
    client, fresh_store, monkeypatch
):
    """Parameters are personal: one stored preference, every cell feels it.

    Structure universal, parameters personal — the spec owns the envelope
    and the wearer owns the value inside it. This is the executable half of
    that sentence: the SAME message, spelled twice, differs in every dwell
    by exactly the difference the wearer asked for, and nothing else.
    """
    _instant_dwells(monkeypatch)
    zs.FAKE_MODEL_SECONDS = 0.05
    text = "pace"
    rec = _RecordingDevice()
    zs.hub.devices.append(rec)

    def spell_once() -> list[float]:
        seen = _record_dwells(monkeypatch)
        asyncio.run(zs.run_message_turn(text))
        return seen[1:]  # drop the model's poll tick

    try:
        default_dwells = spell_once()
        client.post("/api/ziv/prefs", json={"cell_gap_ms": timing.CELL_GAP_MAX_MS})
        assert zs._effective_cell_gap_ms() == timing.CELL_GAP_MAX_MS
        fast_dwells = spell_once()
    finally:
        zs.hub.devices.remove(rec)

    delta = (timing.CELL_GAP_MAX_MS - timing.CELL_GAP_DEFAULT_MS) / 1000.0
    assert len(default_dwells) == len(fast_dwells) == len(text)
    for before, after in zip(default_dwells, fast_dwells):
        assert after - before == pytest.approx(delta)


def test_health_reports_inbox_prefs_and_store_problems(client, fresh_store):
    h = client.get("/api/ziv/health").json()
    assert h["service"].startswith("Ziv relay v1")
    assert h["inbox_pending"] == 0
    assert h["prefs"]["cell_gap_ms"] == timing.CELL_GAP_DEFAULT_MS
    assert h["store_problems"] == []
    # A corrupt store file surfaces as a problem, not a crash.
    (fresh_store / "wearer.inbox.json").write_text("{broken", encoding="utf-8")
    h2 = client.get("/api/ziv/health").json()
    assert "inbox" in h2["store_problems"]


# ---------------------------------------------------------------------------
# The Omni spike, real: mic audio → Token Factory → the same turn
# ---------------------------------------------------------------------------

_B64_PNG = "iVBORw0KGgoAAAANSUhEUg=="  # well-formed base64; content is mocked


def test_omni_requires_key(client, monkeypatch):
    """No NEBIUS_API_KEY: audio is refused with 503 — never a silent drop."""
    monkeypatch.setattr(zs, "NEBIUS_API_KEY", "")
    r = client.post("/inject/audio", json={"audio_b64": _B64_PNG, "mime": "webm"})
    assert r.status_code == 503
    assert "NEBIUS_API_KEY" in r.json()["detail"]


def test_omni_rejects_bad_mime_and_missing_body(client, monkeypatch):
    monkeypatch.setattr(zs, "NEBIUS_API_KEY", "k")
    monkeypatch.setattr(zs, "ZIV_OMNI_MODEL", "audio-endpoint/for-tests")
    r = client.post("/inject/audio", json={"audio_b64": _B64_PNG, "mime": "flac"})
    assert r.status_code == 422
    r = client.post("/inject/audio", json={})
    assert r.status_code == 422


def test_omni_audio_transcribes_and_runs_the_turn(client, monkeypatch):
    """audio_b64 → Token Factory call (mocked) → transcript takes the turn.

    The HTTP mock asserts the request the provider must see: OpenAI-compatible
    chat completions, the bearer key, the input_audio part with the caller's
    format, and the Omni model id. The response's transcript becomes the
    turn's text — the same wearer-visible journey a typed message takes.
    """
    captured = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "Pills at nine"}}]}

    class _FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"], captured["json"], captured["headers"] = url, json, headers
            return _Resp()

    class _FakeHttpx:
        AsyncClient = _FakeClient
        class HTTPError(Exception):
            pass

    monkeypatch.setitem(sys.modules, "httpx", _FakeHttpx)
    monkeypatch.setattr(zs, "NEBIUS_API_KEY", "test-key")
    monkeypatch.setattr(zs, "ZIV_OMNI_MODEL", "audio-endpoint/for-tests")

    with _attach(client) as ws:
        r = client.post(
            "/inject/audio",
            json={"audio_b64": _B64_PNG, "mime": "webm"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["source"] == "audio_omni"
        assert body["event"] == "turn_complete"

        # The wire request is the provider contract, not our guess.
        assert captured["url"].endswith("/chat/completions")
        assert captured["url"].startswith("https://api.tokenfactory.nebius.com")
        assert captured["headers"]["Authorization"] == "Bearer test-key"
        assert captured["json"]["model"] == zs.ZIV_OMNI_MODEL
        parts = captured["json"]["messages"][0]["content"]
        assert parts[1]["type"] == "input_audio"
        # Exactly the OpenAI audio shape: raw base64 in ``data``, the container
        # named in ``format``. Asserted for equality on purpose — a loosened
        # ``endswith`` here is precisely how a ``data:`` URL slips into the
        # payload and ships unnoticed.
        assert parts[1]["input_audio"] == {"data": _B64_PNG, "format": "webm"}

        # The transcript — not the stub text — is what the wrist spells.
        frames = [ws.receive_json() for _ in range(7)]
        text_frame = next(f for f in frames if f["type"] == "text")
        assert "Pills at nine" in text_frame["text"]  # the transcript, spelled


def test_omni_requires_a_configured_audio_endpoint(client, monkeypatch):
    """A key alone is not enough: with no audio-capable endpoint configured the
    seam refuses with 503 rather than naming a model that cannot serve it."""
    monkeypatch.setattr(zs, "NEBIUS_API_KEY", "test-key")
    monkeypatch.setattr(zs, "ZIV_OMNI_MODEL", "")
    r = client.post("/inject/audio", json={"audio_b64": _B64_PNG, "mime": "webm"})
    assert r.status_code == 503
    assert "ZIV_OMNI_MODEL" in r.json()["detail"]


def test_omni_provider_failure_is_loud_not_silent(client, monkeypatch):
    """A provider error answers 502 with the provider's own words — the phone
    shows the failure; the turn never half-happens."""
    monkeypatch.setattr(zs, "NEBIUS_API_KEY", "test-key")
    monkeypatch.setattr(zs, "ZIV_OMNI_MODEL", "audio-endpoint/for-tests")

    class _Resp:
        status_code = 503
        text = "model overloaded"

        def json(self):
            return {"detail": "model overloaded"}

    class _FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            return _Resp()

    class _FakeHttpx:
        AsyncClient = _FakeClient

        class HTTPError(Exception):
            pass

    monkeypatch.setitem(sys.modules, "httpx", _FakeHttpx)

    with _attach(client):
        r = client.post("/inject/audio", json={"audio_b64": _B64_PNG, "mime": "ogg"})
    assert r.status_code == 502
    assert "model overloaded" in r.json()["detail"]





def test_omni_stub_path_still_runs_keyless(client, monkeypatch):
    """The keyless demo path is untouched: simulate needs no key.

    The stub must not touch Token Factory at all. Swapping between the stub and
    a real transcription changes nothing on the phone — only the log's
    ``source`` field differs.
    """
    monkeypatch.setattr(zs, "NEBIUS_API_KEY", "")
    monkeypatch.setattr(zs, "ZIV_OMNI_MODEL", "")
    with _attach(client) as ws:
        r = client.post("/inject/audio", json={"simulate": "Taxi here"})
        assert r.status_code == 200
        assert r.json()["source"] == "audio_stub"
        f = ws.receive_json()
        assert f["type"] == "haptic" and f["pattern"] == "double-tap"


# ---------------------------------------------------------------------------
# Hardened seam: bounded queue (429) + concurrent-delivery serialization
# ---------------------------------------------------------------------------

def test_message_is_rejected_429_when_replay_queue_is_full(client, monkeypatch):
    """A full replay queue answers 429 with the cap — the sender is told no,
    loudly, and the wrist feels nothing for a refused message."""
    pushed = []
    real_push = zs._push

    async def spy(frame):
        pushed.append(frame)
        return await real_push(frame)

    monkeypatch.setattr(zs, "_push", spy)
    with _attach(client):
        zs.gate.begin_playback()
        for i in range(zs.MessageGate.MAX_QUEUED):
            zs.gate.admit("filler-%d" % i)
        r = client.post("/api/ziv/message", json={"text": "overflow"})
        assert r.status_code == 429
        assert "full" in r.json()["detail"]
        assert str(zs.MessageGate.MAX_QUEUED) in r.json()["detail"]
    # The refusal pushed no frame: the wearer feels nothing for a no.
    assert pushed == []


def test_health_surfaces_the_model_wiring(client, monkeypatch):
    """Health says which model path can actually run right now, so the demo
    take never claims a model ran when none did: ``text`` is the agent path the
    demo proves, ``omni`` the audio seam, configured only when an audio-capable
    endpoint is named."""
    h = client.get("/api/ziv/health").json()
    text, omni = h["text"], h["omni"]
    assert text["base_url"].startswith("https://api.tokenfactory.nebius.com")
    assert text["model"] == zs.ZIV_TEXT_MODEL
    assert text["available"] == zs.agent_path_available()
    assert omni["configured"] == bool(zs.ZIV_OMNI_MODEL)
    assert omni["model"] == zs.ZIV_OMNI_MODEL

    # A key plus a model id is what makes the agent path available.
    monkeypatch.setattr(zs, "NEBIUS_API_KEY", "k")
    h2 = client.get("/api/ziv/health").json()
    assert h2["text"]["key_set"] is True
    assert h2["text"]["available"] is True


def test_scheduled_intent_is_composed_by_the_model_and_played(client, monkeypatch):
    """The agent path: a reminder scheduled as an *intent* is composed into a
    line by a live NVIDIA open model on Nebius Token Factory, and the model's
    own words are what the turn spells — not the intent, not a template."""
    import asyncio

    captured = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "Meds at nine tonight."}}]}

    class _FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            captured.update(url=url, json=json, headers=headers)
            return _Resp()

    class _FakeHttpx:
        AsyncClient = _FakeClient

        class HTTPError(Exception):
            pass

    monkeypatch.setitem(sys.modules, "httpx", _FakeHttpx)
    monkeypatch.setattr(zs, "NEBIUS_API_KEY", "test-key")

    r = client.post(
        "/api/ziv/schedule",
        json={"fire_at": time.time() + 3600, "intent": "meds at nine"},
    )
    assert r.status_code == 200
    # The durable store keeps the *intent* — never a line nobody composed.
    assert r.json()["source"] == "agent"
    assert r.json()["text"] == "meds at nine"

    zs.scheduled._save([{**row, "fire_at": time.time() - 1}
                        for row in zs.scheduled._load()])
    with _attach(client):
        fired = asyncio.run(zs.fire_due())
    assert fired[0]["fired"] is True
    assert fired[0]["source"] == "agent"
    assert fired[0]["text"] == "Meds at nine tonight."

    # The wire request is the provider contract, not our guess.
    assert captured["url"].endswith("/chat/completions")
    assert captured["json"]["model"] == zs.ZIV_TEXT_MODEL
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert "meds at nine" in captured["json"]["messages"][-1]["content"]


def test_scheduled_intent_echoes_verbatim_without_a_key(client, monkeypatch):
    """No key, no model: the promise still fires — verbatim, and honestly
    labelled ``text_echo``, so the log never claims a model ran when none did."""
    import asyncio

    monkeypatch.setattr(zs, "NEBIUS_API_KEY", "")
    client.post(
        "/api/ziv/schedule",
        json={"fire_at": time.time() + 3600, "intent": "meds at nine"},
    )
    zs.scheduled._save([{**row, "fire_at": time.time() - 1}
                        for row in zs.scheduled._load()])
    with _attach(client):
        fired = asyncio.run(zs.fire_due())
    assert fired[0]["fired"] is True
    assert fired[0]["source"] == "text_echo"
    assert fired[0]["text"] == "meds at nine"


def test_compose_failure_is_loud_not_silent(monkeypatch):
    """A model failure answers 502 with the provider's own words — never a
    silent empty line, and never a fabricated substitute."""
    import asyncio

    class _Resp:
        status_code = 500
        text = "upstream exploded"

        def json(self):
            return {"detail": "upstream exploded"}

    class _FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            return _Resp()

    class _FakeHttpx:
        AsyncClient = _FakeClient

        class HTTPError(Exception):
            pass

    monkeypatch.setitem(sys.modules, "httpx", _FakeHttpx)
    with pytest.raises(zs.HTTPException) as ei:
        asyncio.run(zs.compose_with_nebius("meds at nine"))
    assert ei.value.status_code == 502
    assert "upstream exploded" in ei.value.detail


def test_health_surfaces_queue_rejection_telemetry(client):
    """Every 429 the relay hands out is operator-visible in health: the
    cumulative count, the per-minute rate, the last refusal reason, and
    when it happened. Health before any refusal shows a zeroed snapshot."""
    h0 = client.get("/api/ziv/health").json()["queue_rejections"]
    assert h0 == {"count": 0, "per_minute": 0, "window_s": 60,
                  "last_reason": None, "last_at": None}

    with _attach(client):
        zs.gate.begin_playback()
        for i in range(zs.MessageGate.MAX_QUEUED):
            zs.gate.admit("filler-%d" % i)
        r1 = client.post("/api/ziv/message", json={"text": "overflow-1"})
        r2 = client.post("/api/ziv/message", json={"text": "overflow-2"})
        assert r1.status_code == 429 and r2.status_code == 429

    h = client.get("/api/ziv/health").json()["queue_rejections"]
    assert h["count"] == 2
    assert h["per_minute"] == 2  # both refusals landed within the window
    assert h["last_reason"] == "queue_full"
    assert h["last_at"]  # ISO timestamp of the last refusal


def test_rejection_rate_reflects_only_the_recent_window():
    """per_minute counts only rejections inside the 60 s window: a refusal
    older than the window drops out of the rate (spike signal) while the
    cumulative count keeps it (lifetime signal)."""
    import time as _time

    st = zs._RejectionStats()
    st.record("queue_full")
    snap = st.snapshot()
    assert snap["per_minute"] == 1 and snap["count"] == 1

    # Age the refusal past the window — no 60 s sleep; move the timestamp.
    assert len(st._recent) == 1
    st._recent[0] = _time.monotonic() - (st.WINDOW_S + 1)
    snap2 = st.snapshot()
    assert snap2["per_minute"] == 0, "aged refusal still counts in the rate"
    assert snap2["count"] == 1, "cumulative count must keep the refusal"


def test_health_payload_serves_the_pwa_badge_contract(client):
    """The dev-band PWA's live queue badge renders straight from health:
    ``gate_queue`` + ``gate_queue_cap`` for the depth line,
    ``queue_rejections.per_minute`` for the refusal rate. The client
    renders NOTHING (silently blank) when depth or cap is missing or not
    a number — so these keys are a wire contract, not an internal detail.
    This test pins them hermetically: a server-side rename fails HERE,
    not on a phone with a blank badge (the browser-level proof is the
    Playwright e2e, which does not run everywhere the suite does).

    Types are part of the contract: the client guards with JS
    ``typeof x === "number"``, and a bool/string would blank the badge
    just like a missing key — hence the strict numeric check.
    """
    def numeric(v) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    # Fresh boot — the badge renders on page load, before anything happens.
    h0 = client.get("/api/ziv/health").json()
    assert numeric(h0["gate_queue"]) and h0["gate_queue"] == 0
    assert numeric(h0["gate_queue_cap"])
    assert h0["gate_queue_cap"] == zs.MessageGate.MAX_QUEUED
    assert numeric(h0["queue_rejections"]["per_minute"])

    # Real depth, at a non-cap value first: the key must reflect the live
    # queue, not echo the cap.
    with _attach(client):
        zs.gate.begin_playback()
        for i in range(3):
            zs.gate.admit("filler-%d" % i)
        h3 = client.get("/api/ziv/health").json()
        assert h3["gate_queue"] == 3

        # Filled to the cap + one real refusal: the badge's "full" and
        # "N/min refused" states rest on these exact numbers.
        for i in range(3, zs.MessageGate.MAX_QUEUED):
            zs.gate.admit("filler-%d" % i)
        r = client.post("/api/ziv/message", json={"text": "overflow"})
        assert r.status_code == 429
    h = client.get("/api/ziv/health").json()
    assert h["gate_queue"] == zs.MessageGate.MAX_QUEUED
    assert h["gate_queue_cap"] == zs.MessageGate.MAX_QUEUED
    assert h["queue_rejections"]["per_minute"] == 1


def test_health_payload_surfaces_the_schedule(client):
    """The durable schedule gets the gate queue's treatment in health:
    ``schedule_pending`` (live depth), ``schedule_cap`` (the drop-oldest
    limit), and ``schedule_corrupt`` (a corrupt store file is a fact, not
    a silence — same rule as the inbox's corrupt reports). The flag is
    consumed from the SAME drain as ``store_problems``, so the flag and
    the list can never disagree within one response.
    """
    import ziv_store as zstore

    # Fresh boot: empty schedule, the store's cap, nothing corrupt.
    h0 = client.get("/api/ziv/health").json()
    assert h0["schedule_pending"] == 0
    assert h0["schedule_cap"] == zstore.SCHEDULE_CAP
    assert h0["schedule_corrupt"] is False

    # Depth is live: pending reminders move the number.
    zs.scheduled.add(time.time() + 10_000, "pills")
    zs.scheduled.add(time.time() + 10_100, "call back")
    h2 = client.get("/api/ziv/health").json()
    assert h2["schedule_pending"] == 2
    assert h2["schedule_corrupt"] is False

    # Corruption surfaces on BOTH channels of one response. The corrupt
    # file is DISCOVERED by the depth load inside health() (count before
    # drain — that ordering is part of the contract), so the very next
    # response carries both the flag and the store_problems entry.
    (zstore.DATA_DIR / "wearer.schedule.json").write_text("[{broken",
                                                          encoding="utf-8")
    h3 = client.get("/api/ziv/health").json()
    assert h3["schedule_corrupt"] is True
    assert h3["schedule_pending"] == 0  # a corrupt load discards
    assert "schedule" in h3["store_problems"]
    # Consume-once, like every corrupt report here: heal the file (a valid
    # write rebuilds it — the store's own recovery discipline) and the next
    # response is clean. (A real add() would itself re-discover the corrupt
    # file in its load and re-report before healing — the store's
    # re-report-until-rebuilt semantics, covered in the store tests.) The
    # fire loop only ever APPENDS reports (its loads never drain), so clear
    # any report appended between h3's drain and the heal — after the heal
    # no new reports can be appended by anyone, making h4 race-free.
    (zstore.DATA_DIR / "wearer.schedule.json").write_text("[]",
                                                          encoding="utf-8")
    zs.scheduled.take_corrupt_files()
    h4 = client.get("/api/ziv/health").json()
    assert h4["schedule_pending"] == 0
    assert h4["schedule_corrupt"] is False
    assert h4["store_problems"] == []


def test_concurrent_inbox_deliveries_never_double_deliver(client, monkeypatch):
    """Two deliveries racing pick up two different entries — never the same
    one twice (the inbox peek happens under the turn lock).

    Regression proof for the peek-outside-the-lock race: with the peek
    outside, both tasks peek the same oldest entry and one message plays
    twice while the other waits forever. With the peek inside the lock, the
    second task waits, then peeks the next entry.
    """
    import asyncio

    labels = []

    async def fake_push(frame):
        if frame.get("type") == "text":
            labels.append(frame["text"])
        return None

    monkeypatch.setattr(zs, "_push", fake_push)
    client.post("/api/ziv/message", json={"text": "alpha"})
    client.post("/api/ziv/message", json={"text": "beta"})
    assert client.get("/api/ziv/inbox").json()["count"] == 2

    async def deliver_both():
        return await asyncio.gather(zs.deliver_inbox_one(), zs.deliver_inbox_one())

    asyncio.run(deliver_both())

    assert sorted(labels) == sorted([
        "message: alpha", "queued: alpha",
        "message: beta", "queued: beta",
    ])
    assert client.get("/api/ziv/inbox").json()["count"] == 0


# ---------------------------------------------------------------------------
# Spec-defined patterns, felt: the error long-buzz + the name-mark prefix
# ---------------------------------------------------------------------------

def test_omni_provider_failure_feels_the_error_long_buzz(client, monkeypatch):
    """502 from Token Factory: the sender gets the loud HTTP error AND the
    wrist feels the error long-buzz — a transcription failure is never
    silent on either side of the wire."""

    class _Resp:
        status_code = 503
        text = "model overloaded"

    class _FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            return _Resp()

    class _FakeHttpx:
        AsyncClient = _FakeClient
        class HTTPError(Exception):
            pass

    monkeypatch.setitem(sys.modules, "httpx", _FakeHttpx)
    monkeypatch.setattr(zs, "NEBIUS_API_KEY", "test-key")
    monkeypatch.setattr(zs, "ZIV_OMNI_MODEL", "audio-endpoint/for-tests")

    with _attach(client) as ws:
        r = client.post("/inject/audio", json={"audio_b64": _B64_PNG, "mime": "ogg"})
        assert r.status_code == 502
        assert "model overloaded" in r.json()["detail"]

        # The wrist learned it first, in pattern: the long-buzz, then the words.
        f1 = ws.receive_json()
        assert f1["type"] == "haptic"
        assert f1["pattern"] == "long-buzz"
        assert f1["ms"] == _vibrate_ms("long-buzz")
        assert "transcription failed" in f1["why"]
        f2 = ws.receive_json()
        assert f2["type"] == "text"
        assert "transcription failed" in f2["text"]


class _RecordingDevice:
    """A hub device that records every frame the real broadcast delivers —
    the wire path without a socket (the pump serializes; this captures)."""

    def __init__(self) -> None:
        import json as _json

        self._json = _json
        self.frames: list[dict] = []

    async def send_text(self, s: str) -> None:
        self.frames.append(self._json.loads(s))


def test_prefix_mark_order_is_mark_tail_then_turn(client, monkeypatch):
    """The unsolicited turn's felt order: Z-I-V mark cells → triple-pulse
    tail → breath → the turn's own cue → processing → content → close —
    with the wire log narrating both the mark and the content."""
    import asyncio

    zs.FAKE_MODEL_SECONDS = 0.05
    rec = _RecordingDevice()
    zs.hub.devices.append(rec)  # attach() is async; the list is its state
    try:
        result = asyncio.run(
            zs.run_message_turn("pills", source="scheduled", prefix_mark="reminder")
        )
    finally:
        zs.hub.devices.remove(rec)
    assert result["event"] == "turn_complete"

    pushed = rec.frames
    # The mark is narrated FIRST, with its letters for the cells box.
    assert pushed[0]["type"] == "text"
    assert pushed[0]["text"].startswith("reminder: pills")

    # The first three cells are the mark: z, i, v (the generated table).
    cells = [f["ch"] for f in pushed if f["type"] == "cell"]
    assert cells[:3] == list(timing.MARK_CELLS[timing.PREFIX_MARK])

    haptics = [(f["pattern"], f.get("why")) for f in pushed if f["type"] == "haptic"]
    assert haptics[0] == ("triple-pulse", "reminder mark")  # the kind tail
    assert haptics[1][0] == "double-tap"                    # the turn's kind cue
    assert any(p == "processing" for p, _ in haptics)       # the legible wait
    assert haptics[-1][0] == "end-of-message"               # the close

    # The content is narrated after the mark ("message: pills").
    texts = [f.get("text", "") for f in pushed if f["type"] == "text"]
    assert any(t.startswith("message: pills") for t in texts)


def test_scheduled_reminder_fires_with_name_mark_over_the_wire(client):
    """End to end through the LIVE fire loop (the lifespan task): a due
    reminder fires unprompted as its own turn, opening with the Z-I-V mark
    and the triple-pulse tail, and is removed from the schedule so it never
    fires twice. The mark + content take ~9 s of real dwell on the wire."""
    zs.FAKE_MODEL_SECONDS = 0.05
    rec = _RecordingDevice()
    zs.hub.devices.append(rec)  # attach() is async; the list is its state
    try:
        zs.scheduled.add(time.time() - 0.01, "pills")  # due immediately
        deadline = time.time() + 30
        while time.time() < deadline:
            if any(f["type"] == "haptic" and f["pattern"] == "end-of-message"
                   for f in rec.frames):
                break
            time.sleep(0.1)
        assert any(f["type"] == "haptic" and f["pattern"] == "end-of-message"
                   for f in rec.frames), "the live loop never fired the reminder"
    finally:
        zs.hub.devices.remove(rec)

    haptics = []
    texts = []
    for f in rec.frames:
        if f["type"] == "haptic":
            haptics.append((f["pattern"], f.get("why")))
        elif f["type"] == "text":
            texts.append(f.get("text", ""))

    assert haptics[0] == ("triple-pulse", "reminder mark")
    assert haptics[1][0] == "double-tap"          # the turn's kind cue
    assert haptics[-1][1] == "close"              # the event ends
    assert any(p == "processing" for p, _ in haptics)
    assert any(t.startswith("reminder: pills") for t in texts)
    assert any(t.startswith("message: pills") for t in texts)

    # Fired reminders never fire twice.
    assert zs.scheduled.list_all() == []


def test_schedule_accepts_reminders_after_a_drain(client):
    """The schedule must accept reminders after any drain — the historical
    trap was fire_due rebuilding its queue with
    ``deque(remaining, maxlen=len(remaining))``: an empty remaining list
    produced a maxlen-0 deque, and every later ``add`` silently vanished.
    The durable rewrite (ziv_store) makes the invariant structural — the
    file is rewritten from a plain list, never a capped deque — and the
    round-trip below proves a fresh instance (a restart) still sees it.
    """
    import asyncio

    sched = zs.scheduled  # the fixture's fresh durable schedule
    # A drain with nothing due — the poll that poisoned the old deque.
    asyncio.run(zs.fire_due())
    # The schedule must still accept a reminder and hand it back out.
    sched.add(time.time() + 60, "water the plants")
    pending = sched.list_all()
    assert len(pending) == 1
    assert pending[0]["text"] == "water the plants"
    # And the round-trip: a new instance over the same store (a restart)
    # reads the same reminder — nothing lives only in process memory.
    reborn = zs.ScheduledReminders()
    assert [r["text"] for r in reborn.list_all()] == ["water the plants"]


def test_schedule_survives_concurrent_adds(client):
    """Ten threads adding at once: every reminder present, ids unique.

    Pins the lock discipline the add() debugging episode chased —
    contention was never the bug (the maxlen-0 deque was), but the
    guarantee is worth holding. With the durable store, every add is an
    atomic file rewrite behind the RLock.
    """
    import threading

    sched = zs.scheduled
    n = 10
    barrier = threading.Barrier(n)

    def adder(i: int) -> None:
        barrier.wait()
        sched.add(time.time() + i, f"thread-{i}")

    threads = [threading.Thread(target=adder, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    pending = sched.list_all()
    assert sorted(p["text"] for p in pending) == sorted(
        f"thread-{i}" for i in range(n)
    )
    assert len({p["id"] for p in pending}) == n


def test_reminder_stored_offline_replays_with_name_mark(client):
    """A reminder that fired with no band attached is stored in the inbox —
    on the next delivery it replays as the same self-naming turn a live
    reminder is: mark cells, the triple-pulse tail, then the content.
    Redelivery must not lose the identity.
    """
    import asyncio

    rec = _RecordingDevice()
    # Store a "scheduled" entry directly — the no-band fire path is covered
    # by the misfire tests; here the replay is what is under test.
    zs.inbox.offer("pills", source="scheduled")
    zs.hub.devices.append(rec)
    try:
        asyncio.run(zs.deliver_inbox_one())
    finally:
        zs.hub.devices.remove(rec)

    haptics = [(f["pattern"], f.get("why")) for f in rec.frames
               if f["type"] == "haptic"]
    texts = [f.get("text", "") for f in rec.frames if f["type"] == "text"]
    cells = [f["ch"] for f in rec.frames if f["type"] == "cell"]

    assert texts[0] == "reminder: pills"
    assert cells[:3] == list(timing.MARK_CELLS[timing.PREFIX_MARK])
    assert haptics[0] == ("triple-pulse", "reminder mark")
    assert any(t.startswith("queued: pills") for t in texts)
    assert haptics[-1][0] == "end-of-message"
    # Marked delivered only after the close — the entry is gone.
    assert zs.inbox.count() == 0


# ---------------------------------------------------------------------------
# The felt sequence: spec-defined patterns over the wire
