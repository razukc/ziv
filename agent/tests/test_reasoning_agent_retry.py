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


def _done_event(text: str) -> dict:
    """Parse the done SSE event out of a stream body."""
    for line in text.splitlines():
        if line.startswith("data: ") and '"type": "done"' in line:
            return json.loads(line[6:])
    raise AssertionError("no done event in stream")


def test_stream_emits_notice_when_compose_had_to_retry(client, monkeypatch):
    """A compose that heals via retry surfaces a notice SSE event, and the
    done event reports the retry count and the wall time."""
    import server
    agent, _ = _stub_agent([None, json.dumps(_valid_pipeline()), "a recovered explanation"])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    monkeypatch.setattr(server, "get_agent", lambda: agent)
    r = client.post("/api/compose/stream",
                    json={"task": "Sort packages by size", "robot": "unitree-r1"})
    assert r.status_code == 200
    assert '"type": "notice"' in r.text, "stream must tell the UI about the healed retry"
    assert '"retries": 1' in r.text
    done = _done_event(r.text)
    assert done["retries"] == 1, "done must carry the retry count"
    assert isinstance(done["seconds"], (int, float)) and done["seconds"] > 0, \
        "done must report the compose wall time"
    assert _phases_ok(done["phases"]), "done must break the run into decompose/explain/logs"


def test_stream_has_no_notice_when_no_retry(client):
    """Clean composes carry no notice event (fake agent never retries); the
    done event still reports seconds with retries=0."""
    r = client.post("/api/compose/stream",
                    json={"task": "Pick up the red block", "robot": "unitree-g1"})
    assert r.status_code == 200
    assert '"type": "notice"' not in r.text
    done = _done_event(r.text)
    assert done["retries"] == 0, "a clean compose must report zero retries"
    assert isinstance(done["seconds"], (int, float)) and done["seconds"] > 0, \
        "done must report the compose wall time even without retries"
    assert _phases_ok(done["phases"]), "done must break the run into decompose/explain/logs"


def _phases_ok(phases: dict) -> bool:
    """The phases dict names the three round-trip groups with sane timings."""
    return (isinstance(phases, dict)
            and set(phases) == {"decompose", "explain", "logs"}
            and all(isinstance(v, (int, float)) and v >= 0 for v in phases.values())
            and phases["logs"] > 0)  # the simulated log stream always takes real time


# --- request/response endpoints expose the retry count -----------------------

def _use_agent(monkeypatch, responses):
    """Point server.get_agent at a stubbed ReasoningAgent; no-op the backoff."""
    import server
    from reasoning_agent import time as _ra_time
    monkeypatch.setattr(_ra_time, "sleep", lambda s: None)
    agent, calls = _stub_agent(responses)
    monkeypatch.setattr(server, "get_agent", lambda: agent)
    return calls


def test_request_response_endpoints_report_zero_retries_on_clean_calls(client):
    """Clean compose / compose-silent / improve responses all carry retries=0."""
    r = client.post("/api/compose", json={"task": "Pick up the red block", "robot": "unitree-g1"})
    assert r.status_code == 200
    assert r.json()["retries"] == 0, "clean compose must report zero retries"
    r2 = client.post("/api/compose/silent", json={"task": "Sort packages", "robot": "unitree-g1"})
    assert r2.status_code == 200
    assert r2.json()["retries"] == 0
    pid = r2.json()["pipeline_id"]
    r3 = client.post("/api/improve",
                     json={"task": "ignored", "robot": "unitree-g1", "pipeline_id": pid})
    assert r3.status_code == 200
    assert r3.json()["retries"] == 0, "clean improve must report zero retries"


def test_compose_response_counts_retries_across_round_trips(client, monkeypatch):
    """POST /api/compose reports retries from BOTH its LLM round-trips."""
    _use_agent(monkeypatch, [None, json.dumps(_valid_pipeline()), "an explanation"])
    r = client.post("/api/compose",
                    json={"task": "Sort packages by size", "robot": "unitree-r1"})
    assert r.status_code == 200
    data = r.json()
    assert data["retries"] == 1, "decompose retried once; the explanation was clean"
    assert data["explanation"] == "an explanation"


def test_compose_silent_response_counts_retries(client, monkeypatch):
    """POST /api/compose/silent reports how many times decompose retried."""
    _use_agent(monkeypatch, [None, None, json.dumps(_valid_pipeline())])
    r = client.post("/api/compose/silent",
                    json={"task": "Sort packages by size", "robot": "unitree-r1"})
    assert r.status_code == 200
    assert r.json()["retries"] == 2, "two empty responses healed via retries"


def test_improve_response_counts_retries(client, monkeypatch):
    """POST /api/improve reports healed retries on the suggestion round-trip."""
    # First store a pipeline cleanly (decompose succeeds on the first call),
    # then /improve resolves it by id — only the suggestion call retries.
    _use_agent(monkeypatch, [json.dumps(_valid_pipeline()), None, "Use cheaper skills."])
    r = client.post("/api/compose/silent",
                    json={"task": "Sort packages by size", "robot": "unitree-r1"})
    pid = r.json()["pipeline_id"]
    assert r.json()["retries"] == 0
    r2 = client.post("/api/improve",
                     json={"task": "ignored", "robot": "unitree-r1", "pipeline_id": pid})
    assert r2.status_code == 200
    data = r2.json()
    assert data["retries"] == 1, "suggestion round-trip healed one retry"
    assert data["improvements"] == "Use cheaper skills."
