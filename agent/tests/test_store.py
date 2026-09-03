import server


def test_store_returns_stable_content_hash_id(sample_pipeline):
    pid1 = server.store_pipeline(sample_pipeline)
    pid2 = server.store_pipeline(sample_pipeline)
    assert pid1 == pid2
    assert pid1.startswith("p")
    assert len(pid1) == 11  # "p" + 10 hex chars
    assert server.PIPELINE_STORE[pid1] == sample_pipeline


def test_different_pipelines_get_different_ids(sample_pipeline):
    other = dict(sample_pipeline)
    other["notes"] = "different"
    assert server.store_pipeline(sample_pipeline) != server.store_pipeline(other)


def test_store_cap_evicts_oldest(sample_pipeline):
    for i in range(server.PIPELINE_STORE_MAX + 20):
        p = dict(sample_pipeline)
        p["notes"] = f"variant {i}"
        server.store_pipeline(p)
    assert len(server.PIPELINE_STORE) == server.PIPELINE_STORE_MAX
    # The first stored pipeline should have been evicted.
    assert all("variant 0" not in v["notes"] for v in server.PIPELINE_STORE.values())


def test_persist_and_reload_from_disk(sample_pipeline):
    pid = server.store_pipeline(sample_pipeline)
    # Simulate a restart: fresh in-memory store, reload from disk.
    server.PIPELINE_STORE.clear()
    server.load_pipeline_store()
    assert server.PIPELINE_STORE.get(pid) == sample_pipeline


def test_corrupt_store_file_starts_empty(tmp_path):
    """A corrupt or unreadable store file is ignored, not fatal."""
    file = tmp_path / "pipeline_store.json"
    file.write_text("{ definitely not json !!!", encoding="utf-8")
    store = server.PipelineStore(file_path=str(file))
    assert len(store) == 0
    # And a later store still works normally.
    pid = store.store({"task": "x", "subtasks": []})
    assert store.get(pid) == {"task": "x", "subtasks": []}


def test_memory_backend_used_without_redis_config(monkeypatch):
    """Without Upstash credentials the store falls back to the local backend."""
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    store = server.PipelineStore()
    assert not store.is_remote
    pid = store.store({"task": "x", "subtasks": []})
    assert store.get(pid) == {"task": "x", "subtasks": []}


class FakeRedis:
    """Minimal stand-in for the upstash_redis client (REST SDK surface)."""

    def __init__(self):
        self.data = {}          # key -> (value, ttl)
        self.zsets = {}         # key -> {member: score}

    def get(self, key):
        entry = self.data.get(key)
        return entry[0] if entry else None

    def set(self, key, value, ex=None):
        self.data[key] = (value, ex)

    def ping(self):
        return "PONG"

    def zcard(self, key):
        return len(self.zsets.get(key, {}))

    def zadd(self, key, scores):
        self.zsets.setdefault(key, {}).update(scores)

    def zrange(self, key, start, stop):
        # Mirrors Redis: negative indexes count from the end; if stop still
        # resolves negative (beyond the list), the range is empty.
        members = sorted(self.zsets.get(key, {}).items(), key=lambda kv: kv[1])
        n = len(members)
        if start < 0:
            start = max(n + start, 0)
        if stop < 0:
            stop = n + stop
        if start > stop or n == 0:
            return []
        return [m for m, _ in members[start:stop + 1]]

    def zrem(self, key, *members):
        z = self.zsets.get(key, {})
        for m in members:
            z.pop(m, None)

    def delete(self, *keys):
        for k in keys:
            self.data.pop(k, None)


def test_redis_backend_stores_and_retrieves(sample_pipeline):
    fake = FakeRedis()
    store = server.PipelineStore(redis_client=fake)
    assert store.is_remote
    pid = store.store(sample_pipeline)
    assert pid.startswith("p")
    assert store.get(pid) == sample_pipeline
    # Values are stored as JSON with the configured TTL.
    value, ttl = fake.data[f"sf:pipeline:{pid}"]
    assert ttl == server.PIPELINE_STORE_TTL_SECONDS
    assert pid in fake.zsets["sf:pipeline:created"]


