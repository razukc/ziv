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


def test_on_retry_reports_each_failed_attempt(monkeypatch):
    """Every healed failure is reported with its 1-based attempt number."""
    agent, _ = _stub_agent([None, None, json.dumps(_valid_pipeline())])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    reported = []
    agent.decompose_task("Sort packages", "unitree-r1",
                         on_retry=lambda attempt, err: reported.append((attempt, type(err).__name__)))
    assert [a for a, _ in reported] == [1, 2], "two healed failures must both be reported"
    assert all(err == "ValueError" for _, err in reported)


def test_on_retry_not_called_when_first_attempt_succeeds(monkeypatch):
    agent, _ = _stub_agent([json.dumps(_valid_pipeline())])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    reported = []
    agent.decompose_task("Sort packages", "unitree-r1",
                         on_retry=lambda attempt, err: reported.append(attempt))
    assert reported == [], "clean round-trip must not report retries"


def test_on_retry_not_called_when_all_attempts_fail(monkeypatch):
    """A hard failure raises after the final attempt without a healing notice."""
    agent, _ = _stub_agent([None, None, None])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    reported = []
    with pytest.raises(ValueError):
        agent.decompose_task("Sort packages", "unitree-r1",
                             on_retry=lambda attempt, err: reported.append(attempt))
    assert reported == [1, 2], "only healed attempts are retried; the last failure raises"


def test_stream_emits_notice_when_compose_had_to_retry(client, monkeypatch):
    """A compose that heals via retry surfaces a notice SSE event."""
    import server
    agent, _ = _stub_agent([None, json.dumps(_valid_pipeline()), "a recovered explanation"])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    monkeypatch.setattr(server, "get_agent", lambda: agent)
    r = client.post("/api/compose/stream",
                    json={"task": "Sort packages by size", "robot": "unitree-r1"})
    assert r.status_code == 200
    assert '"type": "notice"' in r.text, "stream must tell the UI about the healed retry"
    assert '"retries": 1' in r.text
    assert '"type": "done"' in r.text, "the retried compose still completes"


def test_stream_has_no_notice_when_no_retry(client):
    """Clean composes carry no notice event (fake agent never retries)."""
    r = client.post("/api/compose/stream",
                    json={"task": "Pick up the red block", "robot": "unitree-g1"})
    assert r.status_code == 200
    assert '"type": "notice"' not in r.text