"""End-to-end: the compose retry note renders for retries=1 and retries=3.

Live composes report their wall time and retry count on the stream's ``done``
event, and the results view folds the retry disclosure into the timing line:
"compose took Xs (auto-retried Nx, healed on its own)". A real model blip
can't be forced on demand, so this test INTERCEPTS the ``/api/compose/stream``
request with a canned SSE body — first carrying ``retries: 1``, then
``retries: 3`` — and drives two live composes through the real UI. No
backend call and no credits are involved.

Marked ``e2e``: excluded from the default hermetic suite via
``addopts = -m \"not e2e\"`` — run it explicitly with ``pytest -m e2e``.
"""
import json

import pytest

import e2e_helpers

FRONTEND = "http://localhost:3000"

pytest.importorskip("playwright")

pytestmark = pytest.mark.e2e

PIPE = {
    "task": "Pick up the red block and place it on the blue platform",
    "robot": "unitree-g1",
    "task_type": "manipulation",
    "total_estimated_cost_usd": 3.10,
    "estimated_time_minutes": 12,
    "risk_assessment": "low",
    "notes": "retry-note stub pipeline",
    "subtasks": [
        {"order": 1, "name": "scene-creation", "description": "Build 3D environment in Isaac Sim", "skill_id": "scene-creation", "estimated_cost_usd": 0.15, "gpu_required": True},
        {"order": 2, "name": "synthetic-data", "description": "Generate pick-place demos", "skill_id": "synthetic-data-generation", "estimated_cost_usd": 0.50, "gpu_required": True},
        {"order": 3, "name": "validation", "description": "Test across Isaac Sim scenarios", "skill_id": "policy-validation", "estimated_cost_usd": 0.30, "gpu_required": True},
        {"order": 4, "name": "deployment", "description": "Export ROS2 package", "skill_id": "policy-deployment", "estimated_cost_usd": 0.05, "gpu_required": False},
    ],
}


def _retry_stub(retries_by_call):
    """Fetch stub serving canned compose streams with the given retries
    (one entry per compose call; the last entry repeats for later calls)."""
    pipe_json = json.dumps(PIPE)
    retries_json = json.dumps(retries_by_call)
    return f"""
    (() => {{
      const pipe = {pipe_json};
      const retriesByCall = {retries_json};
      const origFetch = window.fetch.bind(window);
      let calls = 0;
      window.fetch = (url, opts) => {{
        if (opts && opts.method === "POST" && String(url).includes("/api/compose/stream")) {{
          calls++;
          const retries = retriesByCall[Math.min(calls, retriesByCall.length) - 1];
          const ev = o => `data: ${{JSON.stringify(o)}}\\n\\n`;
          const body =
            ev({{type:"thinking", content:"parsing task", step:1, total:2}}) +
            ev({{type:"pipeline", content: pipe, pipeline_id: "pretry-" + calls}}) +
            ev({{type:"notice", retries, content: "auto-retried after a model blip"}}) +
            ev({{type:"done", pipeline_id: "pretry-" + calls, seconds: 11.4, retries}});
          return Promise.resolve(new Response(body, {{ status: 200, headers: {{ "Content-Type": "text/event-stream" }} }}));
        }}
        return origFetch(url, opts);
      }};
      return "retry stub installed";
    }})()
    """


def test_retry_note_renders_for_1_and_3_retries():
    with e2e_helpers.browser_page() as page:
        page.goto(FRONTEND, wait_until="domcontentloaded", timeout=30000)
        e2e_helpers.wait_hydrated(page)
        page.evaluate(_retry_stub([1, 3]))

        # --- Compose #1: the done event reports retries=1 ------------------
        page.get_by_role("button", name="live", exact=True).click()
        page.locator("textarea").fill("Pick up the red block and place it on the blue platform")
        page.get_by_role("button", name="compose", exact=True).click()

        timing = page.locator('[data-testid="compose-timing"]')
        timing.wait_for(timeout=10000)
        text = timing.inner_text()
        print(f"compose#1 timing line: {text.strip()}")
        assert "compose took 11s" in text, text
        assert "auto-retried 1×" in text, f"retries=1 must read 'auto-retried 1×': {text}"
        assert "healed on its own" in text, text

        # --- Compose #2: the done event reports retries=3 ------------------
        page.get_by_role("button", name=">>> compose another").click()
        page.locator("textarea").fill("Wipe the kitchen counter clean")
        page.get_by_role("button", name="compose", exact=True).click()

        timing3 = page.locator('[data-testid="compose-timing"]')
        timing3.wait_for(timeout=10000)
        text3 = timing3.inner_text()
        print(f"compose#2 timing line: {text3.strip()}")
        assert "auto-retried 3×" in text3, f"retries=3 must read 'auto-retried 3×': {text3}"
        assert "healed on its own" in text3, text3
