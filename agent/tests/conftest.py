import pytest
from fastapi.testclient import TestClient

import pipeline_store
import server


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Point the pipeline store at a temp file and start empty for every test.

    The suite is hermetic: even when real Upstash credentials exist in .env,
    tests force a fresh local (memory) store so they never hit the network
    or write to the shared Redis. Tests that exercise the Redis backend pass
    their own fake client explicitly.
    """
    # The store file path is resolved from the pipeline_store module at
    # construction time; redirect it so bare PipelineStore() instances in
    # tests stay in the temp dir too.
    monkeypatch.setattr(pipeline_store, "PIPELINE_STORE_FILE", str(tmp_path / "pipeline_store.json"))
    # Health ping results are cached module-wide; reset so tests don't leak.
    monkeypatch.setattr(server, "_redis_health_cache", {"mono": None, "ok": None, "at_iso": None})
    # Per-client rate-limit state is process-wide; reset so tests don't leak.
    monkeypatch.setattr(server, "_share_link_limiter", {})
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    local_store = server.PipelineStore()
    monkeypatch.setattr(server, "PIPELINE_STORE", local_store)
    yield
    server.PIPELINE_STORE.clear()


@pytest.fixture()
def client():
    with TestClient(server.app) as c:
        yield c


@pytest.fixture()
def sample_pipeline():
    return {
        "task": "Pick up the red block",
        "robot": "unitree-g1",
        "task_type": "manipulation",
        "subtasks": [
            {"order": 1, "name": "scene-creation", "description": "Build 3D environment in Isaac Sim", "skill_id": "scene-creation", "estimated_cost_usd": 0.15, "gpu_required": True},
            {"order": 2, "name": "gr00t-n1-finetune", "description": "Fine-tune GR00T N1 on task data", "skill_id": "policy-training-gr00t", "estimated_cost_usd": 2.00, "gpu_required": True},
            {"order": 3, "name": "deployment", "description": "Export ROS2 package", "skill_id": "policy-deployment", "estimated_cost_usd": 0.05, "gpu_required": False},
        ],
        "total_estimated_cost_usd": 2.20,
        "estimated_time_minutes": 9,
        "risk_assessment": "low",
        "notes": "test",
    }


class FakeAgent:
    """Stands in for ReasoningAgent — no LLM calls, no API key needed.

    ``calls`` records every LLM-facing method that was invoked, so tests can
    assert an endpoint truly ran without touching the model.
    """

    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.calls = []
        self.last_seed = None

    def decompose_task(self, task, robot, seed_pipeline=None, on_retry=None, on_tool=None,
                       tools_enabled=None):
        self.calls.append("decompose_task")
        self.last_seed = seed_pipeline
        self.last_tools_enabled = tools_enabled
        # Exercise the tool-notification wiring: the real agent reports every
        # registry lookup, so the fake fires two representative calls too —
        # unless the request explicitly opted out (tools_enabled=False).
        if on_tool is not None and tools_enabled is not False:
            on_tool("get_skill", {"skill_id": "motion-generation"},
                    {"id": "motion-generation", "estimated_cost_usd": 0.10})
            on_tool("check_capability", {"skill_id": "motion-generation", "robot_id": robot},
                    {"compatible": True, "missing": []})
        p = dict(self.pipeline)
        p["task"] = task
        p["robot"] = robot
        return p

    def explain_pipeline(self, pipeline, on_retry=None):
        self.calls.append("explain_pipeline")
        return "This is a test explanation."

    def suggest_improvements(self, pipeline, on_retry=None):
        self.calls.append("suggest_improvements")
        return ["Use a cheaper validation skill."]


@pytest.fixture(autouse=True)
def fake_agent(sample_pipeline, monkeypatch):
    """Replace get_agent() everywhere so no test can hit the real Nebius API."""
    agent = FakeAgent(sample_pipeline)
    monkeypatch.setattr(server, "get_agent", lambda: agent)
    return agent