"""Fixtures for the browser end-to-end tests (``-m e2e``; deselected by default).

A real relay serving the built ``/client/`` and ``/console/`` on a loopback
port, and a headless Chromium through Playwright. Both front ends are built
once per session when their ``node_modules`` exist; otherwise the existing
``dist`` is used, and the tests skip cleanly when there is none or when the
browser cannot launch on this host.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from relay_live import CONSOLE_DIR, LiveRelay, build_front_end

AXE = CONSOLE_DIR / "node_modules" / "axe-core" / "axe.min.js"


@pytest.fixture(scope="session")
def front_ends() -> None:
    for name, need in (("client", ("index.html",)), ("console", ("index.html", "manifest.json"))):
        reason = build_front_end(name, need=need)
        if reason:
            pytest.skip(reason)


@pytest.fixture(scope="session")
def playwright_browser(front_ends):
    from playwright.sync_api import Error as PlaywrightError, sync_playwright

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except PlaywrightError as exc:  # missing system libraries, no browser download
            pytest.skip(f"chromium cannot launch here: {str(exc).splitlines()[0]}")
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture()
def relay(tmp_path: Path, front_ends):
    with LiveRelay(tmp_path, serve_front_ends=True) as live:
        assert live.settings.client_dist and live.settings.console_dist, "both front ends must be mounted"
        yield live


@pytest.fixture()
def page(playwright_browser):
    """A page with the console's CSP enforced, as a wearer's browser would."""
    context = playwright_browser.new_context()
    try:
        yield context.new_page()
    finally:
        context.close()


@pytest.fixture()
def axe_page(playwright_browser):
    """A page that lets the test inject axe-core; the CSP is proven separately on ``page``."""
    context = playwright_browser.new_context(bypass_csp=True)
    try:
        yield context.new_page()
    finally:
        context.close()


@pytest.fixture(scope="session")
def axe_source() -> str:
    if not AXE.is_file():
        pytest.skip("axe-core is not installed under console/node_modules")
    return AXE.read_text(encoding="utf-8")