def test_health_reports_redis_backend(client, monkeypatch, sample_pipeline):
    fake = FakeRedis()
    store = server.PipelineStore(redis_client=fake)
    store.store(sample_pipeline)
    monkeypatch.setattr(server, "PIPELINE_STORE", store)

    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["pipeline_store"]["backend"] == "redis"
    assert body["pipeline_store"]["entries"] == 1
    assert body["pipeline_store"]["redis_connected"] is True
    assert body["pipeline_store"]["redis_checked_at"] is not None

    # Second call within the cache TTL reports the cached ping result.
    body2 = client.get("/api/health").json()
    assert body2["pipeline_store"]["redis_connected"] is True
    assert body2["pipeline_store"]["redis_checked_at"] == body["pipeline_store"]["redis_checked_at"]


def test_ready_ok_when_redis_connected(client, monkeypatch, sample_pipeline):
    fake = FakeRedis()
    store = server.PipelineStore(redis_client=fake)
    store.store(sample_pipeline)
    monkeypatch.setattr(server, "PIPELINE_STORE", store)

    r = client.get("/api/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"
    assert r.json()["pipeline_store"]["backend"] == "redis"


def test_ready_503_when_redis_down(client, monkeypatch, sample_pipeline):
    """Configured but unreachable Redis makes the probe report degraded."""
    fake = FakeRedis()
    fake.ping = lambda: (_ for _ in ()).throw(RuntimeError("redis down"))
    store = server.PipelineStore(redis_client=fake)
    monkeypatch.setattr(server, "PIPELINE_STORE", store)

    r = client.get("/api/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["pipeline_store"]["redis_connected"] is False


def test_health_reports_redis_disconnected(client, monkeypatch, sample_pipeline):
    fake = FakeRedis()
    fake.ping = lambda: (_ for _ in ()).throw(RuntimeError("redis down"))
    store = server.PipelineStore(redis_client=fake)
    monkeypatch.setattr(server, "PIPELINE_STORE", store)

    body = client.get("/api/health").json()
    assert body["pipeline_store"]["backend"] == "redis"
    assert body["pipeline_store"]["entries"] == 0
    assert body["pipeline_store"]["redis_connected"] is False


def test_redis_backend_missing_id_returns_none():
    fake = FakeRedis()
    store = server.PipelineStore(redis_client=fake)
    assert store.get("p-unknown") is None
    assert "p-unknown" not in store


def test_redis_backend_same_pipeline_same_id(sample_pipeline):
    fake = FakeRedis()
    store = server.PipelineStore(redis_client=fake)
    assert store.store(sample_pipeline) == store.store(sample_pipeline)


def test_redis_backend_cap_evicts_oldest(sample_pipeline):
    import json
    fake = FakeRedis()
    store = server.PipelineStore(redis_client=fake, max_size=5)
    for i in range(12):
        p = dict(sample_pipeline)
        p["notes"] = f"variant {i}"
        store.store(p)
    # Only the newest 5 value keys remain, oldest evicted from both structures.
    assert len(fake.data) == 5
    notes = [json.loads(v[0])["notes"] for v in fake.data.values()]
    assert notes == [f"variant {i}" for i in range(7, 12)]
    assert len(fake.zsets["sf:pipeline:created"]) == 5


def test_api_flow_with_redis_backend(client, fake_agent, sample_pipeline, monkeypatch):
    """Compose → fetch → export works end-to-end when the store is Redis-backed.
    Simulates one server instance writing and another reading the shared store."""
    fake = FakeRedis()
    remote_store = server.PipelineStore(redis_client=fake)
    monkeypatch.setattr(server, "PIPELINE_STORE", remote_store)

    r = client.post("/api/compose/silent", json={"task": "Sort boxes", "robot": "unitree-g1"})
    assert r.status_code == 200
    pid = r.json()["pipeline_id"]
    assert pid.startswith("p")
    assert remote_store.get(pid) is not None

    # A different "instance" (fresh store over the same fake Redis) sees it.
    other = server.PipelineStore(redis_client=fake)
    expected = dict(sample_pipeline)
    expected["task"] = "Sort boxes"  # FakeAgent stamps the request task
    assert other.get(pid) == expected

    r2 = client.get(f"/api/pipeline/{pid}")
    assert r2.status_code == 200
    assert r2.json()["pipeline_id"] == pid

    # Export by id resolves from the store — no re-decompose, same id back.
    r3 = client.post("/api/pipeline/export", json={"task": "ignored", "robot": "unitree-g1", "pipeline_id": pid})
    assert r3.status_code == 200
    assert r3.json()["pipeline_id"] == pid