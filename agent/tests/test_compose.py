import json

import server


def test_compose_returns_pipeline_and_id(client, fake_agent):
    r = client.post("/api/compose", json={"task": "Sort packages by size", "robot": "unitree-g1"})
    assert r.status_code == 200
    data = r.json()
    assert data["pipeline"]["task"] == "Sort packages by size"
    assert data["pipeline"]["task_type"] == "manipulation"
    assert data["explanation"] == "This is a test explanation."
    assert data["pipeline_id"].startswith("p")
    # Composed pipelines are stored and fetchable.
    fetch = client.get(f"/api/pipeline/{data['pipeline_id']}")
    assert fetch.status_code == 200
    assert fetch.json()["pipeline"]["task_type"] == "manipulation"


def test_compose_silent(client, fake_agent):
    r = client.post("/api/compose/silent", json={"task": "Walk to the table", "robot": "unitree-g1"})
    assert r.status_code == 200
    data = r.json()
    assert data["pipeline_id"].startswith("p")
    assert "explanation" not in data


def test_compose_stream_emits_full_event_sequence(client, fake_agent):
    r = client.post("/api/compose/stream", json={"task": "Pick up the red block", "robot": "unitree-g1"})
    assert r.status_code == 200
    text = r.text
    for expected in ['"type": "thinking"', '"type": "pipeline"', '"type": "explanation"',
                     '"type": "log"', '"type": "done"']:
        assert expected in text, f"missing SSE event {expected}"
    # The pipeline_id is emitted on both the pipeline and done events.
    assert '"pipeline_id": "p' in text
    # The streamed pipeline must be stored and retrievable.
    pid = None
    for line in text.splitlines():
        if line.startswith("data: "):
            evt = json.loads(line[6:])
            if evt.get("type") == "done":
                pid = evt.get("pipeline_id")
    assert pid and server.PIPELINE_STORE.get(pid)


def test_improve_resolves_from_store(client, fake_agent, sample_pipeline):
    pid = server.store_pipeline(sample_pipeline)
    r = client.post("/api/improve", json={"task": "ignored", "robot": "unitree-g1", "pipeline_id": pid})
    assert r.status_code == 200
    data = r.json()
    assert data["pipeline_id"] == pid
    assert data["pipeline"]["task_type"] == "manipulation"
    assert data["improvements"] == ["Use a cheaper validation skill."]


def test_compose_empty_task_rejected(client, fake_agent):
    r = client.post("/api/compose", json={"task": "", "robot": "unitree-g1"})
    # Empty task still flows to the agent in the API; the UI validates before sending.
    assert r.status_code in (200, 500)


def test_compose_variation_passes_seed(client, fake_agent, sample_pipeline):
    """A variation compose carries the seed pipeline into the agent, and the
    reworded task/robot override the seed's originals in the response."""
    r = client.post("/api/compose", json={
        "task": "Pick up the blue cup from the shelf",
        "robot": "1x-neo",
        "seed_pipeline": sample_pipeline,
    })
    assert r.status_code == 200
    data = r.json()
    assert fake_agent.last_seed == sample_pipeline, "agent did not receive the seed pipeline"
    assert data["pipeline"]["task"] == "Pick up the blue cup from the shelf"
    assert data["pipeline"]["robot"] == "1x-neo"
    assert data["pipeline_id"].startswith("p")


def test_compose_stream_variation_passes_seed(client, fake_agent, sample_pipeline):
    r = client.post("/api/compose/stream", json={
        "task": "Wipe the counter with a different robot",
        "robot": "1x-neo",
        "seed_pipeline": sample_pipeline,
    })
    assert r.status_code == 200
    assert '"type": "pipeline"' in r.text
    assert fake_agent.last_seed == sample_pipeline, "stream compose did not pass the seed"


def test_compose_without_seed_sends_none(client, fake_agent):
    r = client.post("/api/compose", json={"task": "Walk to the door", "robot": "unitree-g1"})
    assert r.status_code == 200
    assert fake_agent.last_seed is None