"""Device flows over the WebSocket, driven with a FakeClock and a FakeComposer."""
from __future__ import annotations

import json

import pytest
from starlette.websockets import WebSocketDisconnect
from test_relay_harness import HangingComposer, Harness, running

from ziv.core import spec
from ziv.relay.composer import ComposeError


@pytest.fixture()
def h(tmp_path):
    with running(tmp_path) as harness:
        yield harness


def test_submit_hello_resend_progress_played(h: Harness):
    _, key = h.enroll()
    uid = h.submit("hello").json()["id"]
    assert h.get(uid)["state"] == "pending"
    with h.device(key) as (ws, ack):
        assert ack["type"] == "hello.ack" and ack["prefs"]["pace_ms"] == spec.pace_envelope()[2]
        assert [u["id"] for u in ack["resend"]] == [uid]
        utt = ack["resend"][0]
        assert utt["words"] == ["hello"] and utt["prefix"] == {"mark": "ziv", "tail": spec.tail_for("message")}
        assert utt["from"]["sender"] == "admin" and utt["spec_version"] == spec.spec_version()
        assert h.get(uid)["state"] == "sent" and h.get(uid)["device"] == ack["device"]
        assert h.client.get("/health").json()["devices_connected"] == 1
        ws.send_json({"type": "progress", "id": uid, "phase": "cue"})
        h.sync(ws)
        assert h.get(uid)["state"] == "playing"
        ws.send_json({"type": "progress", "id": uid, "phase": "word", "word_index": 0})
        ws.send_json({"type": "played", "id": uid, "started_ms": 1000, "closed_ms": 4200})
        h.sync(ws)
        view = h.get(uid)
        assert view["state"] == "played" and view["reason"] is None
        # a second utterance while connected arrives as utterance.open
        uid2 = h.submit("again").json()["id"]
        frame = ws.receive_json()
        assert frame["type"] == "utterance.open" and frame["utterance"]["id"] == uid2
        assert h.get(uid2)["state"] == "sent"
    kinds = [e["kind"] for e in h.events()]
    assert "device_hello" in kinds and "playing" in kinds and "played" in kinds
    played = [e for e in h.events() if e["kind"] == "played"][0]
    assert played["counts"] == {"played_ms": 3200}


def test_hello_with_held_ids_skips_them_and_cancels_what_it_should_not_play(h: Harness):
    _, key = h.enroll()
    a = h.submit("alpha").json()["id"]
    b = h.submit("bravo").json()["id"]
    with h.device(key) as (ws, ack):
        assert {u["id"] for u in ack["resend"]} == {a, b}
    # the device went away holding both; both return to pending
    assert h.get(a)["state"] == "pending" and h.get(a)["reason"] == "device_gone"
    h.client.delete(f"/utterances/{b}", headers=h.auth())
    with h.device(key, held=[a, b]) as (ws, ack):
        assert ack["resend"] == []                       # it already holds a
        cancel = ws.receive_json()
        assert cancel == {"type": "utterance.cancel", "id": b, "reason": "cancelled_by_sender"}
        assert h.get(a)["state"] == "sent"


def test_hello_last_acked_counts_as_played(h: Harness):
    _, key = h.enroll()
    uid = h.submit("hello").json()["id"]
    with h.device(key) as (ws, ack):
        ws.send_json({"type": "progress", "id": uid, "phase": "cue"})
        h.sync(ws)
    assert h.get(uid)["state"] == "pending"            # the socket dropped while it played
    with h.device(key, last_acked=uid) as (ws, ack):
        assert ack["resend"] == []                        # it was played offline: not sent again
    view = h.get(uid)
    assert view["state"] == "played" and view["device"] == ack["device"]
    # an id another device holds now is left to that device
    uid2 = h.submit("second").json()["id"]
    _, key2 = h.enroll("two")
    with h.device(key) as (ws1, _):
        with h.device(key2, last_acked=uid2) as (ws2, ack2):
            assert ack2["resend"] == []
            assert h.get(uid2)["state"] == "sent" and h.get(uid2)["device"] != ack2["device"]


