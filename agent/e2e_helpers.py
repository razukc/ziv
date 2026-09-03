"""Shared helpers for browser-based live checks.

Used by the ``e2e``-marked pytest tests (agent/tests/) and by the live
verification CLI (agent/live_check.py), so the boilerplate for launching a
system browser and waiting for the React page to hydrate lives in one place.
"""

from contextlib import contextmanager

import httpx


def servers_up(frontend="http://localhost:3000", backend="http://localhost:8000") -> bool:
    """True when both the frontend and its proxied backend answer health."""
    for url in (f"{backend}/api/health", f"{frontend}/api/health"):
        try:
            if httpx.get(url, timeout=3.0).status_code != 200:
                return False
        except httpx.HTTPError:
            return False
    return True


@contextmanager
def browser_page(channels=("chrome", "msedge")):
    """A headless Playwright page in a system browser (no download needed).

    Tries each ``channels`` entry and raises if none is available.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = None
        for channel in channels:
            try:
                browser = p.chromium.launch(channel=channel, headless=True)
                break
            except Exception:
                continue
        if browser is None:
            raise RuntimeError("no system Chrome/Edge available to Playwright")
        try:
            yield browser.new_page()
        finally:
            browser.close()


def wait_hydrated(page, timeout=30000):
    """Wait until React has hydrated the page.

    The mock/live segmented control in the compose box is server-rendered, so
    its presence means the shell is up; the extra pause lets React attach
    event handlers so later synthetic clicks reach them reliably.
    """
    page.locator("[data-mode=mock]").wait_for(timeout=timeout)
    page.wait_for_timeout(1500)
