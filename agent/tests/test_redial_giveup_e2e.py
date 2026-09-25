"""End-to-end: the redial's give-up is LOUD — a visible dead-end, not a quiet drop.

The channel's rule is loud-not-silent for every no the wearer can feel; the
redial's budget exhaustion is a no the wearer must see. After three armed
redials are each refused again, the note must STAY on screen naming the dead
end ("gave up after 3 tries — the wrist never freed"), the wire log must
carry the give-up line, and a wearer action (a manual send) must clear it.

How the scenario is made deterministic: the page's own ``/api/ziv/message``
POSTs are intercepted with Playwright's ``page.route`` and answered 429 —
so every redial the page fires is refused again and the budget runs out at
exactly three. The *starter* turn that generates the three free closes is
posted server-side via httpx (routing intercepts only the page's requests),
and its close frames arrive over the page's real WebSocket, driving
``fireRedialIfFree`` three times.

Marked ``e2e``: excluded from the default hermetic suite — run explicitly
with ``pytest -m e2e``. Self-contained like ``test_redial_e2e.py``.
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

pytest.importorskip("playwright")  # before e2e_helpers: skip, never error

import e2e_helpers  # noqa: E402

pytestmark = pytest.mark.e2e

FAKE_MODEL_SECONDS = "0.3"


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


class _RecordingASGI:
    """Record every /api/ziv/message exchange (status + both bodies)."""

    def __init__(self, inner, path: str):
        self._inner = inner
        self._path = path
        self.exchanges = []

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != self._path:
            await self._inner(scope, receive, send)
            return
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
    """The real relay app, live in-process on an ephemeral port."""
    import ziv_store
    import ziv_server

    original_data_dir = ziv_store.DATA_DIR
    original_fake = os.environ.get("ZIV_FAKE_MODEL_SECONDS")
    data_dir = tmp_path_factory.mktemp("ziv_giveup_data")
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
        importlib.reload(ziv_server)


def _health_up(base):
    try:
        return httpx.get(f"{base}/api/ziv/health", timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


def test_redial_giveup_is_a_visible_dead_end(relay):
    base = relay.base

    # The wearer's fastest pace keeps the three starter turns short.
    r = httpx.post(f"{base}/api/ziv/prefs", json={"cell_gap_ms": 250}, timeout=5)
    assert r.status_code == 200 and r.json()["cell_gap_ms"] == 250

    with e2e_helpers.browser_page() as page:
        console = []
        page.on("console", lambda m: console.append(m))
        page.goto(f"{base}/ziv_client/index.html",
                  wait_until="domcontentloaded", timeout=30000)
        page.locator("#queueBadge").wait_for(state="visible", timeout=10000)
        page.locator("#state").filter(has_text="connected").wait_for(timeout=10000)
        page.locator("#btnUnlock").click()

        VICTIM = "call me back"

        # Every POST the PAGE makes is refused — the redials can never
        # succeed, so the budget exhausts deterministically. Server-side
        # starters below use httpx and are NOT intercepted.
        def refuse_page_posts(route):
            route.fulfill(
                status=429,
                content_type="application/json",
                body=json.dumps({"detail":
                                 "message rejected: the replay queue is full "
                                 "(8 queued) — the wearer releases it after the "
                                 "current turn; try again later"}),
            )

        page.route("**/api/ziv/message", refuse_page_posts)

        # --- the victim is refused; the redial arms -----------------------
        page.locator("#msg").fill(VICTIM)
        page.locator("#btnSend").click()
        note = page.locator("#redialNote")
        note.wait_for(state="visible", timeout=5000)
        assert VICTIM in note.inner_text()
        assert "3 chances left" in note.inner_text()

        # --- three starter turns → three free closes → three redials -----
        for turn in range(3):
            resp = httpx.post(f"{base}/api/ziv/message",
                              json={"text": f"starter{turn}"}, timeout=30)
            assert resp.status_code == 200, resp.text
            assert resp.json()["event"] == "turn_complete"
            if turn < 2:
                # Between closes: the note re-arms with a smaller budget.
                _wait_for(
                    lambda: VICTIM in note.inner_text()
                    and "chances left" in note.inner_text(),
                    10, f"the redial to re-arm after close {turn + 1}",
                )

        # --- the third refused redial is a DEAD END, not a quiet drop ----
        _wait_for(
            lambda: "gave up after 3 tries" in note.inner_text(),
            10, "the dead-end note",
        )
        assert "the wrist never freed" in note.inner_text()
        assert VICTIM in note.inner_text()
        assert note.is_visible()
        # The log carries the give-up line too — loud, not silent.
        page.locator("#log div").filter(
            has_text="↹ redial gave up after 3 chances"
        ).first.wait_for(timeout=5000)

        # The dead end is not stuck forever: the wearer's manual send clears
        # it. Route passthrough first — the manual send must really land.
        page.unroute("**/api/ziv/message")
        page.locator("#btnSend").click()
        note.wait_for(state="hidden", timeout=10000)
        assert not note.is_visible()
        redelivered = _wait_for(
            lambda: next((e for e in relay.exchanges
                          if json.loads(e[1]) == {"text": VICTIM}
                          and e[0] == 200), None),
            15, "the manual send's turn_complete",
        )
        assert redelivered[0] == 200
        # ...and a later refusal starts from a clean budget again: the
        # successful send cleared the per-message budget (RD.lastLabel).
        page.route("**/api/ziv/message", refuse_page_posts)
        page.locator("#msg").fill(VICTIM)
        page.locator("#btnSend").click()
        _wait_for(
            lambda: VICTIM in note.inner_text()
            and "3 chances left" in note.inner_text(),
            10, "the fresh budget on the next refusal",
        )