def test_bad_first_frame_closes_4401(h: Harness):
    _, key = h.enroll()
    with h.client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "progress", "id": "not-a-hello-0", "phase": "cue"})
        err = ws.receive_json()
        assert err["type"] == "error" and err["reason"] == "unauthorized"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
    with h.client.websocket_connect("/ws") as ws:
        ws.send_text("this is not json")
        assert ws.receive_json()["reason"] == "unauthorized"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
    with h.client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "v": 1, "device_key": "wrong-key-wrong-key", "profile": "six_actuator",
                      "spec_version": spec.spec_version()})
        assert ws.receive_json()["reason"] == "unauthorized"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
    assert h.client.get("/health").json()["devices_connected"] == 0
    refused = [e for e in h.events() if e["kind"] == "ws_refused"]
    assert len(refused) == 3 and "wrong-key-wrong-key" not in json.dumps(refused)


def test_failover_after_the_handoff_window_to_a_second_device(h: Harness):
    d1, key1 = h.enroll("primary")
    d2, key2 = h.enroll("phone", profile="single_actuator")
    with h.device(key1) as (ws1, _), h.device(key2, profile="single_actuator") as (ws2, _):
        uid = h.submit("hello").json()["id"]
        frame = ws1.receive_json()
        assert frame["type"] == "utterance.open" and frame["utterance"]["id"] == uid
        assert h.get(uid)["device"] == d1
        h.advance(h.settings.handoff_window_s - 0.5)
        h.tick()
        assert h.get(uid)["device"] == d1 and h.get(uid)["state"] == "sent"
        h.advance(1)
        h.tick()
        assert ws1.receive_json() == {"type": "utterance.cancel", "id": uid, "reason": "failover"}
        frame = ws2.receive_json()
        assert frame["type"] == "utterance.open" and frame["utterance"]["id"] == uid
        view = h.get(uid)
        assert view["device"] == d2 and view["state"] == "sent"
        # the slow primary starts it anyway: a logged duplicate, not a transition
        ws1.send_json({"type": "progress", "id": uid, "phase": "cue"})
        h.sync(ws1)
        assert h.get(uid)["device"] == d2
        assert any(e["kind"] == "duplicate_play" for e in h.events())
        ws2.send_json({"type": "played", "id": uid, "started_ms": 0, "closed_ms": 900})
        h.sync(ws2)
        assert h.get(uid)["state"] == "played"
    fo = [e for e in h.events() if e["kind"] == "failover"]
    assert len(fo) == 1 and fo[0]["reason"] == "failover" and fo[0]["counts"] == {"tried": 1}


def test_failover_with_one_device_waits_for_its_next_hello(h: Harness):
    d1, key1 = h.enroll()
    with h.device(key1) as (ws, _):
        uid = h.submit("hello").json()["id"]
        ws.receive_json()
        h.advance(h.settings.handoff_window_s + 1)
        h.tick()
        assert ws.receive_json()["type"] == "utterance.cancel"
        view = h.get(uid)
        assert view["state"] == "pending" and view["device"] is None and view["reason"] == "failover"
        h.tick()
        assert h.get(uid)["state"] == "pending"           # not re-offered to the same silent socket
    with h.device(key1) as (ws, ack):
        assert [u["id"] for u in ack["resend"]] == [uid]  # a fresh hello is a fresh chance


def test_expiry_drop_and_play(h: Harness):
    _, key = h.enroll()
    now = h.clock.now()
    uid = h.submit("soon", expires=now + 60).json()["id"]
    h.advance(59)
    h.tick()
    assert h.get(uid)["state"] == "pending"
    h.advance(1)
    h.tick()
    view = h.get(uid)
    assert view["state"] == "expired" and view["reason"] == "expired"
    assert h.client.get("/health").json()["outbox"]["expired"] == 1
    # late = play: the entry survives and the device gets it, late
    h.client.put("/prefs", json={"late": "play"}, headers=h.auth())
    uid2 = h.submit("late one", expires=h.clock.now() + 30).json()["id"]
    h.advance(31)
    h.tick()
    assert h.get(uid2)["state"] == "pending"
    with h.device(key) as (ws, ack):
        assert [u["id"] for u in ack["resend"]] == [uid2]
    assert [e for e in h.events() if e["kind"] == "late_play"]
    # an entry recalled from a device on expiry gets a cancel frame
    h.client.put("/prefs", json={"late": "drop"}, headers=h.auth())
    with h.device(key) as (ws, ack):
        assert [u["id"] for u in ack["resend"]] == [uid2]
        uid3 = h.submit("recall me", expires=h.clock.now() + 10).json()["id"]
        h.frames_until(ws, "utterance.open")
        h.advance(10)
        h.tick()
        cancels = {h.frames_until(ws, "utterance.cancel")["id"], h.frames_until(ws, "utterance.cancel")["id"]}
        assert cancels == {uid2, uid3}
        assert h.get(uid3) == h.get(uid3) | {"state": "expired", "reason": "expired", "device": None}


