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
* /inject/audio (the Omni spike's seam, real now): ``audio_b64`` is
  transcribed by Nemotron-3-Nano-Omni on Nebius Token Factory (HTTP mocked;
  the wire request is asserted) and the transcript takes the same turn;
  without ``NEBIUS_API_KEY`` it answers 503, provider errors answer 502 —
  and the ``simulate`` stub keeps running keyless;
* auth: when ZIV_RELAY_TOKEN is set, bad/missing bearer tokens and WS tokens
  are rejected (monkeypatched — no env mutation).
"""

from __future__ import annotations

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
    zs.hub.devices.clear()
    zs.gate = zs.MessageGate()
    prev = zs.FAKE_MODEL_SECONDS
    zs.FAKE_MODEL_SECONDS = 0.3
    with TestClient(zs.app) as c:
        yield c
    zs.FAKE_MODEL_SECONDS = prev
    zs.hub.devices.clear()
    zs.gate = zs.MessageGate()


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


def test_health_counts_devices_and_gate(client):
    assert client.get("/api/ziv/health").json()["devices"] == 0
    with _attach(client):
        h = client.get("/api/ziv/health").json()
        assert h["devices"] == 1
        assert h["spec_version"] == timing.SPEC_VERSION
        assert h["gate_queue"] == 0


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

    Delivery happens after hello; each message plays cue → cells → close
    and is only then marked delivered — a vanished band means redelivery,
    never loss.
    """
    client.post("/api/ziv/message", json={"text": "first stored"})
    client.post("/inject/audio", json={"simulate": "second stored"})
    assert client.get("/api/ziv/inbox").json()["count"] == 2

    with _attach(client) as ws:
        # hello carries the pending count...
        # (already consumed by _attach; delivered frames follow)
        # first message: cue, text, cells, close
        f1 = ws.receive_json()
        assert f1 == {"type": "haptic", "pattern": "double-tap",
                      "ms": _vibrate_ms("double-tap"), "why": "from your inbox"}
        f2 = ws.receive_json()
        assert f2["type"] == "text" and f2["text"].startswith("queued: ")
        saw_first_close = False
        while not saw_first_close:
            f = ws.receive_json()
            if f["type"] == "haptic" and f["pattern"] == "end-of-message":
                saw_first_close = True
        # second message: same shape
        f3 = ws.receive_json()
        assert f3["type"] == "haptic" and f3["pattern"] == "double-tap"
        while True:
            f = ws.receive_json()
            if f["type"] == "haptic" and f["pattern"] == "end-of-message":
                break
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
        assert parts[1]["input_audio"] == {"data": _B64_PNG, "format": "webm"}

        # The transcript — not the stub text — is what the wrist spells.
        frames = [ws.receive_json() for _ in range(7)]
        text_frame = next(f for f in frames if f["type"] == "text")
        assert "Pills at nine" in text_frame["text"]  # the transcript, spelled


def test_omni_provider_failure_is_loud_not_silent(client, monkeypatch):
    """A provider error answers 502 with the provider's words — the phone
    shows the failure; the turn never half-happens."""
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

    with _attach(client):
        r = client.post("/inject/audio", json={"audio_b64": _B64_PNG, "mime": "ogg"})
    assert r.status_code == 502
    assert "model overloaded" in r.json()["detail"]


def test_omni_stub_path_still_runs_keyless(client, monkeypatch):
    """The hermetic demo path is untouched: simulate needs no key."""
    monkeypatch.setattr(zs, "NEBIUS_API_KEY", "")
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

    assert sorted(labels) == ["queued: alpha", "queued: beta"]
    assert client.get("/api/ziv/inbox").json()["count"] == 0
