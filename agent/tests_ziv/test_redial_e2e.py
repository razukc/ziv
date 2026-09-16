"""End-to-end: a queue-full refusal auto-sends again when the free close lands.

Unlike the SkillForge e2e tests (which intercept fetch and stub the backend
seam), this one drives the REAL relay: an in-process uvicorn serving the
actual dev band on an ephemeral port with a temp data dir, its real
``MessageGate`` filled to the cap by eight real POSTs while a starter turn
holds the haptic channel. Nothing on the page is stubbed — the proof covers
the whole refusal arc:

    victim POST → 429 → wrist-busy note + redial armed
    → the starter turn's LAST close (the ``free`` marker) on /ws
    → the client re-posts the refused body by itself
    → the redialed message plays its own full turn (turn_complete)

Two things make the synchronization honest rather than lucky:

* The server marks the close that truly frees the wrist (``free: true`` on
  the last close of the turn-plus-drain sequence) — the client fires its
  redial on exactly that frame, so it never queues its retry behind the
  remaining replays. The test asserts the marker is on precisely one close
  and is the final haptic frame the page receives.
* Traffic is recorded with a raw-ASGI wrapper around the real app — actual
  wire statuses and request/response bodies, not a browser event that can
  drop. The exact-one-redial property reads the recording: exactly three
  ``/api/ziv/message`` exchanges occur (starter 200, victim 429, redial
  200) — no double-fire from the replay drains' subsequent closes.

The fill window opens when the starter's playback begins (its ``text``
frame appears in the page's wire log) and the starter's fake-model phase is
shortened via ``ZIV_FAKE_MODEL_SECONDS`` so the scenario fits in seconds.

Marked ``e2e``: excluded from the default hermetic suite via
``addopts = -m \"not e2e\"`` — run explicitly with ``pytest -m e2e``.
(No SkillForge frontend/backend needed — the test starts its own relay.)
"""

import importlib
import json
import os
import socket
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

import e2e_helpers

pytest.importorskip("playwright")

pytestmark = pytest.mark.e2e

FAKE_MODEL_SECONDS = "1.0"
VICTIM_TEXT = "hi"             # short: the redialed turn must play fast
STARTER_TEXT = "Taxi arrived"  # 4 cells ≈ 2 s of playback — the fill window


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_for(pred, timeout_s, what):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        got = pred()
        if got is not None and got is not False:
            return got
        time.sleep(0.1)
    raise AssertionError("timed out waiting for " + what)


def wait_log(page, text, timeout_s=10, console=None):
    """Wait for a wire-log line; on timeout, dump the page's real state so a
    failure names its cause instead of leaving a bare locator timeout."""
    try:
        page.locator("#log div").filter(has_text=text).first.wait_for(
            timeout=timeout_s * 1000
        )
    except Exception:
        logs = [m.text for m in (console or [])]
        raise AssertionError(
            "wire log never showed %r.\n  state: %r\n  ws readyState: %s\n"
            "  wire log:\n%s\n  console:\n%s"
            % (
                text,
                page.locator("#state").inner_text(),
                page.evaluate("S.ws ? S.ws.readyState : null"),
                page.locator("#log").inner_text()[:1200],
                "\n".join(logs[-8:]) or "(none)",
            )
        )


class _RecordingASGI:
    """Raw-ASGI recorder around the real app: every /api/ziv/message exchange
    with its real status and both real bodies — the test's source of truth."""

    def __init__(self, inner, path: str):
        self._inner = inner
        self._path = path
        self.exchanges = []  # (status, request_body_bytes, response_body_bytes)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != self._path:
            await self._inner(scope, receive, send)
            return
        # Drain the request body, then REPLAY it to the app — the app must
        # still receive a well-formed body message (and pass-through for
        # anything after), or its body read blocks forever.
        body = b""
        more = True
        while more:
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)
        replayed = {"type": "http.request", "body": body, "more_body": False}
        done = False

        async def receive_replayer():
            nonlocal done
            if not done:
                done = True
                return replayed
            return await receive()

        captured = {"status": None, "chunks": []}

        async def send_recorder(message):
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
            elif message["type"] == "http.response.body":
                captured["chunks"].append(message.get("body", b""))
            await send(message)

        await self._inner(scope, receive_replayer, send_recorder)
        self.exchanges.append(
            (captured["status"], body, b"".join(captured["chunks"]))
        )


