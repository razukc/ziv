"""End-to-end: a live compose that beats the session's moving baseline warns.

The slow-compose hint mirrors the frequent-blip hint: live compose wall
times accumulate in sessionStorage (`sf-session-compose-times`) and a
compose that clears an absolute floor and is SLOW_COMPOSE_MULTIPLIER (2x)
over the session's recent median gets a warn note suggesting a retry or a
simpler task. A real slow LLM call can't be forced on demand, so the test
seeds a session baseline (two ~13s composes), then INTERCEPTS the compose
stream with a done event reporting 60s — no backend call, no credits —
and asserts the hint appears with the ratio, then clears on a normal
(~10s) compose.

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
    "notes": "slow-compose stub pipeline",
    "subtasks": [
        {"order": 1, "name": "scene-creation", "description": "Build 3D environment in Isaac Sim", "skill_id": "scene-creation", "estimated_cost_usd": 0.15, "gpu_required": True},
        {"order": 2, "name": "validation", "description": "Test across Isaac Sim scenarios", "skill_id": "policy-validation", "estimated_cost_usd": 0.30, "gpu_required": True},
        {"order": 3, "name": "deployment", "description": "Export ROS2 package", "skill_id": "policy-deployment", "estimated_cost_usd": 0.05, "gpu_required": False},
    ],
}


def _slow_stub(seconds_by_call):
    """Fetch stub serving canned compose streams; each done event reports the
    given wall time (one entry per compose call, last one repeats)."""
    pipe_json = json.dumps(PIPE)
    seconds_json = json.dumps(seconds_by_call)
    return f"""
    (() => {{
      const pipe = {pipe_json};
      const secondsByCall = {seconds_json};
      const origFetch = window.fetch.bind(window);
      let calls = 0;
      window.fetch = (url, opts) => {{
        if (opts && opts.method === "POST" && String(url).includes("/api/compose/stream")) {{
          calls++;
          const seconds = secondsByCall[Math.min(calls, secondsByCall.length) - 1];
          const ev = o => `data: ${{JSON.stringify(o)}}\\n\\n`;
          const body =
            ev({{type:"thinking", content:"parsing task", step:1, total:2}}) +
            ev({{type:"pipeline", content: pipe, pipeline_id: "pslow-" + calls}}) +
            ev({{type:"done", pipeline_id: "pslow-" + calls, seconds, retries: 0,
                phases: {{decompose: seconds - 10, explain: 5, logs: 5}}}});
          return Promise.resolve(new Response(body, {{ status: 200, headers: {{ "Content-Type": "text/event-stream" }} }}));
        }}
        return origFetch(url, opts);
      }};
      return "slow stub installed";
    }})()
    """


def test_slow_compose_warns_against_moving_baseline():
    with e2e_helpers.browser_page() as page:
        page.goto(FRONTEND, wait_until="domcontentloaded", timeout=30000)
        e2e_helpers.wait_hydrated(page)

        # Seed a session baseline of two ~13s composes, then reload in the
        # same tab (sessionStorage survives — that is the persistence the app
        # promises) so the moving threshold is established before composing.
        page.evaluate("sessionStorage.setItem('sf-session-compose-times', '[12,14]')")
        page.reload(wait_until="domcontentloaded")
        e2e_helpers.wait_hydrated(page)
        page.evaluate(_slow_stub([60, 10]))

        # Compose #1 reports 60s — 4.6x over the 13s baseline -> warn hint.
        page.get_by_role("button", name="live", exact=True).click()
        page.locator("textarea").fill("Pick up the red block and place it on the blue platform")
        page.get_by_role("button", name="compose", exact=True).click()
        page.locator('[data-testid="compose-timing"]').wait_for(timeout=10000)
        slow = page.locator('[data-testid="slow-note"]')
        slow.wait_for(timeout=10000)
        slow_text = slow.inner_text()
        print(f"slow note: {slow_text.strip()}")
        assert "compose took 60s" in slow_text, slow_text
        assert "4.6× slower than your recent typical (13s)" in slow_text, slow_text
        assert "retry, or simplify the task" in slow_text, slow_text

        # Compose #2 reports 10s — under the floor and under 2x the baseline
        # (which now includes the 60s run): the warn note clears.
        page.get_by_role("button", name=">>> compose another").click()
        page.locator("textarea").fill("Wipe the kitchen counter clean")
        page.get_by_role("button", name="compose", exact=True).click()
        timing2 = page.locator('[data-testid="compose-timing"]')
        timing2.wait_for(timeout=10000)
        text2 = timing2.inner_text()
        assert "compose took 10s" in text2, text2
        assert slow.count() == 0, "a normal compose must clear the slow note"

        # The session history now carries both new runs for the next baseline.
        stored = page.evaluate("sessionStorage.getItem('sf-session-compose-times')")
        assert stored and json.loads(stored) == [12, 14, 60, 10], stored

        # Clean up the fake history entries this run created.
        page.evaluate("""(() => {
          const key = "sf-history-v1";
          try {
            const list = JSON.parse(localStorage.getItem(key) || "[]");
            localStorage.setItem(key, JSON.stringify(list.filter(e => !String(e.pipelineId || "").startsWith("pslow"))));
          } catch (e) {}
          return "history cleaned";
        })()""")
