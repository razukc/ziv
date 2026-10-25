"""
Ziv e2e helper primitives.

Browser-based end-to-end tests for the Ziv phone prototype: connect to the
relay's PWA, drive the phone through the interaction loop, and assert the
haptic + timing behavior that the wearer experiences.

Split from the old SkillForge e2e helpers during the Sep 2026 handover:
Ziv is a standalone repo and these helpers now target the Ziv relay
(http://localhost:8000) exclusively. Nothing here talks to a SkillForge
instance anywhere.
"""

from __future__ import annotations

import time
from contextlib import contextmanager

from playwright.sync_api import expect
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# URL constants
# ---------------------------------------------------------------------------

# The Ziv relay serves its PWA (ziv_client/index.html) from /ziv_client/ on
# this host+port. Single-process dev runs on 8000; the demo deploy target is
# whatever writable_hosts.run_host + writable_hosts.run_port resolves to at
# runtime (clamped to 127.0.0.1 for a HOME tether, or a public host when the
# relay is reachable from the internet).
RELAY_HOST = "127.0.0.1"
RELAY_PORT = 8000
RELAY_BASE_URL = f"http://{RELAY_HOST}:{RELAY_PORT}"
RELAY_PWA_URL = f"{RELAY_BASE_URL}/ziv_client/"


# ---------------------------------------------------------------------------
# page lifecycle
# ---------------------------------------------------------------------------


@contextmanager
def browser_page():
    """A headless chromium page as a context manager — the shape both e2e
    suites use (``with browser_page() as page:``). Owns the playwright
    driver and browser lifecycle: entering starts them, exiting closes them."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            yield browser.new_context().new_page()
        finally:
            browser.close()


def power_on(page, timeout: float = 10.0) -> None:
    """Bring the band from its off screen to the locked screen.

    The page opens powered down; ``#offToggle`` is the side button. Clicking
    it also supplies the sticky user activation Chrome requires before
    ``navigator.vibrate`` works, which is why the tests do not need a
    separate unlock gesture.
    """
    page.locator("#queueBadge").wait_for(state="visible", timeout=timeout * 1000)
    page.locator("#state").filter(has_text="connected").wait_for(
        timeout=timeout * 1000
    )
    if not page.locator("#btnWrite").is_visible():
        page.locator("#offToggle").click()
    page.locator("#btnWrite").wait_for(state="visible", timeout=timeout * 1000)


def open_compose(page, timeout: float = 5.0) -> str:
    """Open the phone's visible compose surface; return ``"screen"`` or ``"sheet"``.

    From the locked screen the large **Write a message** button opens the
    compose screen. While a turn owns the screens, that button is hidden but
    the device bar exposes **Write a message** / ``#btnWriteDuring``, which
    opens the busy-sheet over the still-running turn. Both paths are the
    wearer's real taps — no ``page.evaluate`` of internal send handlers.
    """
    if page.locator("#composeSheetInput").is_visible():
        return "sheet"
    if page.locator("#composeInput").is_visible():
        return "screen"
    during = page.locator("#btnWriteDuring")
    if during.is_visible():
        during.click()
        page.locator("#composeSheetInput").wait_for(
            state="visible", timeout=timeout * 1000
        )
        return "sheet"
    write = page.locator("#btnWrite")
    write.wait_for(state="visible", timeout=timeout * 1000)
    write.click()
    page.locator("#composeInput").wait_for(
        state="visible", timeout=timeout * 1000
    )
    return "screen"


def send_from_compose(page, text: str) -> str:
    """Type ``text`` into the visible compose surface and press its Send button.

    Returns the surface used (``"screen"`` or ``"sheet"``) so a caller can
    assert that a mid-turn send really went through the visible busy-sheet.
    """
    mode = open_compose(page)
    if mode == "sheet":
        page.locator("#composeSheetInput").fill(text)
        page.locator("#btnSheetSend").click()
    else:
        page.locator("#composeInput").fill(text)
        page.locator("#btnSendCompose").click()
    return mode


def wait_hydrated(page, timeout: float = 8.0) -> None:
    """Wait until the Ziv PWA has mounted and connected to the relay.

    The PWA reports connected state by flipping the header row's status text
    away from its loading placeholder. We wait for that text to stabilize.
    """
    page.wait_for_function(
        """
        () => {
          const root = document.querySelector('#ziv-root') || document.body;
          if (!root) return false;
          const status = root.querySelector('[data-status]') || root.querySelector('h3');
          if (!status) return false;
          const text = (status.textContent || '').trim().toLowerCase();
          return text !== '' && text !== 'connecting' && text !== 'connecting…'
            && !text.includes('connecting');
        }
        """,
        timeout=timeout * 1000,
    )


def open_pwa(page) -> None:
    """Navigate the page to the Ziv PWA served by the relay."""
    page.goto(RELAY_PWA_URL, wait_until="networkidle")
    wait_hydrated(page)
