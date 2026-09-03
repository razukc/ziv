"""End-to-end: human-editable pipeline view.

Drives a real browser through the edit flow in mock mode (no backend or LLM
needed): compose a pipeline, enter edit mode, reorder + remove steps, verify
the displayed pipeline reflects the edits, and re-export.

Marked ``e2e``: excluded from the default hermetic suite via
``addopts = -m "not e2e"`` — run with ``pytest -m e2e``.
"""
import json

import pytest

import e2e_helpers

FRONTEND = "http://localhost:3000"

pytest.importorskip("playwright")

pytestmark = pytest.mark.e2e


def test_edit_reorder_remove_and_reexport():
    with e2e_helpers.browser_page() as page:
        page.goto(FRONTEND, wait_until="domcontentloaded", timeout=30000)
        # Wait for hydration so synthetic clicks reach React.
        e2e_helpers.wait_hydrated(page)

        # 1. Compose (mock mode is the default). Set the task via a
        #    suggestion chip — it goes through React state reliably.
        page.locator(".suggestion-chip").first.click()
        page.get_by_role("button", name="compose", exact=True).click()
        page.get_by_role("button", name="✏️ edit steps").wait_for(timeout=40000)

        # Read the composed step names from the JSON tab.
        page.get_by_role("button", name="{ }").click()
        steps = json.loads(page.locator("pre").inner_text())["subtasks"]
        assert len(steps) >= 3
        original = [s["name"] for s in steps]
        first, second, third = original[0], original[1], original[2]

        # 2. Enter edit mode: swap steps 1<->2, remove step 3.
        page.get_by_role("button", name="✏️ edit steps").click()
        page.get_by_text("edit mode — reorder").wait_for(timeout=10000)

        # Move the first step down -> swaps with the second.
        page.get_by_title("move down").first.click()
        # Remove the originally-third step (still at index 2 after the swap).
        page.get_by_title("remove step").nth(2).click()

        body = page.locator("body").inner_text()
        assert "5 steps ·" in body, "step count did not update after edits"

        # 3. Done editing: the displayed pipeline is edited but not yet
        #    published, so the share-link area shows the re-export hint.
        page.get_by_role("button", name="done").click()
        assert "edited — re-export to publish a new link" in page.locator("body").inner_text()

        # 4. The JSON tab reflects the edits (new order, step removed).
        page.get_by_role("button", name="{ }").click()
        edited = json.loads(page.locator("pre").inner_text())["subtasks"]
        names = [s["name"] for s in edited]
        expected = [second, first] + original[3:]  # swap 1<->2, drop original[2]
        assert names == expected, f"unexpected order: {names}"
        assert third not in names, f"step was not removed: {names}"
        assert all(s["order"] == i + 1 for i, s in enumerate(edited)), "orders not renumbered"

        # 5. Re-export (mock): the block is re-enabled for edited pipelines.
        page.get_by_text("re-export edited pipeline").click()
        page.get_by_text("package ready").wait_for(timeout=10000)
        assert "sf_g1_manipulation" in page.locator("body").inner_text()
        page.get_by_text("Validate Package").click()
        page.get_by_text("package valid").wait_for(timeout=10000)
