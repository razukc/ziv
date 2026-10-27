"""End-to-end: two tabs are two bands, not two windows onto one wrist.

The session split is easy to regress (a shared hub looks harmless until every
open client feels the same message). This test drives the real client in two
pages of one browser context:

1. both tabs open the band and get different session ids;
2. tab A sends a message and only A's wire log / band surface reacts;
3. tab B sends a message and only B reacts.

It is marked ``e2e`` like the other browser suites and starts its own relay on
an ephemeral port, so it needs no manually running server.
"""

from __future__ import annotations

import importlib
import os
import socket
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

pytest.importorskip("playwright")  # before e2e_helpers: skip, never error

import e2e_helpers  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

pytestmark = pytest.mark.e2e

FAKE_MODEL_SECONDS = "0.3"
CELL_GAP_MS = 250  # the wearer's fastest pace; keeps two turns short


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


def _health_up(base: str) -> bool:
    try:
        return httpx.get(f"{base}/api/ziv/health", timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture()
def relay(tmp_path):
    """The real relay app on an ephemeral port, with a temp wearer store."""
    import ziv_server
    import ziv_store

    original_data_dir = ziv_store.DATA_DIR
    original_fake = os.environ.get("ZIV_FAKE_MODEL_SECONDS")
    data_dir = tmp_path / "ziv_data"
    data_dir.mkdir()
    os.environ["ZIV_FAKE_MODEL_SECONDS"] = FAKE_MODEL_SECONDS
    ziv_store.DATA_DIR = data_dir
    importlib.reload(ziv_server)

    port = _free_port()
    import uvicorn

    config = uvicorn.Config(ziv_server.app, host="127.0.0.1", port=port,
                            log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        _wait_for(lambda: _health_up(base), 15, "the relay to start")
        yield SimpleNamespace(base=base)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        ziv_store.DATA_DIR = original_data_dir
        if original_fake is None:
            os.environ.pop("ZIV_FAKE_MODEL_SECONDS", None)
        else:
            os.environ["ZIV_FAKE_MODEL_SECONDS"] = original_fake
        importlib.reload(ziv_server)  # pristine module state for later tests


def _is_message_post(response) -> bool:
    return (response.url.endswith("/api/ziv/message")
            and response.request.method == "POST")


def test_one_tabs_message_never_plays_on_the_other(relay):
    base = relay.base
    r = httpx.post(f"{base}/api/ziv/prefs",
                   json={"cell_gap_ms": CELL_GAP_MS}, timeout=5)
    assert r.status_code == 200 and r.json()["cell_gap_ms"] == CELL_GAP_MS

    with e2e_helpers.browser_page() as page_a:
        page_b = page_a.context.new_page()
        try:
            for page in (page_a, page_b):
                page.goto(f"{base}/ziv_client/index.html",
                          wait_until="domcontentloaded", timeout=30000)
                e2e_helpers.open_band(page)

            sid_a = page_a.evaluate("S.sessionId")
            sid_b = page_b.evaluate("S.sessionId")
            assert sid_a and sid_b and sid_a != sid_b, (sid_a, sid_b)
            assert page_a.evaluate("S.ws.url").endswith("session=" + sid_a)
            assert page_b.evaluate("S.ws.url").endswith("session=" + sid_b)

            sessions = httpx.get(f"{base}/api/ziv/health", timeout=5).json()["sessions"]
            by_id = {s["id"]: s for s in sessions}
            assert {sid_a, sid_b} <= set(by_id), sessions
            assert by_id[sid_a]["devices"] == 1 and by_id[sid_b]["devices"] == 1

            # The operator badge counts attached bands from the same health
            # payload, so both tabs must read the plural form.
            for page in (page_a, page_b):
                page.locator("#queueBadge").filter(
                    has_text="2 bands"
                ).wait_for(timeout=6000)

            # --- the badge drills down to each band's own queue ------------
            page_a.locator("#queueBadge").click()
            list_a = page_a.locator("#bandList")
            list_a.wait_for(state="visible", timeout=5000)
            page_a.locator("#bandList .band-row").first.wait_for(timeout=5000)
            assert page_a.locator("#queueBadge").get_attribute(
                "aria-expanded"
            ) == "true"
            rows = list_a.locator(".band-row")
            assert rows.count() == 2, rows.all_inner_texts()
            texts = [rows.nth(i).inner_text() for i in range(2)]
            assert any(sid_a[:8] in t for t in texts), texts
            assert any(sid_b[:8] in t for t in texts), texts
            assert all("queue 0/8" in t for t in texts), texts
            # The other tab's popover is its own, not a shared panel.
            assert page_b.locator("#bandList").is_hidden()
            page_a.keyboard.press("Escape")
            list_a.wait_for(state="hidden", timeout=3000)

            # --- A speaks: only A's wire and band surface may move ---------
            with page_a.expect_response(_is_message_post, timeout=20000) as info:
                assert e2e_helpers.send_from_compose(page_a, "alpha") == "screen"
            assert info.value.json()["event"] == "turn_complete"

            page_a.locator("#log div").filter(
                has_text="message: alpha"
            ).first.wait_for(timeout=5000)
            assert "message: alpha" in page_a.locator("#log").inner_text()
            # The POST resolves after A's close is on A's wire, so any leak
            # would already have arrived here. Give the other page's JS one
            # frame to render it before asserting absence.
            page_b.wait_for_timeout(500)
            assert "alpha" not in page_b.locator("#log").inner_text(), (
                "A's message crossed into B's stream:\n"
                + page_b.locator("#log").inner_text()[:800]
            )
            assert page_b.evaluate("S.currentScreen") == "ready", (
                "B's band surface reacted to A's turn"
            )
            assert page_b.evaluate("S.queueDepth") == 0

            # --- the popover's last-frame stamp is per band -----------------
            page_a.locator("#queueBadge").click()
            list_now = page_a.locator("#bandList")
            list_now.wait_for(state="visible", timeout=5000)
            rows_now = list_now.locator(".band-row")
            expect(rows_now).to_have_count(2, timeout=5000)
            expect(rows_now.filter(has_text=sid_a[:8])).to_contain_text(
                "last frame", timeout=6000
            )
            expect(rows_now.filter(has_text=sid_b[:8])).to_contain_text(
                "no frames yet", timeout=6000
            )
            page_a.keyboard.press("Escape")
            list_now.wait_for(state="hidden", timeout=3000)

            # --- B speaks: A must stay exactly where it was -----------------
            a_log_before = page_a.locator("#log").inner_text()
            with page_b.expect_response(_is_message_post, timeout=20000) as info_b:
                assert e2e_helpers.send_from_compose(page_b, "bravo") == "screen"
            assert info_b.value.json()["event"] == "turn_complete"

            page_b.locator("#log div").filter(
                has_text="message: bravo"
            ).first.wait_for(timeout=5000)
            assert "message: bravo" in page_b.locator("#log").inner_text()
            page_a.wait_for_timeout(500)
            assert "bravo" not in page_a.locator("#log").inner_text(), (
                "B's message crossed into A's stream:\n"
                + page_a.locator("#log").inner_text()[:800]
            )
            assert page_a.locator("#log").inner_text() == a_log_before, (
                "A's wire log changed while only B was playing"
            )
        finally:
            page_b.close()
