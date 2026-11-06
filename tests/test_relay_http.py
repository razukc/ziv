"""The sender HTTP surface, end to end against a real app with a temp database."""
from __future__ import annotations

import json

import pytest
from test_relay_harness import ADMIN, Harness, running

from ziv.core import spec
from ziv.haptics import tables


@pytest.fixture()
def h(tmp_path):
    with running(tmp_path) as harness:
        yield harness


def test_submit_without_device_is_pending_and_echoes_words(h: Harness):
    r = h.submit("Meds at 9am!")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["state"] == "pending" and body["words"] == ["meds", "at", "nine", "am"]
    assert body["source"] == "sender" and body["device"] is None and body["reason"] is None
    assert body["budget_ms"] == h.settings.budget_ms and 0 < body["duration_ms"] <= body["budget_ms"]
    assert body["lossy"] is False
    assert h.get(body["id"])["state"] == "pending"
    listed = h.client.get("/utterances", params={"state": "pending"}, headers=h.auth()).json()
    assert [u["id"] for u in listed] == [body["id"]]


def test_auth_required_and_scoped(h: Harness):
    assert h.client.get("/utterances").status_code == 401
    r = h.client.get("/utterances", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and r.json()["reason"] == "unauthorized"
    read_only = h.sender("reader", scopes=("read",))
    assert h.client.get("/utterances", headers=h.auth(read_only)).status_code == 200
    r = h.submit("hi", token=read_only)
    assert r.status_code == 401 and r.json()["reason"] == "unauthorized"
    assert h.client.post("/senders", json={"label": "x"}, headers=h.auth(read_only)).status_code == 401
    assert h.client.get("/health").status_code == 200           # public
    assert h.client.get("/spec").json() == tables.SPEC            # public, verbatim


def test_over_budget_is_413_with_both_numbers(h: Harness):
    r = h.submit("the quick brown fox jumps over the lazy dog again and again")
    assert r.status_code == 413, r.text
    body = r.json()
    assert body["reason"] == "over_budget"
    assert body["detail"]["budget_ms"] == h.settings.budget_ms
    assert body["detail"]["duration_ms"] > h.settings.budget_ms
    assert h.client.get("/health").json()["outbox"]["pending"] == 0


def test_cap_refuses_the_newest_with_429(tmp_path):
    with running(tmp_path, outbox_cap=2) as h:
        ids = [h.submit(t).json()["id"] for t in ("one", "two")]
        r = h.submit("three")
        assert r.status_code == 429 and r.json()["reason"] == "queue_full"
        assert r.json()["detail"] == {"active": 2, "cap": 2}
        assert [u["id"] for u in h.client.get("/utterances", headers=h.auth()).json()] == ids[::-1]
        # cancelling frees a slot
        assert h.client.delete(f"/utterances/{ids[0]}", headers=h.auth()).json()["state"] == "cancelled"
        assert h.submit("three").status_code == 201


def test_unencodable_refused_then_accepted_with_allow_lossy(h: Harness):
    r = h.submit("café")
    assert r.status_code == 422 and r.json()["reason"] == "unencodable"
    assert r.json()["detail"]["characters"] == ["é"]
    r = h.submit("café", allow_lossy=True)
    assert r.status_code == 201 and r.json()["words"] == ["cafe"] and r.json()["lossy"] is True


def test_validation_errors_carry_a_reason(h: Harness):
    r = h.client.post("/utterances", json={}, headers=h.auth())
    assert r.status_code == 422 and r.json()["reason"] == "bad_request"
    r = h.client.post("/utterances", json={"text": "hi", "words": ["hi"]}, headers=h.auth())
    assert r.status_code == 422 and r.json()["reason"] == "bad_request"
    r = h.client.post("/utterances", json={"text": "hi", "extra": 1}, headers=h.auth())
    assert r.status_code == 422
    for err in r.json()["detail"]["errors"]:
        assert "input" not in err


def test_body_over_64k_is_413(h: Harness):
    big = json.dumps({"text": "x" * (70 * 1024)})
    r = h.client.post("/utterances", content=big, headers={**h.auth(), "Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["reason"] == "bad_request"
    assert r.json()["detail"]["max_body_bytes"] == h.settings.max_body_bytes


def test_cancel_and_not_found(h: Harness):
    id = h.submit("hello").json()["id"]
    r = h.client.delete(f"/utterances/{id}", headers=h.auth())
    assert r.status_code == 200 and r.json()["state"] == "cancelled" and r.json()["reason"] == "cancelled_by_sender"
    r = h.client.delete(f"/utterances/{id}", headers=h.auth())
    assert r.status_code == 409 and r.json()["reason"] == "conflict"
    r = h.client.get("/utterances/does-not-exist", headers=h.auth())
    assert r.status_code == 404 and r.json()["reason"] == "not_found"


def test_rate_limit_per_sender_on_the_injected_clock(h: Harness):
    tok = h.sender("bursty", rate_per_min=2)
    assert h.submit("one", token=tok).status_code == 201
    assert h.submit("two", token=tok).status_code == 201
    r = h.submit("three", token=tok)
    assert r.status_code == 429 and r.json()["reason"] == "rate_limited"
    h.advance(30)
    assert h.submit("four", token=tok).status_code == 201   # one token refilled
    assert h.submit("five", token=tok).status_code == 429
    assert h.submit("admin is separate").status_code == 201


def test_prefs_are_clamped_into_the_spec_envelope(h: Harness):
    lo, hi, default = spec.pace_envelope()
    assert h.client.get("/prefs", headers=h.auth()).json()["pace_ms"] == default
    r = h.client.put("/prefs", json={"pace_ms": 100}, headers=h.auth())
    assert r.status_code == 200 and r.json()["pace_ms"] == lo
    r = h.client.put("/prefs", json={"pace_ms": 2000, "advance": "tap", "late": "play"}, headers=h.auth())
    assert r.json() == {"pace_ms": hi, "advance": "tap", "late": "play", "history": False}
    assert h.client.get("/prefs", headers=h.auth()).json()["pace_ms"] == hi
    assert h.client.put("/prefs", json={"pace_ms": 50}, headers=h.auth()).status_code == 422  # wire floor


def test_schedule_crud_and_cap(tmp_path):
    with running(tmp_path, schedule_cap=2) as h:
        fire_at = h.clock.now() + 600
        r = h.client.post("/schedule", json={"fire_at": fire_at, "text": "meds 9", "label": "pills"}, headers=h.auth())
        assert r.status_code == 201, r.text
        first = r.json()
        assert first["composed"] is False and first["kind"] == "reminder" and first["label"] == "pills"
        r = h.client.post("/schedule", json={"fire_at": fire_at, "intent": "take the pills"}, headers=h.auth())
        assert r.status_code == 201 and r.json()["composed"] is True
        r = h.client.post("/schedule", json={"fire_at": fire_at, "text": "third"}, headers=h.auth())
        assert r.status_code == 429 and r.json()["reason"] == "queue_full"
        assert [s["id"] for s in h.client.get("/schedule", headers=h.auth()).json()] == [1, 2]
        assert h.client.get("/schedule/1", headers=h.auth()).json() == first
        assert h.client.delete("/schedule/1", headers=h.auth()).status_code == 200
        assert h.client.delete("/schedule/1", headers=h.auth()).status_code == 404
        assert h.client.get("/health").json()["schedule_pending"] == 1
        # a text that could never fit is refused now, not at fire time
        r = h.client.post("/schedule", json={"fire_at": fire_at, "text": "the quick brown fox jumps over the lazy dog"},
                          headers=h.auth())
        assert r.status_code == 413 and r.json()["reason"] == "over_budget"
        r = h.client.post("/schedule", json={"fire_at": fire_at, "text": "café"}, headers=h.auth())
        assert r.status_code == 422 and r.json()["reason"] == "unencodable"


def test_senders_and_devices_admin_surface(h: Harness):
    r = h.client.post("/senders", json={"label": "mum", "scopes": ["send"]}, headers=h.auth())
    assert r.status_code == 201 and r.json()["token"] and r.json()["scopes"] == ["send"]
    token = r.json()["token"]
    listed = h.client.get("/senders", headers=h.auth()).json()
    assert len(listed) == 1 and listed[0]["token"] is None            # shown once only
    assert h.submit("hi", token=token).json()["words"] == ["hi"]
    code = h.client.post("/devices/enroll-code", headers=h.auth())
    assert code.status_code == 201 and 6 <= len(code.json()["code"]) <= 12
    r = h.client.post("/devices/enroll", json={"code": "ZZZZZZ", "profile": "six_actuator", "name": "x"})
    assert r.status_code == 401 and r.json()["reason"] == "unauthorized"
    r = h.client.post("/devices/enroll", json={"code": code.json()["code"], "profile": "six_actuator", "name": "band"})
    assert r.status_code == 201 and len(r.json()["device_key"]) >= 16
    r2 = h.client.post("/devices/enroll", json={"code": code.json()["code"], "profile": "six_actuator", "name": "again"})
    assert r2.status_code == 401                                        # a code is exchanged once
    devices = h.client.get("/devices", headers=h.auth()).json()
    assert len(devices) == 1 and devices[0]["primary"] is True and devices[0]["connected"] is False
    h.advance(h.settings.enroll_code_ttl_s + 1)
    code2 = h.client.post("/devices/enroll-code", headers=h.auth()).json()["code"]
    h.advance(h.settings.enroll_code_ttl_s + 1)
    r = h.client.post("/devices/enroll", json={"code": code2, "profile": "single_actuator", "name": "phone"})
    assert r.status_code == 401                                         # expired


def test_a_device_key_never_appears_anywhere_but_its_one_response(h: Harness):
    device_id, key = h.enroll()
    h.submit("hello there")
    with h.device(key) as (ws, ack):
        h.sync(ws)
    texts = [
        h.client.get("/devices", headers=h.auth()).text,
        h.client.get("/health").text,
        h.client.get("/utterances", headers=h.auth()).text,
        h.client.get("/senders", headers=h.auth()).text,
        json.dumps(h.events()),
        h.db_dump(),
    ]
    assert all(key not in t for t in texts)
    assert ADMIN not in h.db_dump() and ADMIN not in json.dumps(h.events())


def test_health_and_events_carry_no_words(h: Harness):
    h.submit("zebra quince")
    h.client.post("/schedule", json={"fire_at": h.clock.now() + 60, "text": "xylophone"}, headers=h.auth())
    h.submit("café ünd")                      # refused, with characters in the response only
    health = h.client.get("/health").text
    events = json.dumps(h.events())
    for word in ("zebra", "quince", "xylophone", "é", "ü", "caf"):
        assert word not in health and word not in events
    hj = json.loads(health)
    assert hj["outbox"]["pending"] == 1 and hj["schedule_pending"] == 1 and hj["caps"]["outbox"] == 20
    assert hj["compose"]["attempts"] == 0 and hj["devices_connected"] == 0
    kinds = {e["kind"] for e in h.events()}
    assert {"start", "integrity_check", "admitted", "refused", "scheduled"} <= kinds
