"""End-to-end: composed pipelines persist across reloads and can be reopened.

The iteration loop for a compose that needs another attempt: mock-compose a
pipeline, reload the page, and prove the history panel came back from
localStorage; then reopen the pipeline via the card's "open in editor"
action, confirm the restored content matches, tweak it, and re-export
LLM-free.

Marked ``e2e``: excluded from the default hermetic suite via
``addopts = -m \"not e2e\"`` — run it explicitly with ``pytest -m e2e``.
"""
import json

import pytest

import e2e_helpers

FRONTEND = "http://localhost:3000"

pytest.importorskip("playwright")

pytestmark = pytest.mark.e2e


def test_history_persists_and_reopens_after_reload():
    with e2e_helpers.browser_page() as page:
        page.goto(FRONTEND, wait_until="domcontentloaded", timeout=30000)
        e2e_helpers.wait_hydrated(page)

        # 1. Compose in mock mode (the default) from a suggestion chip.
        page.locator(".suggestion-chip").first.click()
        page.get_by_role("button", name="compose", exact=True).click()
        page.get_by_role("button", name="✏️ edit steps").wait_for(timeout=40000)

        # Record the composed pipeline (task text + step names) from the JSON tab.
        page.get_by_role("button", name="{ }").click()
        composed = json.loads(page.locator("pre").inner_text())
        assert len(composed["subtasks"]) >= 3
        task_text = composed["task"]
        names = [s["name"] for s in composed["subtasks"]]

        # 2. Reload — the history panel must survive via localStorage.
        page.goto(FRONTEND, wait_until="domcontentloaded", timeout=30000)
        e2e_helpers.wait_hydrated(page)
        page.get_by_title("open in editor — restore this pipeline and tweak steps").first.wait_for(timeout=15000)
        body = page.locator("body").inner_text()
        assert "1 pipeline composed" in body, "history did not persist across reload"
        assert f"{len(names)} steps" in body, "persisted history card is missing its stats"

        # 3. Open the pipeline back into the editor from history.
        page.get_by_title("open in editor — restore this pipeline and tweak steps").first.click()
        page.get_by_text("pipeline_metadata").wait_for(timeout=15000)
        assert task_text in page.locator("body").inner_text(), "restored task text missing"

        # The restored content matches what was composed.
        page.get_by_role("button", name="{ }").click()
        restored = json.loads(page.locator("pre").inner_text())
        assert [s["name"] for s in restored["subtasks"]] == names, "reopened pipeline differs from the original"

        # 4. Tweak (remove a step) and re-export LLM-free — the iterate loop.
        page.get_by_role("button", name="✏️ edit steps").click()
        page.get_by_text("edit mode — reorder").wait_for(timeout=10000)
        page.get_by_title("remove step").nth(2).click()
        page.get_by_role("button", name="done").click()
        page.get_by_text("re-export edited pipeline").wait_for(timeout=10000)
        page.get_by_text("re-export edited pipeline").click()
        page.get_by_text("package ready").wait_for(timeout=15000)

        # The re-export packaged the edited (one-step-fewer) pipeline.
        page.get_by_role("button", name="{ }").click()
        reexported = json.loads(page.locator("pre").inner_text())
        assert len(reexported["subtasks"]) == len(names) - 1, "re-export did not use the edited pipeline"
