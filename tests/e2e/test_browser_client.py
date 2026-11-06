"""The web device renderer in a real browser against the real relay: served by
the relay at ``/client/``, it defaults to the page origin, enrolls with a code,
starts, speaks hello over the same-origin WebSocket, and plays a message the
sender submitted over HTTP, phase by phase, until the relay records ``played``.

Selectors are the ids in client/index.html; the phase wording is
``phaseText()`` in client/src/app.ts.
"""
from __future__ import annotations

import re

import pytest
from relay_live import LiveRelay

pytestmark = pytest.mark.e2e


def test_client_enrolls_starts_and_plays_a_message_to_played(relay: LiveRelay, page):
    from playwright.sync_api import expect

    page.goto(f"{relay.http}/client/")
    expect(page).to_have_title("Ziv web renderer")
    # served by the relay: the relay URL defaults to this page's origin
    expect(page.locator("#relay-url")).to_have_value(relay.http)
    expect(page.locator("#start")).to_be_disabled()

    # enroll this browser with the code the console (here: the service layer) minted
    page.locator("details summary").click()
    page.fill("#enroll-code", relay.enroll_code)
    page.fill("#device-name", "e2e browser")
    page.click("#enroll")
    expect(page.locator("#enroll-msg")).to_contain_text("Enrolled as d_", timeout=10_000)
    expect(page.locator("#device-key")).to_have_value(re.compile(r".{16,}"))
    expect(page.locator("#start")).to_be_enabled()

    # start: GET /spec, then hello first on the same-origin socket
    page.click("#start")
    expect(page.locator("#status")).to_have_text(re.compile(r"^connected · spec v\d+"), timeout=10_000)
    [device] = relay.get("/devices").json()
    assert device["connected"] is True and device["profile"] == "single_actuator" and device["name"] == "e2e browser"

    # a sender submits over HTTP; the page shows the words and walks the phases to the close
    r = relay.post("/utterances", {"text": "Go now", "label": "mum"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert r.json()["words"] == ["go", "now"]
    expect(page.locator("#words")).to_have_text("go now", timeout=10_000)
    expect(page.locator("#from")).to_have_text("message from mum")
    expect(page.locator("#phase-live")).to_have_text(re.compile(r"^word 1 of 2: go"), timeout=15_000)
    expect(page.locator("#words .letter.active")).to_have_count(1)
    expect(page.locator("#phase-live")).to_have_text("end of message", timeout=30_000)

    # the relay saw cue, words and close, then the close finished on the actuator
    view = relay.wait_state(uid, "played", timeout=15)
    assert view["device"] == device["device"] and view["reason"] is None
    expect(page.locator("#status")).to_have_text(re.compile(r"idle, nothing waiting$"), timeout=10_000)
    log = page.locator("#log").inner_text()
    assert "→ hello profile=single_actuator" in log and "→ played id=" in log
    assert "go now" not in log, "the wire log never carries message text"


def test_client_page_refuses_while_hidden_and_recovers_when_visible(relay: LiveRelay, page):
    """The browser's own rule (docs/ARCHITECTURE.md §5.4): a hidden page cannot
    vibrate, so it refuses with ``hidden``; the relay keeps the message pending
    and re-offers it on the page's fresh hello when it is visible again."""
    from playwright.sync_api import expect

    _, key = relay.enroll_device(name="e2e hidden")
    page.goto(f"{relay.http}/client/")
    page.fill("#device-key", key)
    page.click("#start")
    expect(page.locator("#status")).to_have_text(re.compile(r"^connected"), timeout=10_000)

    uid = relay.post("/utterances", {"text": "go now"}).json()["id"]
    expect(page.locator("#words")).to_have_text("go now", timeout=10_000)
    # simulate the tab going to the background: document.hidden flips and visibilitychange fires
    page.evaluate(
        "() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });"
        " document.dispatchEvent(new Event('visibilitychange')); }"
    )
    pending = relay.wait_state(uid, "pending", timeout=10)
    assert pending["reason"] == "hidden"
    page.evaluate(
        "() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });"
        " document.dispatchEvent(new Event('visibilitychange')); }"
    )
    expect(page.locator("#words")).to_have_text("go now", timeout=10_000)
    view = relay.wait_state(uid, "played", timeout=30)
    assert view["reason"] is None
