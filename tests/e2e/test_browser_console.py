"""The console in a real browser against the real relay: served at ``/console/``
with its CSP enforced, it signs in with a sender token, sends a message, shows
the normalised words, lists the utterance, and passes axe with no serious
violation. Selectors follow console/src/views/{signin,send,utterances}.ts.
"""
from __future__ import annotations

import re

import pytest
from relay_live import LiveRelay

pytestmark = pytest.mark.e2e


def sign_in(page, relay: LiveRelay, token: str) -> None:
    from playwright.sync_api import expect

    page.goto(f"{relay.http}/console/")
    expect(page).to_have_title("Sign in – Ziv console")
    expect(page.locator("main h1")).to_have_text("Sign in")
    page.fill("main form input[type=password]", token)
    page.click("main form button[type=submit]")
    expect(page.locator("main h1")).to_have_text("Send", timeout=10_000)
    expect(page.locator("#session-state")).to_have_text("Signed in. Token held in this tab only.")


def test_console_boots_under_its_csp_signs_in_sends_and_lists(relay: LiveRelay, page):
    from playwright.sync_api import expect

    # GET / lands on the console
    page.goto(relay.http + "/")
    expect(page).to_have_url(re.compile(r"/console/#?/?(signin)?$"))
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    sign_in(page, relay, relay.sender_token)
    assert not [e for e in errors if "Content Security Policy" in e], errors

    # send: the result shows the exact words the wearer will feel
    page.fill("main form textarea", "Meds at 9!")
    page.click("main form button[type=submit]")
    result = page.locator("main section.result")
    expect(result).to_be_visible(timeout=10_000)
    expect(result.locator("h2")).to_have_text("Sent")
    expect(result.locator("dd .words")).to_have_text("meds at nine")
    expect(result).to_contain_text("pending")
    expect(result.locator("dd .source")).to_contain_text("sender")
    expect(page.locator("#live-status")).to_have_text(re.compile(r"^Sent: meds at nine\."), timeout=5_000)
    assert page.evaluate("() => document.activeElement?.classList.contains('result')") is True
    [view] = relay.get("/utterances").json()
    assert view["words"] == ["meds", "at", "nine"] and view["state"] == "pending"

    # the utterance appears in the list, newest first, with its state
    page.click("nav a[href='#/utterances']")
    expect(page.locator("main h1")).to_have_text("Utterances")
    row = page.locator("main table tbody tr").first
    expect(row.locator("th.words")).to_have_text("meds at nine", timeout=10_000)
    expect(row).to_contain_text("pending")
    expect(row).to_contain_text("message")
    assert page.evaluate("() => sessionStorage.getItem('ziv.console.token')") == relay.sender_token
    assert page.evaluate("() => localStorage.length") == 0, "the token never reaches localStorage"


def test_console_ask_the_agent_shows_the_echo_source(relay: LiveRelay, page):
    """No model is configured on the test relay, so the agent path echoes the
    intent and the result says so. (No bring-your-own key here: that would make
    the relay call the real provider.)"""
    from playwright.sync_api import expect

    sign_in(page, relay, relay.sender_token)
    page.check("main form input[type=radio][value=agent]")
    expect(page.locator("main form button[type=submit]")).to_have_text("Ask the agent")
    expect(page.locator("main form select")).to_have_value("reminder")
    page.fill("main form input[maxlength='200']", "Take meds at 9")
    page.click("main form button[type=submit]")
    result = page.locator("main section.result")
    expect(result).to_be_visible(timeout=15_000)
    expect(result.locator("h2")).to_have_text("Composed")
    expect(result.locator("dd .words")).to_have_text("take meds at nine")
    expect(result.locator("dd .source")).to_have_attribute("data-source", "echo")
    expect(result.locator("dd .source")).to_have_text(re.compile(r"^echo: "))
    expect(page.locator("#live-status")).to_have_text(re.compile(r"^Composed: take meds at nine\. .*Source echo\.$"), timeout=5_000)
    [view] = relay.get("/utterances").json()
    assert view["source"] == "echo" and view["kind"] == "reminder" and view["words"] == ["take", "meds", "at", "nine"]


def test_console_has_no_serious_axe_violations(relay: LiveRelay, axe_page, axe_source: str):
    from playwright.sync_api import expect

    page = axe_page
    sign_in(page, relay, relay.sender_token)
    page.fill("main form textarea", "all good")
    page.click("main form button[type=submit]")
    expect(page.locator("main section.result")).to_be_visible(timeout=10_000)
    report: dict[str, list[str]] = {}
    for route in ("send", "utterances", "schedule", "prefs", "health"):
        page.click(f"nav a[href='#/{route}']")
        expect(page.locator("nav a[aria-current=page]")).to_have_attribute("href", f"#/{route}")
        page.add_script_tag(content=axe_source)
        results = page.evaluate("async () => await axe.run(document.body)")
        bad = [f"{v['impact']} {v['id']}: {v['help']}" for v in results["violations"] if v["impact"] in ("serious", "critical")]
        if bad:
            report[route] = bad
    assert report == {}, report