def test_schedule_text_fires_through_admission(h: Harness):
    fire_at = h.clock.now() + 120
    r = h.client.post("/schedule", json={"fire_at": fire_at, "text": "Meds 9", "label": "pills"}, headers=h.auth())
    sid = r.json()["id"]
    h.advance(119)
    h.tick()
    assert h.client.get("/utterances", headers=h.auth()).json() == []
    h.advance(1)
    h.tick()
    assert h.client.get("/schedule", headers=h.auth()).json() == []
    [view] = h.client.get("/utterances", headers=h.auth()).json()
    assert view["state"] == "pending" and view["kind"] == "reminder" and view["words"] == ["meds", "nine"]
    assert view["source"] == "sender"
    entry = h.store.outbox.get(view["id"])
    assert entry.utterance.prefix.mark == spec.prefix_mark() and entry.utterance.prefix.tail == spec.tail_for("reminder")
    assert entry.utterance.from_.sender == "schedule" and entry.utterance.from_.label == "pills"
    assert entry.expires_at() == fire_at + 3600 and entry.not_before_at() == fire_at
    assert h.store.schedule.get(sid) is None
    assert [e["kind"] for e in h.events() if e["kind"] in ("schedule_fired", "admitted")] == ["admitted", "schedule_fired"]


def test_schedule_intent_body_pending_then_body(h: Harness):
    _, key = h.enroll()
    h.composer.results.append(["pills", "now"])
    fire_at = h.clock.now() + 10
    h.client.post("/schedule", json={"fire_at": fire_at, "intent": "remind me to take the pills"}, headers=h.auth())
    with h.device(key) as (ws, _):
        h.advance(10)
        h.tick()
        frame = ws.receive_json()
        assert frame["type"] == "utterance.open"
        utt = frame["utterance"]
        assert utt["body_pending"] is True and utt["words"] == [] and utt["kind"] == "reminder"
        uid = utt["id"]
        assert h.get(uid)["state"] == "sent"
        ws.send_json({"type": "progress", "id": uid, "phase": "cue"})
        ws.send_json({"type": "progress", "id": uid, "phase": "working"})
        h.drain()
        body = h.frames_until(ws, "utterance.body")
        assert body == {"type": "utterance.body", "id": uid, "words": ["pills", "now"], "source": "live"}
        h.sync(ws)
        view = h.get(uid)
        assert view["words"] == ["pills", "now"] and view["source"] == "live" and view["state"] == "playing"
        assert view["duration_ms"] > 0
        assert h.composer.calls[0]["budget_ms"] == h.settings.budget_ms
        assert h.composer.calls[0]["profile"] == "six_actuator" and h.composer.calls[0]["api_key"] is None
        ws.send_json({"type": "played", "id": uid, "started_ms": 0, "closed_ms": 5000})
        h.sync(ws)
        assert h.get(uid)["state"] == "played"
    compose = [e for e in h.events() if e["kind"] == "compose"]
    assert compose and compose[-1]["counts"] == {"ok": 1, "words": 2}
    assert "pills" not in json.dumps(h.events())
    assert h.client.get("/health").json()["compose"]["ok"] == 1


def test_schedule_intent_compose_failure_plays_the_error(h: Harness):
    _, key = h.enroll()
    h.composer.results.append(ComposeError(detail="3 attempts over budget"))
    h.client.post("/schedule", json={"fire_at": h.clock.now(), "intent": "something"}, headers=h.auth())
    with h.device(key) as (ws, _):
        h.tick()
        uid = ws.receive_json()["utterance"]["id"]
        h.drain()
        body = ws.receive_json()
        assert body == {"type": "utterance.body", "id": uid, "words": [], "source": "live", "error": "compose_failed"}
        view = h.get(uid)
        assert view["state"] == "failed" and view["reason"] == "compose_failed"
    ev = [e for e in h.events() if e["kind"] == "compose"][-1]
    assert ev["reason"] == "compose_failed" and ev["counts"] == {"ok": 0}


