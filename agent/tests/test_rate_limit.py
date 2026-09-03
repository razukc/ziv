import time

import server


def test_share_link_fetches_allowed_under_limit(client, sample_pipeline):
    pid = server.store_pipeline(sample_pipeline)
    for _ in range(server.SHARE_LINK_RATE_LIMIT):
        r = client.get(f"/api/pipeline/{pid}")
        assert r.status_code == 200
    assert len(server._share_link_limiter) == 1


def test_share_link_rate_limited_after_limit(client, sample_pipeline):
    pid = server.store_pipeline(sample_pipeline)
    for _ in range(server.SHARE_LINK_RATE_LIMIT):
        client.get(f"/api/pipeline/{pid}")
    r = client.get(f"/api/pipeline/{pid}")
    assert r.status_code == 429
    assert "detail" in r.json()
    assert int(r.headers["Retry-After"]) >= 1


def test_rate_limit_scoped_to_share_link_endpoint(client, sample_pipeline):
    pid = server.store_pipeline(sample_pipeline)
    # Burn through the share-link budget for this client.
    for _ in range(server.SHARE_LINK_RATE_LIMIT):
        client.get(f"/api/pipeline/{pid}")
    assert client.get(f"/api/pipeline/{pid}").status_code == 429
    # Every other endpoint is unaffected by the exhausted budget.
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/skills").status_code == 200
    assert client.post("/api/pipeline/validate", json={"files": {}}).status_code == 200


def test_rate_limit_keys_per_peer_ip(monkeypatch):
    """The budget is keyed on the direct peer IP, not on spoofable headers."""
    from types import SimpleNamespace
    import pytest
    from fastapi import HTTPException

    def req(host):
        return SimpleNamespace(client=SimpleNamespace(host=host))

    monkeypatch.setattr(server, "SHARE_LINK_RATE_LIMIT", 2)
    server.rate_limit_share_links(req("10.0.0.1"))
    server.rate_limit_share_links(req("10.0.0.1"))
    with pytest.raises(HTTPException) as exc:
        server.rate_limit_share_links(req("10.0.0.1"))
    assert exc.value.status_code == 429
    # A different peer starts with a fresh budget.
    server.rate_limit_share_links(req("10.0.0.2"))
    server.rate_limit_share_links(req("10.0.0.2"))
    assert len(server._share_link_limiter) == 2


def test_rate_limit_window_resets(client, sample_pipeline, monkeypatch):
    monkeypatch.setattr(server, "SHARE_LINK_RATE_LIMIT", 2)
    pid = server.store_pipeline(sample_pipeline)
    assert client.get(f"/api/pipeline/{pid}").status_code == 200
    assert client.get(f"/api/pipeline/{pid}").status_code == 200
    assert client.get(f"/api/pipeline/{pid}").status_code == 429
    # Force the window to expire, then the budget is available again.
    now = time.monotonic()
    with server._share_link_limiter_lock:
        for entry in server._share_link_limiter.values():
            entry[0] = now - server.SHARE_LINK_RATE_WINDOW_SECONDS - 1
    assert client.get(f"/api/pipeline/{pid}").status_code == 200