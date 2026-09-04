"""Unit tests for ReasoningAgent's LLM round-trip resilience.

The live model occasionally returns an empty payload or truncated JSON;
``decompose_task`` (and the other LLM methods) retry the stateless prompt a
bounded number of times instead of failing the compose on the first blip.
These tests stub the OpenAI client — no API key or network needed.
"""
import json
from types import SimpleNamespace

import pytest

from reasoning_agent import ReasoningAgent, _MAX_ATTEMPTS
from skill_registry import SKILL_CATALOG


def _stub_agent(responses):
    """ReasoningAgent with a fake chat client.

    ``responses`` is a queue consumed per ``create`` call: ``None`` means the
    model returned empty content, a ``str`` is returned as content, and an
    ``Exception`` instance is raised by the transport.
    """
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        content = item  # None -> empty response; str -> content
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    agent = ReasoningAgent.__new__(ReasoningAgent)
    agent.model = "fake-model"
    agent.client = client
    agent.skills_text = "fake skills"
    return agent, calls


def _valid_pipeline():
    ids = list(SKILL_CATALOG)[:2]
    return {
        "task": "Sort packages by size", "robot": "unitree-r1", "task_type": "manipulation",
        "subtasks": [
            {"order": 1, "name": "n1", "description": "d1", "skill_id": ids[0],
             "parameters": {}, "estimated_cost_usd": 0.1, "gpu_required": False},
            {"order": 2, "name": "n2", "description": "d2", "skill_id": ids[1],
             "parameters": {}, "estimated_cost_usd": 0.2, "gpu_required": True},
        ],
    }


def test_decompose_retries_after_empty_responses(monkeypatch):
    agent, calls = _stub_agent([None, None, json.dumps(_valid_pipeline())])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    pipeline = agent.decompose_task("Sort packages", "unitree-r1")
    ids = list(SKILL_CATALOG)[:2]
    assert len(calls) == 3, "should have retried both empty responses"
    assert [s["skill_id"] for s in pipeline["subtasks"]] == ids
    expected = round(sum(SKILL_CATALOG[i]["estimated_cost_usd"] for i in ids), 2)
    assert pipeline["total_estimated_cost_usd"] == expected, "costs are recalculated from the registry"


def test_decompose_retries_after_truncated_json(monkeypatch):
    agent, calls = _stub_agent(["{\"subtasks\": [", "not json at all", json.dumps(_valid_pipeline())])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    pipeline = agent.decompose_task("Sort packages", "unitree-r1")
    assert len(calls) == 3
    assert len(pipeline["subtasks"]) == 2


def test_decompose_retries_fenced_json(monkeypatch):
    agent, calls = _stub_agent(["```json\n" + json.dumps(_valid_pipeline()) + "\n```"])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    pipeline = agent.decompose_task("Sort packages", "unitree-r1")
    assert len(calls) == 1
    assert len(pipeline["subtasks"]) == 2, "markdown code fences are stripped"


def test_decompose_gives_up_after_max_attempts(monkeypatch):
    agent, calls = _stub_agent(["bad", "bad", "bad"])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    with pytest.raises(json.JSONDecodeError):
        agent.decompose_task("Sort packages", "unitree-r1")
    assert len(calls) == _MAX_ATTEMPTS


def test_seeded_decompose_retries_and_keeps_seed_in_prompt(monkeypatch):
    seed = _valid_pipeline()
    agent, calls = _stub_agent([None, json.dumps(_valid_pipeline())])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    agent.decompose_task("Sort packages", "unitree-r1", seed_pipeline=seed)
    assert len(calls) == 2, "retried call must re-send the same prompt"
    body = calls[-1]["messages"][1]["content"]
    assert json.dumps(seed, indent=2) in body, "seed pipeline must survive the retry"


def test_explain_retries_on_empty_content(monkeypatch):
    agent, calls = _stub_agent([None, "a real explanation"])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    assert agent.explain_pipeline({"subtasks": []}) == "a real explanation"
    assert len(calls) == 2