def test_body_timeout_fails_the_entry_and_tells_the_device(tmp_path):
    with running(tmp_path, composer=HangingComposer()) as h:
        _, key = h.enroll()
        h.client.post("/schedule", json={"fire_at": h.clock.now(), "intent": "slow"}, headers=h.auth())
        with h.device(key) as (ws, _):
            h.tick()
            uid = ws.receive_json()["utterance"]["id"]
            assert h.composer.started == 1
            ws.send_json({"type": "progress", "id": uid, "phase": "cue"})   # cued: the device is ticking
            h.sync(ws)
            h.advance(h.settings.handoff_window_s + 1)
            h.tick()                                                         # no failover: it is playing
            assert h.get(uid)["state"] == "playing"
            h.advance(h.settings.body_timeout_s - h.settings.handoff_window_s - 1)
            h.tick()
            assert ws.receive_json() == {"type": "utterance.body", "id": uid, "words": [], "source": "live",
                                         "error": "body_timeout"}
            assert h.get(uid)["state"] == "failed" and h.get(uid)["reason"] == "body_timeout"
        assert not h.relay._compose_tasks


def test_intent_without_a_device_composes_and_is_delivered_complete(h: Harness):
    h.composer.results.append(["water", "plants"])
    h.client.post("/schedule", json={"fire_at": h.clock.now(), "intent": "water the plants"}, headers=h.auth())
    h.tick()
    h.drain()
    [view] = h.client.get("/utterances", headers=h.auth()).json()
    assert view["state"] == "pending" and view["words"] == ["water", "plants"] and view["source"] == "live"
    _, key = h.enroll()
    with h.device(key) as (ws, ack):
        [utt] = ack["resend"]
        assert utt["body_pending"] is False and utt["words"] == ["water", "plants"]


def test_echo_source_when_no_model_is_configured(tmp_path):
    from ziv.relay.composer import EchoComposer

    with running(tmp_path, composer=EchoComposer()) as h:
        h.client.post("/schedule", json={"fire_at": h.clock.now(), "intent": "take meds at 9"}, headers=h.auth())
        h.tick()
        h.drain()
        [view] = h.client.get("/utterances", headers=h.auth()).json()
        assert view["source"] == "echo" and view["words"] == ["take", "meds", "at", "nine"]
        assert h.client.get("/health").json()["compose"]["source"] == "echo"


def test_lease_blocks_a_second_claim_until_it_expires(h: Harness):
    h.client.post("/schedule", json={"fire_at": h.clock.now(), "text": "meds"}, headers=h.auth())
    claimed = h.store.schedule.claim_due(h.clock.now(), h.settings.lease_s)   # "another process" claimed it
    assert len(claimed) == 1
    h.tick()
    assert h.client.get("/utterances", headers=h.auth()).json() == []         # leased: not fired twice
    h.advance(h.settings.lease_s)
    h.tick()
    assert len(h.client.get("/utterances", headers=h.auth()).json()) == 1     # the lease expired: fired once
    assert h.client.get("/schedule", headers=h.auth()).json() == []


def test_schedule_at_cap_is_deferred_not_lost(tmp_path):
    with running(tmp_path, outbox_cap=1) as h:
        h.submit("occupies the slot")
        h.client.post("/schedule", json={"fire_at": h.clock.now(), "text": "meds"}, headers=h.auth())
        h.tick()
        assert len(h.client.get("/schedule", headers=h.auth()).json()) == 1
        assert any(e["kind"] == "refused" and e["reason"] == "queue_full" for e in h.events())
        [u] = h.client.get("/utterances", headers=h.auth()).json()
        h.client.delete(f"/utterances/{u['id']}", headers=h.auth())
        h.advance(h.settings.lease_s)
        h.tick()
        assert h.client.get("/schedule", headers=h.auth()).json() == []
        assert len(h.client.get("/utterances", params={"state": "pending"}, headers=h.auth()).json()) == 1


