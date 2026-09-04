"""End-to-end: the session auto-retry hint appears when the model blips often.

Live composes auto-retry transient LLM blips server-side, and the UI tallies
those per session (``sf-session-retries`` in sessionStorage, so the count
survives reloads within the tab). Once the tally reaches 3, the app shows a
hint suggesting mock mode or a simpler task. A real model blip can't be forced
on demand, so the test seeds the sessionStorage tally directly — no compose,
no backend, no credits — and verifies the hint's behavior across a same-tab
reload and the mock/live switch (the suggestion the hint makes).

Marked ``e2e``: excluded from the default hermetic suite via
``addopts = -m \"not e2e\"`` — run it explicitly with ``pytest -m e2e``.
"""
import pytest

import e2e_helpers

FRONTEND = "http://localhost:3000"

pytest.importorskip("playwright")

pytestmark = pytest.mark.e2e


def test_retry_hint_tracks_session_and_resets_on_mock_switch():
    with e2e_helpers.browser_page() as page:
        page.goto(FRONTEND, wait_until="domcontentloaded", timeout=30000)
        e2e_helpers.wait_hydrated(page)
        hint = page.locator('[data-testid="blip-hint"]')
        assert not hint.is_visible(), "no hint with an empty session"

        # Seed a session that already logged several auto-retries, then reload
        # in the same tab (sessionStorage survives — this is the persistence
        # the app promises). The hint must stay hidden while in mock mode.
        page.evaluate("sessionStorage.setItem('sf-session-retries', '3')")
        page.reload(wait_until="domcontentloaded")
        e2e_helpers.wait_hydrated(page)
        assert not hint.is_visible(), "hint must not show in mock mode"

        # Switching to live surfaces the nudge (no compose needed).
        page.get_by_role("button", name="live", exact=True).click()
        hint.wait_for(timeout=10000)
        assert "3 times this session" in hint.inner_text()
        assert "try mock mode or a simpler task" in hint.inner_text()

        # Taking the suggestion (back to mock) clears the hint and the tally.
        page.get_by_role("button", name="mock", exact=True).click()
        assert not hint.is_visible(), "hint must clear when mock mode is chosen"
        assert (
            page.evaluate("sessionStorage.getItem('sf-session-retries')") is None
        ), "mock switch must reset the session tally"
