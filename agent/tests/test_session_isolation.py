"""One relay process, one gate per band.

The relay used to keep a single process-wide hub and gate, so every open
client received every turn: five tabs were five windows onto one wrist. These
tests pin the split at every layer that can leak a turn — the turn pump, the
HTTP route that starts it, the two websocket transports, and the reminder
scheduler's choice of band — plus the two properties that keep it honest:

* an unnamed client keeps the old ``default`` behaviour (curl, demo scripts);
* sessions are forgotten when their last device leaves, so tabs cannot
  accumulate in the registry.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import anyio
import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT / "agent"), str(_ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ziv_server as zs  # noqa: E402


class _Band:
    """A device that records what the relay pushed to its stream."""

    def __init__(self) -> None:
        self.frames: list[dict] = []

    async def send_text(self, payload: str) -> None:
        self.frames.append(json.loads(payload))

    def types(self) -> list[str]:
        return [str(f.get("type")) for f in self.frames]


def _instant_dwells(monkeypatch) -> None:
    """Ordering tests do not need to wait out the cells."""

    async def fake(_seconds: float) -> None:
        return None

    monkeypatch.setattr(zs, "_dwell", fake)


@pytest.fixture()
def fast(monkeypatch, tmp_path):
    """A hermetic relay: temp store, fast model, instant dwells."""
    import ziv_store as zstore

    d = tmp_path / "ziv_data"
    d.mkdir()
    monkeypatch.setattr(zstore, "DATA_DIR", d)
    monkeypatch.setattr(zs, "inbox", zs.MessageInbox())
    monkeypatch.setattr(zs, "FAKE_MODEL_SECONDS", 0.0)
    _instant_dwells(monkeypatch)
    yield


@pytest.fixture()
def client(fast):
    with TestClient(zs.app) as c:
        yield c


def _attach_bands(*session_ids: str):
    pairing = []
    for sid in session_ids:
        session = zs.sessions.get(sid)
        band = _Band()
        session.hub.devices.append(band)
        pairing.append((session, band))
    return pairing


def _detach_all(pairing) -> None:
    for session, band in pairing:
        if band in session.hub.devices:
            session.hub.devices.remove(band)
        zs.sessions.release(session)


def _frame_within(ws, seconds: float):
    """One frame from a TestClient websocket, or None at the deadline.

    Starlette's test session has no receive timeout; read its anyio queue
    without blocking and poll, exactly as the main server suite does.
    """
    import time

    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            message = ws.portal.call(ws._send_rx.receive_nowait)
        except anyio.WouldBlock:
            time.sleep(0.02)
            continue
        if message.get("text") is not None:
            return json.loads(message["text"])
        return message.get("bytes")
    return None


def _assert_no_frame(ws) -> None:
    try:
        message = ws.portal.call(ws._send_rx.receive_nowait)
    except anyio.WouldBlock:
        return
    raise AssertionError(f"the other session received a frame: {message!r}")


def test_a_turn_plays_only_on_its_own_session(fast):
    """Session A's gate, cells and close never touch session B's socket."""
    pairing = _attach_bands("tab-a", "tab-b")
    (a, band_a), (b, band_b) = pairing
    try:
        result = asyncio.run(zs.run_message_turn("alpha", session=a))
        assert result["event"] == "turn_complete"
        assert "cell" in band_a.types(), "the turn's content never played on A"
        assert "haptic" in band_a.types()
        assert band_b.frames == [], "a message for A leaked onto B's stream"
        assert len(b.gate) == 0 and b.gate.playing is False
    finally:
        _detach_all(pairing)


def test_an_unnamed_turn_still_uses_the_default_session(fast):
    """Back-compat: curl and the demo scripts post with no session at all."""
    band = _Band()
    zs.hub.devices.append(band)
    try:
        result = asyncio.run(zs.run_message_turn("bravo"))
        assert result["event"] == "turn_complete"
        assert "cell" in band.types()
    finally:
        if band in zs.hub.devices:
            zs.hub.devices.remove(band)
    assert zs.sessions.default.session_id == "default"


def test_the_http_route_targets_the_named_session(client):
    """The header the browser sends, and the body fallback, both route."""
    pairing = _attach_bands("http-a", "http-b")
    (_, band_a), (_, band_b) = pairing
    try:
        r = client.post(
            "/api/ziv/message",
            json={"text": "charlie"},
            headers={"X-Ziv-Session": "http-a"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["event"] == "turn_complete"
        assert "cell" in band_a.types(), band_a.frames
        assert band_b.frames == []

        seen = len(band_a.frames)
        r2 = client.post(
            "/api/ziv/message",
            json={"text": "delta", "session": "http-b"},
        )
        assert r2.status_code == 200, r2.text
        assert "cell" in band_b.types(), band_b.frames
        assert len(band_a.frames) == seen, "B's turn leaked back onto A"
    finally:
        _detach_all(pairing)


def test_two_websockets_get_only_their_own_messages(client):
    """The live transport: two sockets, one POST, one stream."""
    with client.websocket_connect("/ws?session=ws-a") as ws_a, \
            client.websocket_connect("/ws?session=ws-b") as ws_b:
        hello_a = ws_a.receive_json()
        hello_b = ws_b.receive_json()
        assert hello_a["type"] == hello_b["type"] == "hello"
        assert hello_a["session"] == "ws-a"
        assert hello_b["session"] == "ws-b"

        r = client.post("/api/ziv/message",
                        json={"text": "delta", "session": "ws-a"})
        assert r.status_code == 200, r.text

        seen = []
        for _ in range(40):
            frame = _frame_within(ws_a, 1.0)
            assert frame is not None, "A's turn stopped before its close"
            seen.append(frame)
            if frame.get("pattern") == "end-of-message":
                break
        assert any(f.get("type") == "cell" for f in seen)
        assert seen[-1].get("pattern") == "end-of-message"
        _assert_no_frame(ws_b)

    assert zs.sessions.get("ws-a", create=False) is None
    assert zs.sessions.get("ws-b", create=False) is None


def test_a_closed_tab_is_forgotten(client):
    """A closed session must not occupy the registry forever."""
    with client.websocket_connect("/ws?session=short-lived") as ws:
        assert ws.receive_json()["session"] == "short-lived"
        assert zs.sessions.get("short-lived", create=False) is not None
    assert zs.sessions.get("short-lived", create=False) is None


def test_an_unnamed_post_targets_the_band_in_use(client):
    """curl, demo scripts and webhooks do not know a tab's id.

    They address the wearer, so the newest attached band plays the message
    and the other open tab stays silent — never both, never the empty
    ``default`` session.
    """
    pairing = _attach_bands("anon-a", "anon-b")
    (a, band_a), (b, band_b) = pairing
    try:
        zs.sessions.touch(a)
        zs.sessions.touch(b)
        r = client.post("/api/ziv/message", json={"text": "foxtrot"})
        assert r.status_code == 200, r.text
        assert r.json()["event"] == "turn_complete"
        assert "cell" in band_b.types(), band_b.frames
        assert band_a.frames == [], "an anonymous message reached both tabs"
    finally:
        _detach_all(pairing)


def test_reminders_pick_one_attached_band(fast):
    """A wearer-level reminder goes to the newest band, never to all of them."""
    # No unnamed client is attached, so ``active`` is the newest named band.
    pairing = _attach_bands("rem-a", "rem-b")
    (a, _), (b, _) = pairing
    try:
        zs.sessions.touch(a)
        zs.sessions.touch(b)
        assert zs.sessions.active() is b
        assert sum(1 for s in (a, b) if s.hub.count) == 2
    finally:
        _detach_all(pairing)


def test_health_reports_each_live_band(client):
    """The badge's band count is driven by health: one row per attached band."""
    pairing = _attach_bands("health-a", "health-b")
    try:
        h = client.get("/api/ziv/health").json()
        rows = {s["id"]: s for s in h["sessions"]}
        assert rows["health-a"]["devices"] == 1, rows
        assert rows["health-b"]["devices"] == 1, rows
        assert h["devices"] >= 2
    finally:
        _detach_all(pairing)


def test_health_stamps_when_a_band_last_felt_a_frame(client):
    """A freshly attached band has no frames; a played turn stamps it."""
    pairing = _attach_bands("frame-a")
    try:
        row = next(s for s in client.get("/api/ziv/health").json()["sessions"]
                   if s["id"] == "frame-a")
        assert row["last_frame_age_s"] is None

        r = client.post("/api/ziv/message", json={"text": "echo"},
                        headers={"X-Ziv-Session": "frame-a"})
        assert r.status_code == 200, r.text

        row = next(s for s in client.get("/api/ziv/health").json()["sessions"]
                   if s["id"] == "frame-a")
        assert isinstance(row["last_frame_age_s"], (int, float))
        assert 0 <= row["last_frame_age_s"] < 60, row
    finally:
        _detach_all(pairing)


def test_a_bad_session_id_is_refused(client):
    """The id is caller input: reject it instead of storing it in the registry."""
    r = client.post("/api/ziv/message",
                    json={"text": "echo", "session": "bad id!"})
    assert r.status_code == 422
    assert "session" in r.json()["detail"]
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?session=bad%20id") as ws:
            ws.receive_json()
