"""The real relay, over TCP, driven by the real web renderer running headless
(docs/ARCHITECTURE.md §10, tier 3 with a real device program).

A relay under uvicorn on an ephemeral loopback port with the system clock and
a 100 ms poll; ``client/dist/device-cli.js`` (the page's ``Device`` with an
instant playback clock) as the device. Skips cleanly when node or the built
CLI is missing; builds the CLI once per session when ``client/node_modules``
exists. Whole module: seconds.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from relay_live import DEVICE_CLI, NODE, DeviceCli, LiveRelay, build_front_end, wait_until

from ziv.core import spec
from ziv.wire import Profile, Utterance

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytest.fixture(scope="session")
def device_cli():
    reason = build_front_end("client", need=("device-cli.js",))
    if reason:
        pytest.skip(reason)
    return DEVICE_CLI


@pytest.fixture()
def relay(tmp_path, device_cli):
    with LiveRelay(tmp_path) as live:
        yield live


@pytest.fixture()
def clis():
    started: list[DeviceCli] = []
    yield started
    for c in started:
        c.kill()


def start_cli(clis: list[DeviceCli], relay: LiveRelay, *args: str) -> DeviceCli:
    cli = DeviceCli(relay, "--clock", "instant", *args)
    clis.append(cli)
    return cli


def progress_phases(cli: DeviceCli, id: str) -> list[str]:
    return [f"{e['phase']}{'' if e.get('word_index') is None else e['word_index']}" for e in cli.of("progress") if e["id"] == id]


def test_a_message_submitted_before_the_device_connects_plays_when_it_does(relay: LiveRelay, clis):
    r = relay.post("/utterances", {"text": "Go now!", "label": "mum"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert r.json()["state"] == "pending" and r.json()["words"] == ["go", "now"]

    cli = start_cli(clis, relay, "--enroll", relay.enroll_code, "--name", "headless", "--utterances", "1", "--idle-exit", "5000")
    assert cli.wait_exit() == 0, "\n".join(cli.stderr)
    enrolled = cli.of("enrolled")[0]
    assert enrolled["device"].startswith("d_") and len(enrolled["device_key"]) >= 16
    ack = cli.of("hello.ack")[0]
    assert ack["resend"] == [uid] and ack["device"] == enrolled["device"] and ack["spec_version"] == spec.spec_version()
    opened = cli.of("open")[0]
    assert opened["id"] == uid and opened["via"] == "resend" and opened["words"] == ["go", "now"]
    assert opened["prefix"] == {"mark": spec.prefix_mark(), "tail": spec.tail_for("message")} and opened["label"] == "mum"
    assert progress_phases(cli, uid) == ["cue", "word0", "word1", "close"]
    played = cli.of("played")[0]
    # admission measured the message on the default profile (no device was enrolled yet); the device
    # played it on its own, so the reported duration is the single_actuator reference, not the view's
    reference = Utterance(id=uid, wearer=relay.wearer, kind="message", **{"from": {"sender": "x"}},
                          prefix=opened["prefix"], words=opened["words"], spec_version=spec.spec_version())
    expected_ms = spec.duration_ms(reference, Profile.single_actuator, spec.pace_envelope()[2])
    assert played["id"] == uid and played["closed_ms"] - played["started_ms"] == expected_ms
    assert r.json()["duration_ms"] == relay.view(uid)["duration_ms"]  # the view keeps admission's number
    assert cli.of("exit")[0] == cli.of("exit")[0] | {"reason": "played", "played": 1}

    view = relay.view(uid)
    assert view["state"] == "played" and view["device"] == enrolled["device"] and view["reason"] is None
    [device] = relay.get("/devices").json()
    assert device["device"] == enrolled["device"] and device["primary"] is True and device["profile"] == "single_actuator"
    health = relay.client.get("/health").json()
    assert health["outbox"]["played"] == 1 and health["devices_connected"] == 0
    for text in (json.dumps(health), relay.get("/utterances").text):
        assert enrolled["device_key"] not in text


def test_compose_with_echo_reaches_the_device_as_body_pending_then_the_words(relay: LiveRelay, clis):
    _, key = relay.enroll_device()
    cli = start_cli(clis, relay, "--key", key, "--utterances", "1", "--idle-exit", "8000")
    cli.wait_event("hello.ack")

    r = relay.post("/compose", {"intent": "Meds now", "label": "agent"})
    assert r.status_code == 201, r.text
    view = r.json()
    assert view["words"] == ["meds", "now"] and view["source"] == "echo" and view["kind"] == "reminder"
    assert view["state"] in ("sent", "playing", "played") and view["reason"] is None
    uid = view["id"]

    assert cli.wait_exit() == 0, "\n".join(cli.stderr)
    opened = cli.of("open")[0]
    assert opened["id"] == uid and opened["via"] == "open" and opened["body_pending"] is True and opened["words"] == []
    assert opened["source"] == "echo" and opened["prefix"]["tail"] == spec.tail_for("reminder")
    body = cli.of("body")[0]
    assert body == body | {"id": uid, "words": ["meds", "now"], "source": "echo", "error": None}
    phases = progress_phases(cli, uid)
    assert phases[0] == "cue" and phases[-3:] == ["word0", "word1", "close"]
    assert cli.of("played")[0]["id"] == uid and not cli.of("nack")
    final = relay.view(uid)
    assert final["state"] == "played" and final["source"] == "echo" and final["words"] == ["meds", "now"]
    assert relay.client.get("/health").json()["compose"]["source"] == "echo"


def test_hidden_nack_returns_the_entry_to_pending_until_the_device_reconnects(relay: LiveRelay, clis):
    _, key = relay.enroll_device()
    uid = relay.post("/utterances", {"text": "go now"}).json()["id"]
    cli = start_cli(clis, relay, "--key", key, "--hidden-once", "--hidden-reconnect-ms", "600",
                    "--utterances", "1", "--idle-exit", "8000")
    nack = cli.wait_event("nack")
    assert nack["id"] == uid and nack["reason"] == "hidden"
    # the relay holds it as pending, with the device's refusal recorded, until that device's next hello
    pending = relay.wait_state(uid, "pending", timeout=2.0)
    assert pending["reason"] == "hidden" and pending["device"] is None
    wait_until(lambda: relay.view(uid)["state"] == "pending", "still pending before the reconnect", timeout=0.3)

    assert cli.wait_exit() == 0, "\n".join(cli.stderr)
    assert len(cli.of("hello.ack")) == 2 and cli.of("hello.ack")[1]["resend"] == [uid]
    assert [e["via"] for e in cli.of("open")] == ["resend", "resend"]
    assert len(cli.of("played")) == 1 and len(cli.of("nack")) == 1
    final = relay.view(uid)
    assert final["state"] == "played" and final["reason"] is None


def test_a_scheduled_text_reminder_fires_through_tick_and_plays_with_its_prefix(relay: LiveRelay, clis):
    _, key = relay.enroll_device()
    cli = start_cli(clis, relay, "--key", key, "--utterances", "1", "--idle-exit", "8000")
    cli.wait_event("hello.ack")
    fire_at = datetime.now(timezone.utc) + timedelta(seconds=0.5)
    r = relay.post("/schedule", {"fire_at": fire_at.isoformat(), "text": "Meds 9", "label": "pills"})
    assert r.status_code == 201, r.text
    assert r.json()["composed"] is False and r.json()["kind"] == "reminder"

    opened = cli.wait_event("open", timeout=10)
    assert opened["via"] == "open" and opened["kind"] == "reminder" and opened["words"] == ["meds", "nine"]
    assert opened["prefix"] == {"mark": spec.prefix_mark(), "tail": spec.tail_for("reminder")} and opened["label"] == "pills"
    assert cli.wait_exit() == 0, "\n".join(cli.stderr)
    assert relay.get("/schedule").json() == []
    [view] = relay.get("/utterances").json()
    assert view["id"] == opened["id"] and view["state"] == "played" and view["kind"] == "reminder"
    assert view["source"] == "sender"


def test_the_cap_refuses_the_newest_with_429_queue_full(tmp_path, device_cli):
    with LiveRelay(tmp_path, outbox_cap=2) as relay:
        for text in ("one", "two"):
            assert relay.post("/utterances", {"text": text}).status_code == 201
        r = relay.post("/utterances", {"text": "three"})
        assert r.status_code == 429 and r.json()["reason"] == "queue_full"
        assert r.json()["detail"] == {"active": 2, "cap": 2}
        assert relay.client.get("/health").json()["caps"]["outbox"] == 2


def test_over_budget_is_413_with_both_numbers(relay: LiveRelay):
    words = " ".join(["word"] * 64)
    r = relay.post("/utterances", {"text": words})
    assert r.status_code == 413, r.text
    body = r.json()
    assert body["reason"] == "over_budget"
    assert body["detail"]["budget_ms"] == relay.settings.budget_ms
    assert body["detail"]["duration_ms"] > relay.settings.budget_ms
    assert relay.get("/utterances").json() == []


def test_a_wrong_device_key_is_refused_and_the_socket_closes_with_4401(relay: LiveRelay):
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect

    with connect(relay.ws, open_timeout=5, close_timeout=5) as ws:
        ws.send(json.dumps({"type": "hello", "v": 1, "device_key": "wrong-key-wrong-key-wrong-key",
                            "profile": "single_actuator", "spec_version": spec.spec_version()}))
        err = json.loads(ws.recv(timeout=5))
        assert err["type"] == "error" and err["reason"] == "unauthorized"
        with pytest.raises(ConnectionClosed) as closed:
            ws.recv(timeout=5)
        assert closed.value.rcvd is not None and closed.value.rcvd.code == 4401
    assert relay.client.get("/health").json()["devices_connected"] == 0
