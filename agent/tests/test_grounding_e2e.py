"""End-to-end: the registry-grounding toggle and its measured disclosure.

A live compose's done event reports how many registry tool calls grounded it
(the decompose agent may verify skills via list_skills/get_skill/get_robot/
check_capability). The compose-timing strip surfaces the outcome:

- tool_calls > 0  -> "🔧 verified via N registry lookups"
- tool_calls == 0 -> "prompt-based — no registry lookups"

The compose box (live mode) also carries a grounding toggle: OFF means the UI
sends ``tools_enabled: false`` on the wire, forcing prompt-only composes for
speed. This test proves both: compose #1 (grounded default) renders the
verified line and sends NO tools_enabled field; toggling OFF and composing
again renders the prompt-based line AND the request body carries
``tools_enabled: false``.

The stream is intercepted at the page level (fetch stub) — no backend, no
credits. Marked ``e2e``: run with ``pytest -m e2e``.
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
    "notes": "grounding stub pipeline",
    "subtasks": [
        {"order": 1, "name": "scene-creation", "description": "Build 3D environment in Isaac Sim", "skill_id": "scene-creation", "estimated_cost_usd": 0.15, "gpu_required": True},
        {"order": 2, "name": "synthetic-data", "description": "Generate pick-place demos", "skill_id": "synthetic-data-generation", "estimated_cost_usd": 0.50, "gpu_required": True},
        {"order": 3, "name": "validation", "description": "Test across Isaac Sim scenarios", "skill_id": "policy-validation", "estimated_cost_usd": 0.30, "gpu_required": True},
        {"order": 4, "name": "deployment", "description": "Export ROS2 package", "skill_id": "policy-deployment", "estimated_cost_usd": 0.05, "gpu_required": False},
    ],
}


def _grounding_stub(tool_calls_by_call):
    """Fetch stub serving canned compose streams with the given tool_calls
    counts (one per compose call; the last repeats). Request bodies are
    pushed to window.__composeBodies so the test can inspect the wire."""
    pipe_json = json.dumps(PIPE)
    counts_json = json.dumps(tool_calls_by_call)
    return f"""
    (() => {{
      const pipe = {pipe_json};
      const counts = {counts_json};
      const origFetch = window.fetch.bind(window);
      const bodies = [];
      window.__composeBodies = bodies;
      let calls = 0;
      window.fetch = (url, opts) => {{
        if (opts && opts.method === "POST" && String(url).includes("/api/compose/stream")) {{
          calls++;
          bodies.push(JSON.parse(opts.body || "{{}}"));
          const tool_calls = counts[Math.min(calls, counts.length) - 1];
          const ev = o => `data: ${{JSON.stringify(o)}}\\n\\n`;
          const body =
            ev({{type:"thinking", content:"parsing task", step:1, total:2}}) +
            ev({{type:"pipeline", content: pipe, pipeline_id: "pgr-" + calls}}) +
            ev({{type:"done", pipeline_id: "pgr-" + calls, seconds: 9.7, retries: 0,
                phases: {{decompose: 4.2, explain: 2.4, logs: 3.1}}, tool_calls}});
          return Promise.resolve(new Response(body, {{ status: 200, headers: {{ "Content-Type": "text/event-stream" }} }}));
        }}
        return origFetch(url, opts);
      }};
      return "grounding stub installed";
    }})()
    """


def test_grounding_disclosure_and_opt_out_toggle():
    with e2e_helpers.browser_page() as page:
        page.goto(FRONTEND, wait_until="domcontentloaded", timeout=30000)
        e2e_helpers.wait_hydrated(page)
        page.evaluate(_grounding_stub([4, 0]))

        # --- Compose #1: grounded default, done reports 4 tool calls --------
        page.get_by_role("button", name="live", exact=True).click()
        toggle = page.get_by_test_id("grounding-toggle")
        toggle.wait_for(timeout=5000)
        assert toggle.get_attribute("aria-pressed") == "true", "grounding defaults ON"
        page.locator("textarea").fill("Pick up the red block and place it on the blue platform")
        page.get_by_role("button", name="compose", exact=True).click()

        timing = page.locator('[data-testid="compose-timing"]')
        timing.wait_for(timeout=10000)
        grounding = page.get_by_test_id("compose-grounding")
        grounding.wait_for(timeout=5000)
        line1 = grounding.inner_text().strip()
        print(f"grounding line #1: {line1}")
        assert "verified via 4 registry lookups" in line1, line1

        # --- Compose #2: toggle grounding OFF, done reports 0 tool calls ----
        page.get_by_role("button", name=">>> compose another").click()
        toggle.wait_for(timeout=5000)
        toggle.click()
        assert toggle.get_attribute("aria-pressed") == "false", "toggle must flip OFF"
        page.locator("textarea").fill("Wipe the kitchen counter clean")
        page.get_by_role("button", name="compose", exact=True).click()

        timing.wait_for(timeout=10000)
        line2 = page.get_by_test_id("compose-grounding").inner_text().strip()
        print(f"grounding line #2: {line2}")
        assert "prompt-based — no registry lookups" in line2, line2

        # --- The wire matches the toggle: auto sends no field, OFF sends it -
        bodies = page.evaluate("window.__composeBodies")
        print(f"request bodies: {json.dumps(bodies)}")
        assert len(bodies) == 2, "two compose requests must be intercepted"
        assert "tools_enabled" not in bodies[0], \
            f"grounded default must send auto (no tools_enabled field): {bodies[0]}"
        assert bodies[1].get("tools_enabled") is False, \
            f"opt-out must send tools_enabled: false: {bodies[1]}"
