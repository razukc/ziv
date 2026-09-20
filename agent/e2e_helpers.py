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


def browser_page(playwright) -> "Page":
    """Open a new chromium context page bound to the given Playwright object."""
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    return page


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