@pytest.fixture(scope="module")
def relay(tmp_path_factory):
    """The real relay app, live in-process on an ephemeral port.

    Fresh module state (gate/hub/memory/inbox/telemetry) via a reload against
    a temp data dir; restored afterwards so other tests in the same process
    see the original module state. Yields ``base`` plus the wire recording.
    """
    import ziv_store
    import ziv_server

    original_data_dir = ziv_store.DATA_DIR
    original_fake = os.environ.get("ZIV_FAKE_MODEL_SECONDS")
    data_dir = tmp_path_factory.mktemp("ziv_data")
    os.environ["ZIV_FAKE_MODEL_SECONDS"] = FAKE_MODEL_SECONDS
    ziv_store.DATA_DIR = data_dir
    importlib.reload(ziv_server)

    recorder = _RecordingASGI(ziv_server.app, "/api/ziv/message")
    port = _free_port()
    import uvicorn

    config = uvicorn.Config(recorder, host="127.0.0.1", port=port,
                            log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        _wait_for(lambda: _health_up(base), 15, "the relay to start")
        yield SimpleNamespace(base=base, exchanges=recorder.exchanges)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        ziv_store.DATA_DIR = original_data_dir
        if original_fake is None:
            os.environ.pop("ZIV_FAKE_MODEL_SECONDS", None)
        else:
            os.environ["ZIV_FAKE_MODEL_SECONDS"] = original_fake
        importlib.reload(ziv_server)  # pristine module state for later tests


def _health_up(base):
    try:
        return httpx.get(f"{base}/api/ziv/health", timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


def test_redial_auto_sends_after_the_close_frame(relay):
    base = relay.base

    # The wearer's fastest pace (structure universal, parameters personal) —
    # cells play at the spec's minimum gap so the scenario stays short.
    r = httpx.post(f"{base}/api/ziv/prefs", json={"cell_gap_ms": 250}, timeout=5)
    assert r.status_code == 200 and r.json()["cell_gap_ms"] == 250

    with e2e_helpers.browser_page() as page:
        console = []
        page.on("console", lambda m: console.append(m))
        page.goto(f"{base}/ziv_client/index.html",
                  wait_until="domcontentloaded", timeout=30000)
        # The band is attached once the page's own WS is open and the badge
        # poll answered — no POST can 409 (no band) after this.
        page.locator("#queueBadge").wait_for(state="visible", timeout=10000)
        page.locator("#state").filter(has_text="connected").wait_for(timeout=10000)
        page.locator("#btnUnlock").click()  # clean vibration state in Chrome

        # --- the starter turn owns the channel --------------------------
        page.locator("#msg").fill(STARTER_TEXT)
        page.locator("#btnSend").click()

        # Wire-level sync: the starter's playback begins when its cells
        # text frame lands in the wire log (processing is over). ~2 s of
        # runway before its close.
        wait_log(page, "message: " + STARTER_TEXT, 10, console)

        # --- fill the gate queue to the cap with real POSTs -------------
        with httpx.Client(timeout=5) as client:
            for i in range(8):
                fr = client.post(f"{base}/api/ziv/message", json={"text": chr(ord("a") + i)})
                assert fr.status_code == 200 and fr.json().get("queued") is True, fr.text

        # --- the victim: the queue is full, the gate refuses ------------
        page.locator("#msg").fill(VICTIM_TEXT)
        page.locator("#btnSend").click()

        exchanges = relay.exchanges
        victim = _wait_for(
            lambda: next((e for e in exchanges
                          if json.loads(e[1]) == {"text": VICTIM_TEXT}), None),
            10, "the victim's 429",
        )
        assert victim[0] == 429, "the full queue must refuse the victim"
        assert "queue is full" in json.loads(victim[2])["detail"]

        # The refusal is rendered, not silent — and the redial is armed.
        page.locator("#state").filter(has_text="wrist is busy").wait_for(timeout=5000)
        note = page.locator("#redialNote")
        note.wait_for(state="visible", timeout=5000)
        assert VICTIM_TEXT in note.inner_text()
        assert "3 chances left" in note.inner_text()

        # Server-side truth at the refusal moment: queue full, one 429.
        h = httpx.get(f"{base}/api/ziv/health", timeout=5).json()
        assert h["gate_queue"] == h["gate_queue_cap"] == 8
        assert h["queue_rejections"]["count"] == 1
        assert h["queue_rejections"]["last_reason"] == "queue_full"

        # --- the free close lands; the client redials by itself ----------
        redial = _wait_for(
            lambda: next((e for e in exchanges
                          if json.loads(e[1]) == {"text": VICTIM_TEXT}
                          and e[0] == 200), None),
            20, "the redial's turn_complete",
        )
        body = json.loads(redial[2])
        assert body["event"] == "turn_complete", body
        # The victim played as its own full event: cue → cells → close.
        assert "message:play" in body["events"] and "lifecycle:playback_done" in body["events"]

        # The page's own log shows the redial firing and succeeding.
        page.locator("#log div").filter(
            has_text="↻ redial — resending"
        ).first.wait_for(timeout=5000)
        page.locator("#log div").filter(has_text="POST ok").first.wait_for(timeout=5000)
        # The note is gone while in flight and stays gone after delivery.
        assert not note.is_visible()

        # --- exact one redial: the wire records it once -------------------
        # The recorder sees every exchange: 1 starter + 8 fills + the
        # victim's 429 + the redial's 200 = 11. The no-double-fire proof is
        # the victim body's exchange list: refused once, redialed exactly
        # once — a broken one-shot would add a third (a second 200).
        _wait_for(lambda: len(exchanges) >= 11, 5, "eleven /api/ziv/message exchanges")
        time.sleep(1.0)  # a broken one-shot would double-send within this window
        victim_exchanges = [e for e in exchanges
                            if json.loads(e[1]) == {"text": VICTIM_TEXT}]
        assert [e[0] for e in victim_exchanges] == [429, 200], \
            "the victim must be refused once and redialed exactly once"
        assert len(exchanges) == 11, [e[0] for e in exchanges]
        starter = next(e for e in exchanges
                       if json.loads(e[1]) == {"text": STARTER_TEXT})
        assert starter[0] == 200
        # The starter's turn released the queue: its close drained all 8
        # fills, each replayed as its own full event (the invariant the
        # whole redial story leans on).
        assert json.loads(starter[2])["drained"] == 8

        # The badge drains back to empty, live from health.
        page.locator("#queueBadge").filter(has_text="queue 0/8").wait_for(timeout=10000)


def test_free_marker_is_on_exactly_one_close_and_it_is_last(relay):
    """The redial's trigger is precise: the ``free`` flag rides exactly the
    last haptic close of a turn-with-drain — not the main close, not every
    replay's close. Proven on the raw wire with a Python-side WS device (the
    hub fans every frame out to all attached bands): one starter, one queued
    fill, then every frame until the wire goes quiet."""
    pytest.importorskip("websockets")
    from websockets.sync import client as ws_client

    base = relay.base
    host_port = base.split("//", 1)[1]
    with ws_client.connect(f"ws://{host_port}/ws") as conn:
        hello = json.loads(conn.recv(timeout=5))
        assert hello["type"] == "hello"

        # Starter turn in a thread (its POST returns only when the whole
        # turn is done); the fill is posted the moment the starter's kind
        # cue hits the wire, so it queues behind the playing turn.
        starter_result = {}

        def run_starter():
            starter_result["resp"] = httpx.post(
                f"{base}/api/ziv/message", json={"text": STARTER_TEXT}, timeout=30
            )

        th = threading.Thread(target=run_starter, daemon=True)
        th.start()
        # The fill must land while the gate is PLAYING (else it admits and
        # waits on the turn lock) — the starter's ``text`` cells frame is
        # exactly that signal, same sync the main test uses.
        while True:
            frame = json.loads(conn.recv(timeout=10))
            if frame.get("type") == "text" and STARTER_TEXT in frame.get("text", ""):
                break
        r = httpx.post(f"{base}/api/ziv/message", json={"text": "a"}, timeout=10)
        assert r.status_code == 200 and r.json().get("queued") is True, r.text
        th.join(timeout=30)
        assert starter_result["resp"].status_code == 200
        assert starter_result["resp"].json()["event"] == "turn_complete"

        # Drain the wire until it goes quiet: every frame of the turn, the
        # close, and the single replay. recv with a timeout is the quiet
        # detector — no sleeps racing frame timing.
        frames = []
        while True:
            try:
                frames.append(json.loads(conn.recv(timeout=3)))
            except TimeoutError:
                break

        closes = [f for f in frames if f.get("pattern") == "end-of-message"]
        marked = [f for f in closes if f.get("free") is True]
        assert len(closes) == 2, "starter close + the one replay's close"
        assert len(marked) == 1, "exactly one close may free the wrist"
        assert marked[0] is closes[-1], "the free close must be the LAST one"
        assert frames[-1] is marked[0] or frames[-1].get("free"), \
            "nothing haptic follows the free close on the wire"
