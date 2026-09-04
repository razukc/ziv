import server


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "pipeline_store" in r.json()


def test_health_reports_memory_backend(client, monkeypatch, sample_pipeline):
    """Without Redis credentials the health endpoint reports the local fallback."""
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    store = server.PipelineStore()
    assert not store.is_remote
    store.store(sample_pipeline)
    monkeypatch.setattr(server, "PIPELINE_STORE", store)

    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["pipeline_store"]["backend"] == "memory"
    assert body["pipeline_store"]["entries"] == 1
    assert body["pipeline_store"]["redis_connected"] is None
    assert body["pipeline_store"]["redis_checked_at"] is None


def test_ready_ok_in_memory_mode(client, monkeypatch):
    """Memory fallback is a supported mode: the readiness probe stays 200."""
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    store = server.PipelineStore()
    monkeypatch.setattr(server, "PIPELINE_STORE", store)

    r = client.get("/api/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"
    assert r.json()["pipeline_store"]["backend"] == "memory"


def test_skills_list(client):
    r = client.get("/api/skills")
    assert r.status_code == 200
    skills = r.json()
    assert len(skills) == 11
    assert skills[0]["id"] == "scene-creation"
    assert all("estimated_cost_usd" in s for s in skills)
    ids = {s["id"] for s in skills}
    # Quadruped-class coverage: body manipulation + terrain robustness.
    assert {"legged-manipulation", "terrain-adaptation"} <= ids


def test_skill_by_id(client):
    r = client.get("/api/skills/policy-training-gr00t")
    assert r.status_code == 200
    assert r.json()["product"] == "NVIDIA GR00T N1"


def test_skill_not_found(client):
    r = client.get("/api/skills/does-not-exist")
    assert r.status_code == 404


def test_skill_search(client):
    r = client.get("/api/skills/search/locomotion")
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()]
    assert "policy-training-loco" in ids