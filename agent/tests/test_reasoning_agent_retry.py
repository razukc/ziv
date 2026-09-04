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
    model returned empty content, a ``str`` is returned as content, an
    ``Exception`` instance is raised by the transport, and a dict
    ``{"tool_calls": [...]}`` (OpenAI wire shape) makes the model request
    tools instead of answering.
    """
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            tcs = [SimpleNamespace(
                id=tc["id"],
                function=SimpleNamespace(name=tc["function"]["name"],
                                         arguments=tc["function"]["arguments"]))
                for tc in item.get("tool_calls", [])]
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=tcs))])
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


# --- registry tool use during decomposition ---------------------------------

def _tool_call(name, args, call_id="call_1"):
    return {"tool_calls": [{"id": call_id,
                            "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_registry_tools_executor_is_grounded_in_the_registries():
    """Tool results come from the registries the gate validates against."""
    import registry_tools
    s = registry_tools.execute_tool("get_skill", {"skill_id": "motion-generation"})
    assert s["estimated_cost_usd"] == 0.10 and s["requires"] == ["arm"]
    r = registry_tools.execute_tool("get_robot", {"robot_id": "unitree-go2"})
    assert r["anatomy"] == ["legs", "cameras"]
    ok = registry_tools.execute_tool("check_capability",
                                     {"skill_id": "motion-generation", "robot_id": "unitree-g1"})
    assert ok["compatible"] is True
    bad = registry_tools.execute_tool("check_capability",
                                      {"skill_id": "motion-generation", "robot_id": "unitree-go2"})
    assert bad["compatible"] is False and bad["missing"] == ["arm"]
    assert "error" in registry_tools.execute_tool("get_skill", {"skill_id": "nope"})
    assert "error" in registry_tools.execute_tool("no_such_tool", {})
    alls = registry_tools.execute_tool("list_skills", {})
    assert len(alls["skills"]) == len(SKILL_CATALOG)


def test_decompose_runs_tool_loop_and_feeds_results_back(monkeypatch):
    """The model can query the registries mid-decomposition: tool calls are
    executed and fed back as tool messages before the final answer."""
    agent, calls = _stub_agent([
        _tool_call("get_skill", {"skill_id": "motion-generation"}, "call_1"),
        _tool_call("check_capability",
                   {"skill_id": "motion-generation", "robot_id": "unitree-go2"}, "call_2"),
        json.dumps(_valid_pipeline()),
    ])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    reported = []
    pipeline = agent.decompose_task("Sort packages", "unitree-r1",
                                    on_tool=lambda n, a, r: reported.append(n))
    assert len(calls) == 3, "two tool rounds then the final answer"
    tool_msgs = [m for m in calls[-1]["messages"]
                 if isinstance(m, dict) and m.get("role") == "tool"]
    assert len(tool_msgs) == 2, "both tool results must be fed back"
    assert "motion-generation" in tool_msgs[0]["content"]
    assert tool_msgs[0]["tool_call_id"] == "call_1"
    assert '"missing": ["arm"]' in tool_msgs[1]["content"], \
        "capability check answers from the registry, not memory"
    assert reported == ["get_skill", "check_capability"], "every lookup is reported"
    assert len(pipeline["subtasks"]) == 2


def test_decompose_degrades_to_prompt_only_when_tools_rejected(monkeypatch):
    """Providers that reject tool definitions (400/404/422) fall back to the
    prompt-only path — the catalog stays in the prompt — instead of failing."""
    class _ToolsRejected(Exception):
        status_code = 400

    agent, calls = _stub_agent([_ToolsRejected(), json.dumps(_valid_pipeline())])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    pipeline = agent.decompose_task("Sort packages", "unitree-r1")
    assert len(calls) == 2
    assert "tools" in calls[0], "the first call asks for tools"
    assert "tools" not in calls[1], "the rejection degrades to prompt-only"
    assert len(pipeline["subtasks"]) == 2, "the compose still succeeds"


def test_decompose_tool_loop_is_bounded(monkeypatch):
    """A model stuck requesting tools never loops forever."""
    monkeypatch.setattr("reasoning_agent._MAX_ATTEMPTS", 1)
    agent, calls = _stub_agent([_tool_call("list_skills", {})] * 3)
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    with pytest.raises(ValueError, match="requested tools"):
        agent.decompose_task("Sort packages", "unitree-r1", max_tool_rounds=2)
    assert len(calls) == 3, "bounded at max_tool_rounds tool calls"


def test_decompose_default_tool_budget_covers_a_full_pipeline(monkeypatch):
    """A verification-heavy loop (one get_skill per candidate, ~9 rounds for a
    real 6-7 step plan) fits inside the default budget."""
    agent, calls = _stub_agent(
        [_tool_call("get_skill", {"skill_id": f"s{i}"}, f"c{i}") for i in range(9)]
        + [json.dumps(_valid_pipeline())])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    pipeline = agent.decompose_task("Sort packages", "unitree-r1")
    assert len(calls) == 10, "9 verification rounds then the final answer"
    assert len(pipeline["subtasks"]) == 2


def test_seeded_decompose_skips_tools_by_default(monkeypatch):
    """Seeded variations default to the fast prompt-only path (measured: the
    seed + variation rules already keep them gate-clean; tool rounds would
    only add ~3x latency). Fresh decomposes keep the tools."""
    agent, calls = _stub_agent([json.dumps(_valid_pipeline())])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    agent.decompose_task("Sort packages", "unitree-r1", seed_pipeline=_valid_pipeline())
    assert "tools" not in calls[0], "seeded variations must skip the tool schemas"
    agent2, calls2 = _stub_agent([json.dumps(_valid_pipeline())])
    agent2.decompose_task("Sort packages", "unitree-r1")
    assert "tools" in calls2[0], "fresh decomposes keep the registry tools"


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


def test_stream_surfaces_registry_tool_usage(client):
    """The reasoning stream shows the agent's registry lookups and the done
    event counts them (the fake agent makes two tool calls per decompose)."""
    r = client.post("/api/compose/stream",
                    json={"task": "Pick up the red block", "robot": "unitree-g1"})
    assert r.status_code == 200
    assert "queried get_skill(motion-generation)" in r.text
    assert "checked motion-generation against unitree-g1" in r.text
    done = _done_event(r.text)
    assert done["tool_calls"] == 2, "done must carry the registry-lookup count"


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
    assert r.json()["tool_calls"] == 2, "the fake agent grounds via two registry lookups"
    r2 = client.post("/api/compose/silent", json={"task": "Sort packages", "robot": "unitree-g1"})
    assert r2.status_code == 200
    assert r2.json()["retries"] == 0
    assert r2.json()["tool_calls"] == 2
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


def test_compose_silent_respects_tools_enabled_opt_out(client, fake_agent):
    """tools_enabled=False on the request reaches the agent and yields a
    response with no registry lookups; the default (auto) keeps them."""
    r = client.post("/api/compose/silent", json={
        "task": "Pick up the red block", "robot": "unitree-g1",
        "tools_enabled": False})
    assert r.status_code == 200
    assert r.json()["tool_calls"] == 0, "opt-out must skip registry lookups"
    assert fake_agent.last_tools_enabled is False, "the flag must reach the agent"
    # Default (auto) still grounds fresh composes through the fake's two calls.
    r2 = client.post("/api/compose/silent", json={
        "task": "Pick up the red block", "robot": "unitree-g1"})
    assert r2.status_code == 200
    assert r2.json()["tool_calls"] == 2
    assert fake_agent.last_tools_enabled is None


def test_stream_respects_tools_enabled_opt_out(client, fake_agent):
    """The SSE compose forwards the opt-out: no tool lines, done tool_calls=0."""
    r = client.post("/api/compose/stream", json={
        "task": "Pick up the red block", "robot": "unitree-g1",
        "tools_enabled": False})
    assert r.status_code == 200
    assert "queried get_skill" not in r.text, "opt-out must not surface tool lines"
    assert '"tool_calls": 0' in r.text


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


# --- rolling compose telemetry on /api/health --------------------------------

def test_health_exposes_rolling_compose_telemetry(client):
    """/api/health reports latency + retry aggregates from recent composes."""
    client.post("/api/compose/silent",
                json={"task": "Pick up the red block", "robot": "unitree-g1"})
    r = client.post("/api/compose/stream",
                    json={"task": "Pick up the red block", "robot": "unitree-g1"})
    assert r.status_code == 200
    stats = client.get("/api/health").json()["compose_stats"]
    # The ring is process-global, so other tests' composes may also be in it:
    # assert the aggregates are sane and THIS test's entries landed last.
    assert stats["samples"] >= 2
    assert stats["avg_seconds"] > 0, "the stream's log phase gives real wall time"
    assert stats["p95_seconds"] >= stats["avg_seconds"]
    last = stats["recent"][-1]
    assert last["endpoint"] == "stream" and last["retries"] == 0
    assert last["seconds"] > 0 and "at" in last


def test_health_telemetry_records_healed_retries(client, monkeypatch):
    """A stream compose that healed via retry shows up with retries=1."""
    import server
    agent, _ = _stub_agent([None, json.dumps(_valid_pipeline()), "a recovered explanation"])
    monkeypatch.setattr("reasoning_agent.time.sleep", lambda s: None)
    monkeypatch.setattr(server, "get_agent", lambda: agent)
    r = client.post("/api/compose/stream",
                    json={"task": "Sort packages by size", "robot": "unitree-r1"})
    assert r.status_code == 200
    stats = client.get("/api/health").json()["compose_stats"]
    last = stats["recent"][-1]
    assert last["endpoint"] == "stream" and last["retries"] == 1
    assert stats["retried_composes"] >= 1


def test_health_telemetry_ring_is_capped(client):
    """The in-process ring holds at most COMPOSE_TELEMETRY_MAX entries."""
    import server
    for _ in range(server._COMPOSE_TELEMETRY_MAX + 5):
        server._record_compose("silent", 5.0, 0)
    stats = client.get("/api/health").json()["compose_stats"]
    assert stats["samples"] == server._COMPOSE_TELEMETRY_MAX
    assert len(stats["recent"]) == min(10, server._COMPOSE_TELEMETRY_MAX)
    assert all(e["endpoint"] == "silent" and e["seconds"] == 5.0 for e in stats["recent"])
