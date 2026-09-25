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
        result = asyncio.run(zs.run_scheduled_reminder("pills"))
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
