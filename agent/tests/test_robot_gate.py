"""Hermetic tests for the per-robot capability gate.

Catalog skills declare the anatomy they require (arm / legs / cameras);
robots declare the anatomy they have (robot_registry). Every composed
pipeline — fresh or a seeded variation — is checked against the requested
robot before it is stored, so an armless robot can't end up with arm
skills just because the model said so.
"""

import json

import robot_registry
from skill_registry import SKILL_CATALOG
from robot_registry import known_robots, validate_pipeline_robot

ANATOMY_TOKENS = {"arm", "legs", "cameras"}


def _plan(skills):
    return {
        "task": "some task",
        "robot": "unitree-g1",
        "subtasks": [
            {"order": i + 1, "name": f"step-{i + 1}", "description": "d",
             "skill_id": sid, "estimated_cost_usd": 0.1, "gpu_required": False}
            for i, sid in enumerate(skills)
        ],
    }


# ---------------------------------------------------------------------------
# Registry consistency
# ---------------------------------------------------------------------------

def test_every_skill_declares_known_anatomy():
    for sid, skill in SKILL_CATALOG.items():
        unknown = set(skill["requires"]) - ANATOMY_TOKENS
        assert not unknown, f"{sid} requires unknown anatomy: {unknown}"


def test_every_robot_declares_known_nonempty_anatomy():
    for slug, profile in robot_registry.ROBOT_REGISTRY.items():
        assert set(profile["anatomy"]) <= ANATOMY_TOKENS, slug
        assert profile["anatomy"], f"{slug} has no anatomy"


def test_mock_pipelines_are_compatible_with_their_robots():
    """The frontend demo plans must satisfy the same gate live composes do."""
    compatible = {
        "unitree-g1": ["scene-creation", "synthetic-data-generation",
                       "policy-training-gr00t", "motion-generation",
                       "policy-validation", "policy-deployment"],
        "unitree-r1": ["scene-creation", "synthetic-data-generation",
                       "policy-training-loco", "policy-validation",
                       "policy-deployment"],
        "1x-neo": ["scene-creation", "perception-training", "policy-training-loco",
                   "world-model-generation", "policy-validation", "policy-deployment"],
    }
    for robot, skills in compatible.items():
        assert validate_pipeline_robot(_plan(skills), robot) is None, robot


# ---------------------------------------------------------------------------
# Compatibility logic
# ---------------------------------------------------------------------------

def test_arm_skills_rejected_for_armless_robot():
    msg = validate_pipeline_robot(
        _plan(["policy-training-gr00t", "motion-generation"]), "unitree-r1")
    assert msg is not None
    assert "no arm" in msg
    assert "policy-training-gr00t" in msg and "motion-generation" in msg


def test_arm_skills_allowed_for_humanoid():
    assert validate_pipeline_robot(_plan(["policy-training-gr00t"]), "unitree-g1") is None
    assert validate_pipeline_robot(_plan(["motion-generation"]), "1x-neo") is None


def test_locotion_and_perception_for_quadruped():
    assert validate_pipeline_robot(
        _plan(["policy-training-loco", "perception-training"]), "unitree-go2") is None


def test_perception_needs_cameras():
    # R1 and Go2 have cameras, so perception passes for them...
    assert "cameras" in SKILL_CATALOG["perception-training"]["requires"]
    assert validate_pipeline_robot(_plan(["perception-training"]), "unitree-r1") is None
    # ...but a camera-less robot must be rejected with a clear reason.
    original = dict(robot_registry.ROBOT_REGISTRY["unitree-r1"])
    robot_registry.ROBOT_REGISTRY["unitree-r1"] = {**original, "anatomy": ("legs",)}
    try:
        msg = validate_pipeline_robot(_plan(["perception-training"]), "unitree-r1")
        assert msg is not None and "no cameras" in msg
    finally:
        robot_registry.ROBOT_REGISTRY["unitree-r1"] = original


def test_unknown_robot_rejected_with_registry_list():
    msg = validate_pipeline_robot(_plan(["scene-creation"]), "atlas-x")
    assert msg is not None
    for slug in known_robots():
        assert slug in msg


# ---------------------------------------------------------------------------
# API-level gating
# ---------------------------------------------------------------------------

def test_compose_rejects_arm_skills_for_armless_robot(client, fake_agent, sample_pipeline):
    """A seeded variation for a robot without an arm must be rejected clearly —
    the model isn't trusted to drop the seed's arm skills on its own."""
    r = client.post("/api/compose", json={
        "task": "Pick up the red block", "robot": "unitree-go2",
        "seed_pipeline": sample_pipeline,
    })
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "Unitree Go2" in detail and "no arm" in detail
    assert "policy-training-gr00t" in detail
    # The offending plan must not have been stored.
    entries = client.get("/api/health").json()["pipeline_store"]["entries"]
    assert entries == 0


def test_compose_silent_rejects_unregistered_robot(client, fake_agent):
    r = client.post("/api/compose/silent", json={"task": "Walk around", "robot": "atlas-x"})
    assert r.status_code == 422
    assert "not in the robot registry" in r.json()["detail"]


def test_compose_allows_humanoid_for_arm_skills(client, fake_agent, sample_pipeline):
    r = client.post("/api/compose", json={
        "task": "Pick up the red block", "robot": "1x-neo",
        "seed_pipeline": sample_pipeline,
    })
    assert r.status_code == 200, r.text
    assert r.json()["pipeline_id"].startswith("p")


def test_stream_rejects_incompatible_plan_with_error_event(client, fake_agent, sample_pipeline):
    r = client.post("/api/compose/stream", json={
        "task": "Pick up the red block", "robot": "unitree-go2",
        "seed_pipeline": sample_pipeline,
    })
    assert r.status_code == 200  # SSE channel opens; the error travels as an event
    events = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    types = [e.get("type") for e in events]
    assert types == ["thinking", "thinking", "thinking", "thinking", "error"], types
    assert "no arm" in events[-1]["content"]
    # No pipeline event, no done event — nothing was stored.
    assert "pipeline" not in types
