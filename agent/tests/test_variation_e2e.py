"""End-to-end: create-a-variation composes a new pipeline from the displayed one.

Composes a pipeline in mock mode, opens the variation composer from the
pipeline header, rewrites the task, and verifies a NEW pipeline lands in the
results view and history with the reworded task — while the original stays in
history. The seeded (live) path — where the LLM actually adapts the original
plan — is exercised by the hermetic API tests; here the UI flow is proven.

Marked ``e2e``: excluded from the default hermetic suite via
``addopts = -m \"not e2e\"`` — run it explicitly with ``pytest -m e2e``.
"""
import json

import pytest

import e2e_helpers

FRONTEND = "http://localhost:3000"

pytest.importorskip("playwright")

pytestmark = pytest.mark.e2e

NEW_TASK = "Move the blue cup from the counter to the top shelf"


def test_variation_rewrites_task_and_adds_history_entry():
    with e2e_helpers.browser_page() as page:
        page.goto(FRONTEND, wait_until="domcontentloaded", timeout=30000)
        e2e_helpers.wait_hydrated(page)

        # 1. Compose a pipeline in mock mode (the default).
        page.locator(".suggestion-chip").first.click()
        page.get_by_role("button", name="compose", exact=True).click()
        page.get_by_role("button", name="✏️ edit steps").wait_for(timeout=40000)

        # 2. Open the variation composer from the pipeline header.
        page.get_by_role("button", name="create variation").click()
        task_box = page.locator('[data-testid="variation-task"]')
        task_box.wait_for(timeout=10000)
        # It is prefilled with the original task, then reworded.
        assert task_box.input_value().strip(), "variation task was not prefilled"

        # 3. Reword the task and compose the variation.
        task_box.fill(NEW_TASK)
        page.get_by_role("button", name="compose variation", exact=True).click()

        # 4. The variation lands as a new result with the reworded task.
        page.get_by_role("button", name="✏️ edit steps").wait_for(timeout=40000)
        body = page.locator("body").inner_text()
        assert NEW_TASK in body, "reworded task not rendered in the new result"
        assert "2 pipelines composed" in body, "variation did not add a history entry"

        # The new pipeline's task field carries the rewrite; both entries remain.
        page.get_by_role("button", name="{ }").click()
        composed = json.loads(page.locator("pre").inner_text())
        assert composed["task"] == NEW_TASK, "pipeline task field was not updated"