def test_device_gone_requeues_and_a_second_device_takes_over(h: Harness):
    d1, key1 = h.enroll("one")
    d2, key2 = h.enroll("two")
    with h.device(key2) as (ws2, _):
        with h.device(key1) as (ws1, _):
            uid = h.submit("hello").json()["id"]
            assert ws1.receive_json()["type"] == "utterance.open"     # primary first
            assert h.get(uid)["device"] == d1
        # d1's socket closed: the entry goes back to pending, then straight to d2
        frame = ws2.receive_json()
        assert frame["type"] == "utterance.open" and frame["utterance"]["id"] == uid
        assert h.get(uid)["device"] == d2
    assert h.get(uid)["state"] == "pending" and h.get(uid)["reason"] == "device_gone"


def test_input_text_control_and_pref_changed(h: Harness):
    d1, key1 = h.enroll("one")
    d2, key2 = h.enroll("two")
    uid = h.submit("question").json()["id"]
    with h.device(key1) as (ws1, _), h.device(key2) as (ws2, _):
        ws1.send_json({"type": "input.text", "words": ["yes"], "in_reply_to": uid})
        ws1.send_json({"type": "input.text", "words": ["hello", "there"]})
        ws1.send_json({"type": "control", "action": "stop"})
        ws1.send_json({"type": "pref.changed", "prefs": {"pace_ms": 300}})
        h.sync(ws1)
        replies = h.client.get("/replies", headers=h.auth()).json()
        assert [(r["words"], r["in_reply_to"]) for r in replies] == [(["hello", "there"], None), (["yes"], uid)]
        assert h.client.get("/replies", params={"undelivered": "true"}, headers=h.auth()).json() == []
        assert h.client.get("/prefs", headers=h.auth()).json()["pace_ms"] == 300
        assert ws2.receive_json() == {"type": "pref.set", "prefs": {"pace_ms": 300, "advance": "auto", "late": "drop",
                                                                  "history": False}}
        # a pref put from the console reaches every device
        h.client.put("/prefs", json={"advance": "tap"}, headers=h.auth())
        assert h.frames_until(ws1, "pref.set")["prefs"]["advance"] == "tap"
        assert h.frames_until(ws2, "pref.set")["prefs"]["advance"] == "tap"
        # an invalid frame is answered with a content-free error, and the socket stays up
        ws1.send_json({"type": "progress", "id": uid, "phase": "sideways"})
        err = h.frames_until(ws1, "error")
        assert err["reason"] == "bad_request"
        h.sync(ws1)
    ev = json.dumps(h.events())
    assert "yes" not in json.dumps([e for e in h.events() if e["kind"] == "reply"])
    assert [e for e in h.events() if e["kind"] == "control"][0]["detail"] == "stop"
    assert "there" not in ev


def test_nack_fails_with_the_devices_reason(h: Harness):
    _, key = h.enroll()
    uid = h.submit("hello").json()["id"]
    with h.device(key) as (ws, _):
        ws.send_json({"type": "nack", "id": uid, "reason": "muted"})
        h.sync(ws)
        view = h.get(uid)
        assert view["state"] == "failed" and view["reason"] == "muted"
        # a late frame for a terminal entry is logged, never raised
        ws.send_json({"type": "played", "id": uid, "started_ms": 0, "closed_ms": 1})
        h.sync(ws)
    assert any(e["kind"] == "late_frame" for e in h.events())


def test_profile_mismatch_with_enrollment_is_refused(h: Harness):
    _, key = h.enroll(profile="six_actuator")
    with h.client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "v": 1, "device_key": key, "profile": "single_actuator",
                      "spec_version": spec.spec_version()})
        assert ws.receive_json()["reason"] == "spec_mismatch"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4400


def test_budget_follows_the_primary_devices_profile_and_the_wearers_pace(h: Harness):
    r1 = h.submit("hello world").json()
    h.client.put("/prefs", json={"pace_ms": 700}, headers=h.auth())
    r2 = h.submit("hello world").json()
    assert r2["duration_ms"] > r1["duration_ms"]


def test_prune_runs_on_tick_by_retention(tmp_path):
    with running(tmp_path, retention_days=1) as h:
        uid = h.submit("old").json()["id"]
        h.client.delete(f"/utterances/{uid}", headers=h.auth())
        h.advance(86_400 + 1)
        h.tick()
        assert h.client.get(f"/utterances/{uid}", headers=h.auth()).status_code == 404
        prune = [e for e in h.events() if e["kind"] == "prune"]
        assert prune and prune[-1]["counts"]["utterances"] == 1
