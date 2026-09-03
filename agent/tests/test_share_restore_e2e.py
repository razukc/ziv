"""End-to-end: open a live share link in a real browser and verify the
pipeline renders from the URL hash.

The frontend restores shared pipelines client-side: on a ``#p=<id>`` hash it
fetches ``/api/pipeline/{id}`` (proxied to the backend) and renders the
result. This test drives a real browser through that exact path.

Preconditions (otherwise the test skips):
  - the FastAPI backend on :8000 and the Next.js frontend on :3000, with the
    frontend proxying /api/* to the backend
  - playwright installed (dev dependency) and a system Chrome/Edge browser
    (used via channel, so no browser binaries need downloading)

Marked ``e2e``: excluded from the default hermetic suite via
``addopts = -m "not e2e"`` in pytest.ini — run it explicitly with
``pytest -m e2e``.
"""
import httpx
import pytest

import e2e_helpers

FRONTEND = "http://localhost:3000"
BACKEND = "http://localhost:8000"

pytest.importorskip("playwright")

pytestmark = pytest.mark.e2e


@pytest.mark.skipif(
    not e2e_helpers.servers_up(FRONTEND, BACKEND),
    reason="E2E share-restore test needs the backend on :8000 and the frontend on :3000",
)
def test_share_link_restores_pipeline_in_browser(sample_pipeline):
    # 1. Create a live share link through the frontend proxy (LLM-free store).
    r = httpx.post(
        f"{FRONTEND}/api/pipeline/export",
        json={"task": sample_pipeline["task"], "robot": "unitree-g1",
              "pipeline": sample_pipeline},
        timeout=30,
    )
    assert r.status_code == 200, f"share link creation failed: http {r.status_code}"
    pid = r.json()["pipeline_id"]
    assert pid.startswith("p")

    # The share link is live: the store round-trips it before we even open it.
    r = httpx.get(f"{FRONTEND}/api/pipeline/{pid}", timeout=15)
    assert r.status_code == 200, "share link not resolvable before browser visit"

    subtask_names = [s["name"] for s in sample_pipeline["subtasks"]]

    with e2e_helpers.browser_page() as page:
        page.goto(f"{FRONTEND}/#p={pid}", wait_until="domcontentloaded", timeout=30000)

        # 2. The page must restore the pipeline client-side from the hash.
        # Wait until the first subtask's name is actually rendered.
        page.wait_for_function(
            "arg => document.body.innerText.includes(arg)",
            arg=subtask_names[0],
            timeout=30000,
        )

        # 3. Verify the rendered pipeline: task, every step, and the id.
        body_text = page.locator("body").inner_text()
        assert sample_pipeline["task"] in body_text, "task text not rendered"
        for name in subtask_names:
            assert name in body_text, f"step not rendered: {name}"
        assert pid in body_text, "pipeline id not rendered"

        # Every step's skill id should be listed too.
        for sub in sample_pipeline["subtasks"]:
            assert sub["skill_id"] in body_text, f"skill id missing: {sub['skill_id']}"
